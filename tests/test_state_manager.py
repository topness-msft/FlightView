"""Tests for the state_manager module."""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
from unittest.mock import patch
from state_manager import AircraftStateManager


def _make_aircraft(icao24, callsign="TST100", distance_ft=1000,
                   altitude_ft=2000, compass="N", bearing=0, **kwargs):
    ac = {
        "icao24": icao24,
        "callsign": callsign,
        "distance_ft": distance_ft,
        "altitude_ft": altitude_ft,
        "compass": compass,
        "bearing": bearing,
        "latitude": 40.7,
        "longitude": -74.0,
    }
    ac.update(kwargs)
    return ac


class TestUpdateEmptyList:
    def test_empty_list_returns_zero_count(self):
        mgr = AircraftStateManager()
        state = mgr.update([])
        assert state["nearby_count"] == 0
        assert state["display"] is None
        assert state["aircraft_list"] == []
        assert state["events"] == []


class TestUpdateNewAircraft:
    def test_new_aircraft_triggers_entered_event(self):
        mgr = AircraftStateManager()
        ac = [_make_aircraft("a1b2c3", callsign="SWA1234")]
        state = mgr.update(ac)
        assert state["nearby_count"] == 1
        assert any("entered" in e for e in state["events"])
        assert "SWA1234" in state["events"][0]


class TestStaleRemoval:
    def test_stale_aircraft_removed(self):
        mgr = AircraftStateManager()
        ac = [_make_aircraft("a1b2c3", callsign="SWA1234")]

        # First update: aircraft enters
        mgr.update(ac)

        # Simulate passage of time by manipulating _last_seen
        mgr._last_seen["a1b2c3"] = time.time() - 31

        # Second update: aircraft not in list anymore
        state = mgr.update([])
        assert state["nearby_count"] == 0
        assert any("left" in e for e in state["events"])
        assert "SWA1234" in state["events"][0]


class TestDisplaySelectsClosest:
    def test_closest_is_displayed(self):
        mgr = AircraftStateManager()
        aircraft = [
            _make_aircraft("close", callsign="CLOSE", distance_ft=500),
            _make_aircraft("mid", callsign="MID", distance_ft=1500),
            _make_aircraft("far", callsign="FAR", distance_ft=3000),
        ]
        state = mgr.update(aircraft)
        assert state["display"]["icao24"] == "close"
        assert state["nearby_count"] == 3


class TestAutoAdvanceOnLeave:
    def test_next_closest_shown_when_displayed_leaves(self):
        mgr = AircraftStateManager()
        aircraft = [
            _make_aircraft("first", callsign="FIRST", distance_ft=500),
            _make_aircraft("second", callsign="SECOND", distance_ft=1500),
        ]
        state = mgr.update(aircraft)
        assert state["display"]["icao24"] == "first"

        # First aircraft leaves (stale)
        mgr._last_seen["first"] = time.time() - 31

        state = mgr.update([_make_aircraft("second", callsign="SECOND",
                                           distance_ft=1500)])
        assert state["display"]["icao24"] == "second"
        assert any("left" in e for e in state["events"])


class TestEnrichAircraft:
    def test_merged_output_has_all_fields(self):
        mgr = AircraftStateManager()
        aircraft = {
            "icao24": "a1b2c3",
            "callsign": "SWA1234",
            "distance_ft": 2000,
            "altitude_ft": 3000,
            "bearing": 45,
            "compass": "NE",
            "velocity_kts": 250,
            "heading": 90,
            "vertical_rate_fpm": -500,
        }
        callsign_info = {
            "airline": "Southwest Airlines",
            "iata": "WN",
            "icao": "SWA",
            "flight_number": "1234",
            "display": "WN 1234",
        }
        icao_info = {
            "typecode": "B738",
            "registration": "N12345",
            "manufacturer": "Boeing",
        }
        route_info = {
            "origin": "DAL",
            "destination": "ORD",
        }

        result = mgr.enrich_aircraft(aircraft, callsign_info, icao_info,
                                     route_info)

        assert result["icao24"] == "a1b2c3"
        assert result["airline"] == "Southwest Airlines"
        assert result["flight_number"] == "1234"
        assert result["flight_display"] == "WN 1234"
        assert result["aircraft_type"] == "Boeing 737-800"
        assert result["registration"] == "N12345"
        assert result["route_origin"] == "DAL"
        assert result["route_destination"] == "ORD"
        assert result["route_display"] == "DAL → ORD"
        assert result["altitude_ft"] == 3000
        assert result["velocity_kts"] == 250
        assert result["distance_ft"] == 2000
        assert result["compass"] == "NE"
        assert result["direction"] in ("approaching", "departing", "overhead")

    def test_enrich_with_none_icao_and_route(self):
        mgr = AircraftStateManager()
        aircraft = {
            "icao24": "x1",
            "callsign": "TST",
            "distance_ft": 1000,
            "altitude_ft": 2000,
            "bearing": 0,
            "compass": "N",
        }
        callsign_info = {"airline": "Unknown", "display": "TST"}
        result = mgr.enrich_aircraft(aircraft, callsign_info, None, None)
        assert result["aircraft_type"] == ""
        assert result["route_display"] == ""
        assert result["registration"] == ""


class TestGetDisplayState:
    def test_returns_last_state(self):
        mgr = AircraftStateManager()
        initial = mgr.get_display_state()
        assert initial["display"] is None
        assert initial["nearby_count"] == 0

        ac = [_make_aircraft("a1")]
        mgr.update(ac)
        state = mgr.get_display_state()
        assert state["nearby_count"] == 1
        assert state["display"] is not None
