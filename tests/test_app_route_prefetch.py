"""Tests for async route prefetch behavior."""

import os
import sys
from unittest.mock import Mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import app as flight_app  # noqa: E402
from state_manager import AircraftStateManager  # noqa: E402


def _clear_route_state():
    with flight_app._route_inflight_lock:
        flight_app._route_inflight.clear()


def _active_aircraft(callsign="SWA1234"):
    return {
        "icao24": "a1b2c3",
        "callsign": callsign,
        "callsign_raw": callsign,
        "distance_ft": 1000,
        "altitude_ft": 2000,
        "bearing": 0,
        "compass": "N",
        "airline": "Southwest Airlines",
        "flight_display": "WN 1234",
    }


def test_route_prefetch_emits_updated_state_immediately(monkeypatch):
    _clear_route_state()
    mgr = AircraftStateManager()
    mgr.update([_active_aircraft()])
    monkeypatch.setattr(flight_app, "state_mgr", mgr)
    monkeypatch.setattr(flight_app.route_client, "get_route", lambda callsign: {
        "airports": [
            {"iata": "DAL", "location": "Dallas", "lat": 32.8471, "lon": -96.8518},
            {"iata": "ORD", "location": "Chicago", "lat": 41.9742, "lon": -87.9073},
        ],
    })
    monkeypatch.setattr(flight_app.opensky, "get_track", lambda icao24: [
        [0, 32.85, -96.85, 300, 0, False],
    ])
    emit = Mock()
    monkeypatch.setattr(flight_app, "_emit_current_state", emit)

    flight_app._prefetch_route_async("a1b2c3", "SWA1234")

    state = mgr.get_display_state()
    assert state["display"]["route_origin"] == "DAL"
    assert state["display"]["route_destination"] == "ORD"
    assert state["aircraft_list"][0]["route_checked_at"] is not None
    emit.assert_called_once()


def test_route_prefetch_backfills_blank_receiver_callsign(monkeypatch):
    _clear_route_state()
    mgr = AircraftStateManager()
    mgr.update([_active_aircraft("")])
    monkeypatch.setattr(flight_app, "state_mgr", mgr)
    monkeypatch.setattr(flight_app.opensky, "get_callsign", lambda icao24: "ICE2B")
    monkeypatch.setattr(flight_app.route_client, "get_route", lambda callsign: {
        "airports": [
            {"iata": "IAD", "location": "Washington", "lat": 38.9531, "lon": -77.4565},
            {"iata": "KEF", "location": "Reykjavik", "lat": 63.9850, "lon": -22.6056},
        ],
    })
    monkeypatch.setattr(flight_app.opensky, "get_track", lambda icao24: [
        [0, 38.95, -77.45, 300, 0, False],
    ])
    emit = Mock()
    monkeypatch.setattr(flight_app, "_emit_current_state", emit)

    flight_app._prefetch_route_async("a1b2c3", "", "icao:a1b2c3")

    state = mgr.get_display_state()
    assert state["display"]["callsign_raw"] == "ICE2B"
    assert state["display"]["route_origin"] == "IAD"
    assert state["display"]["route_destination"] == "KEF"
    emit.assert_called_once()


def test_schedule_route_prefetch_queues_blank_callsign_aircraft(monkeypatch):
    _clear_route_state()
    submit = Mock()
    monkeypatch.setattr(flight_app._route_executor, "submit", submit)

    flight_app._schedule_route_prefetches([{
        "icao24": "a1b2c3",
        "callsign_raw": "",
        "route_origin": "",
        "route_checked_at": None,
    }])

    submit.assert_called_once()
    assert submit.call_args.args[1:] == ("a1b2c3", "", "icao:a1b2c3")


def test_pin_flight_uses_reconciler_to_suppress_stale_circular_route(monkeypatch):
    _clear_route_state()
    mgr = AircraftStateManager()
    mgr.update([_active_aircraft("JIA5458")])
    monkeypatch.setattr(flight_app, "state_mgr", mgr)
    monkeypatch.setattr(flight_app.route_client, "get_route", lambda callsign: {
        "origin": "DFW",
        "destination": "DFW",
        "origin_name": "Dallas-Fort Worth",
        "destination_name": "Dallas-Fort Worth",
        "airports": [
            {"iata": "DFW", "location": "Dallas-Fort Worth", "lat": 32.8998, "lon": -97.0403},
            {"iata": "DFW", "location": "Dallas-Fort Worth", "lat": 32.8998, "lon": -97.0403},
        ],
    })
    monkeypatch.setattr(flight_app.opensky, "get_track", lambda icao24: [
        [0, 38.9445, -77.4558, 300, 0, False],
    ])
    emit = Mock()
    monkeypatch.setattr(flight_app, "emit", emit)

    flight_app.handle_pin_flight({"icao24": "a1b2c3", "callsign": "JIA5458"})

    state = mgr.get_display_state()
    assert state["display"].get("route_origin") in (None, "")
    assert state["display"].get("route_destination") in (None, "")
    assert state["display"]["route_checked_at"] is not None
    emit.assert_called_once()


def test_pin_flight_skips_duplicate_inflight_lookup(monkeypatch):
    _clear_route_state()
    with flight_app._route_inflight_lock:
        flight_app._route_inflight.add("UAL1764")
    build = Mock()
    monkeypatch.setattr(flight_app, "_build_route_enrichment", build)

    try:
        flight_app.handle_pin_flight({"icao24": "a05dd8", "callsign": "UAL1764"})
    finally:
        _clear_route_state()

    build.assert_not_called()
