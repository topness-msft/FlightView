"""Contract and snapshot regression tests for the read-only companion feed."""

import json
import os
import sys
import threading
from unittest.mock import Mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import app as flight_app
import state_manager
from state_manager import AircraftStateManager


def aircraft(icao="a00001", distance=1000, **fields):
    return {
        "icao24": icao,
        "callsign_raw": "UAL123",
        "flight_display": "UA 123",
        "airline": "United Airlines",
        "aircraft_type": "Boeing 737 MAX 9",
        "typecode": "B39M",
        "registration": "N123AB",
        "distance_ft": distance,
        "altitude_ft": 2000,
        "bearing": 90,
        "heading": 270,
        "latitude": 47.6,
        "longitude": -122.3,
        **fields,
    }


@pytest.fixture
def clock(monkeypatch):
    value = {"mono": 100.0, "wall": 1700000000.0}
    monkeypatch.setattr(state_manager.time, "monotonic", lambda: value["mono"])
    monkeypatch.setattr(state_manager.time, "time", lambda: value["wall"])
    return value


@pytest.fixture
def feed(monkeypatch):
    manager = AircraftStateManager()
    monkeypatch.setattr(flight_app, "state_mgr", manager)
    monkeypatch.setattr(flight_app, "_health", {
        "status": "ok", "data_source": "mock", "message": "", "last_success": None,
    })
    monkeypatch.setattr(flight_app.config, "POLL_INTERVAL_SEC", 5)
    monkeypatch.setattr(flight_app.config, "RADAR_RADIUS_FT", 60000)
    return manager, flight_app.app.test_client()


def get_feed(client):
    response = client.get("/api/v1/display")
    assert response.status_code == 200
    assert response.content_type == "application/json"
    assert response.headers["Cache-Control"] == "no-store"
    return response.get_json()


def test_startup_is_not_fresh_empty_sky(feed):
    _, client = feed
    body = get_feed(client)
    assert body["schema_version"] == 1
    assert body["display"] is None
    assert body["aircraft"] == []
    assert body["freshness"] == {
        "source_state_observed_at": None,
        "state_age_ms": None,
        "stale_after_ms": 15000,
        "is_initial": True,
        "is_stale": True,
    }


def test_successful_empty_observation_is_fresh(feed, clock):
    manager, client = feed
    manager.update([])
    body = get_feed(client)
    assert body["display"] is None
    assert body["aircraft"] == []
    assert body["freshness"]["state_age_ms"] == 0
    assert body["freshness"]["is_initial"] is False
    assert body["freshness"]["is_stale"] is False


def test_source_age_is_monotonic_and_only_updates_on_observation(feed, clock):
    manager, client = feed
    manager.update([aircraft()])
    first = get_feed(client)
    clock["mono"] += 16
    clock["wall"] -= 3600
    manager.enrich_active("a00001", {"route_origin": "SEA", "route_destination": "ORD"})
    flight_app._health["last_success"] = clock["wall"]
    stale = get_feed(client)
    assert stale["display"]["route_origin"] == "SEA"
    assert stale["freshness"]["state_age_ms"] == 16000
    assert stale["freshness"]["is_stale"] is True
    assert stale["freshness"]["source_state_observed_at"] == first["freshness"]["source_state_observed_at"]
    manager.update([aircraft()])
    assert get_feed(client)["freshness"]["state_age_ms"] == 0


def test_stale_threshold_respects_slow_source_poll(feed, clock, monkeypatch):
    manager, client = feed
    monkeypatch.setattr(flight_app.config, "POLL_INTERVAL_SEC", 15)
    manager.update([])
    clock["mono"] += 30
    body = get_feed(client)
    assert body["freshness"]["stale_after_ms"] == 45000
    assert not body["freshness"]["is_stale"]
    clock["mono"] += 15
    assert get_feed(client)["freshness"]["is_stale"]


def test_failed_update_does_not_renew_observation(feed, clock, monkeypatch):
    manager, client = feed
    manager.update([aircraft()])
    clock["mono"] += 20
    monkeypatch.setattr(manager, "_update_locked", Mock(side_effect=RuntimeError("failed update")))
    with pytest.raises(RuntimeError):
        manager.update([])
    assert get_feed(client)["freshness"]["state_age_ms"] == 20000


def test_snapshot_is_detached_in_both_directions(clock):
    manager = AircraftStateManager()
    manager.update([aircraft(route_origin="SEA", route_destination="ORD")])
    snapshot = manager.get_display_snapshot()
    manager.enrich_active("a00001", {"route_origin": "LAX"})
    assert snapshot["display"]["route_origin"] == "SEA"
    assert snapshot["aircraft_list"][0]["route_origin"] == "SEA"
    snapshot["display"]["airline"] = "Changed"
    snapshot["aircraft_list"].clear()
    assert manager.get_display_state()["display"]["airline"] == "United Airlines"
    assert len(manager.get_display_state()["aircraft_list"]) == 1


def test_snapshot_copies_routes_under_writer_lock():
    manager = AircraftStateManager()
    manager.update([aircraft(route_origin="SEA", route_destination="ORD")])
    errors = []

    def update_routes():
        for i in range(300):
            route = ("LAX", "JFK") if i % 2 else ("SEA", "ORD")
            manager.enrich_active("a00001", {
                "route_origin": route[0], "route_destination": route[1],
            })

    writer = threading.Thread(target=update_routes)
    writer.start()
    for _ in range(300):
        snapshot = manager.get_display_snapshot()
        display = snapshot["display"]
        summary = snapshot["aircraft_list"][0]
        if (display["route_origin"], display["route_destination"]) not in {("SEA", "ORD"), ("LAX", "JFK")}:
            errors.append(display)
        assert display["route_origin"] == summary["route_origin"]
    writer.join(timeout=5)
    assert not writer.is_alive()
    assert not errors


def test_sticky_display_is_authoritative_and_not_lost_to_cap(feed):
    manager, client = feed
    manager.update([aircraft(distance=1400)])
    others = [aircraft(f"b{i:05x}", distance=100 + i) for i in range(40)]
    manager.update(others + [aircraft(distance=1400)])
    body = get_feed(client)
    assert body["display"]["icao24"] == "a00001"
    assert len(body["aircraft"]) == 32
    assert body["counts"] == {
        "total_aircraft": 41, "nearby_aircraft": 41,
        "returned_aircraft": 32, "truncated": True,
    }
    assert "a00001" not in [ac["icao24"] for ac in body["aircraft"]]
    manager.update(others + [aircraft(distance=2000)])
    assert get_feed(client)["display"]["icao24"] == "b00000"


def test_far_only_returns_radar_and_effective_zone_scales(feed):
    manager, client = feed
    manager.update([aircraft(distance=9000)], near_radius_ft=3000)
    body = get_feed(client)
    assert body["display"] is None
    assert len(body["aircraft"]) == 1
    assert body["counts"]["nearby_aircraft"] == 0
    assert body["zones"] == {"near_radius_ft": 3000, "radar_radius_ft": 60000}


def test_values_units_and_missing_data(feed):
    manager, client = feed
    manager.update([aircraft(velocity_kts=0, vertical_rate_fpm=float("nan"), heading=float("inf"))])
    display = get_feed(client)["display"]
    assert display["velocity_kts"] == 0
    assert display["vertical_rate_fpm"] is None
    assert display["heading"] is None
    assert display["route_origin"] == ""
    assert display["registration"] == "N123AB"
    assert display["aircraft_type"] == "Boeing 737 MAX 9"
    assert display["callsign"] == "UAL123"
    assert "latitude" not in display


def test_csv_model_resolution_reaches_v1_display(feed):
    manager, client = feed
    enriched = manager.enrich_aircraft(
        {
            "icao24": "a7c881",
            "callsign": "EJA606",
            "distance_ft": 1000,
            "altitude_ft": 2000,
            "bearing": 90,
            "compass": "E",
        },
        {"airline": "NetJets", "display": "EJA606"},
        {
            "typecode": "E550",
            "manufacturer": "Embraer",
            "model": "Legacy 500",
            "registration": "N550EJ",
        },
        None,
    )
    manager.update([enriched])

    display = get_feed(client)["display"]

    assert display["typecode"] == "E550"
    assert display["aircraft_type"] == "Embraer Legacy 500"
    assert display["registration"] == "N550EJ"


def test_code_only_airframe_metadata_remains_valid_v1_display(feed):
    manager, client = feed
    enriched = manager.enrich_aircraft(
        {
            "icao24": "a7c881",
            "callsign": "EJA606",
            "distance_ft": 1000,
            "altitude_ft": 2000,
            "bearing": 90,
            "compass": "E",
        },
        {"airline": "NetJets", "display": "EJA606"},
        {"typecode": "E550", "manufacturer": "", "model": "", "registration": ""},
        None,
    )
    manager.update([enriched])

    display = get_feed(client)["display"]

    assert display["typecode"] == "E550"
    assert display["aircraft_type"] == "E550"
    assert display["registration"] == ""


@pytest.mark.parametrize("value", [True, "120", [], float("-inf"), 10 ** 400])
def test_unusable_numerics_remain_unknown(feed, value):
    manager, client = feed
    manager.update([aircraft(velocity_kts=value)])
    assert get_feed(client)["display"]["velocity_kts"] is None


def test_normal_maximum_aircraft_payload_meets_target(feed):
    manager, client = feed
    manager.update([
        aircraft(f"a{i:05x}", route_origin="SEA", route_destination="ORD",
                 origin_city="Seattle", destination_city="Chicago")
        for i in range(32)
    ])
    response = client.get("/api/v1/display")
    assert response.status_code == 200
    assert len(response.data) <= 32 * 1024
    assert response.get_json()["counts"]["truncated"] is False
    assert client.post("/api/v1/display", json={}).status_code == 405


def test_health_does_not_expose_raw_receiver_error_or_configuration(feed):
    manager, client = feed
    manager.update([aircraft()])
    flight_app._health.update(
        status="error", data_source="rtlsdr",
        message="Cannot connect to http://user:secret@receiver.local:8080",
    )
    body = get_feed(client)
    assert body["health"]["status"] == "error"
    assert body["health"]["message"] == "Aircraft data source unavailable"
    wire = json.dumps(body)
    for private in ("secret", "receiver.local", "home_lat", "latitude", "route_checked_at", "inflight"):
        assert private not in wire
    assert body["display"] is not None


def test_wire_allowlist_and_utf8_bounds(feed):
    from display_projection import TEXT_LIMITS

    manager, client = feed
    fields = {key: "\U0001f680" * 200 for key in TEXT_LIMITS if key != "icao24"}
    manager.update([aircraft(**fields)])
    body = get_feed(client)
    assert set(body) == {"schema_version", "display", "aircraft", "counts", "zones", "freshness", "health", "server_version"}
    for key, limit in TEXT_LIMITS.items():
        text = body["display"][key]
        assert len(text.encode("utf-8")) <= limit
        assert "\ufffd" not in text


@pytest.mark.parametrize("text", ["\U0001f680", "\u0001", '"\\', "\u00e9"])
def test_worst_case_serialized_response_is_bounded(feed, text):
    from display_projection import MAX_BODY_BYTES, TEXT_LIMITS

    manager, client = feed
    fields = {key: text * 300 for key in TEXT_LIMITS if key != "icao24"}
    manager.update([aircraft(f"a{i:05x}", **fields) for i in range(40)])
    response = client.get("/api/v1/display")
    assert response.status_code == 200
    assert len(response.data) <= MAX_BODY_BYTES
    assert response.get_json()["counts"]["truncated"]


def test_get_has_no_upstream_or_selection_side_effects(feed, clock, monkeypatch):
    manager, client = feed
    manager.update([aircraft()])
    prohibited = []
    for obj, name in [
        (flight_app, "_fetch_from_source"), (flight_app, "_schedule_route_prefetches"),
        (flight_app.route_client, "get_route"), (flight_app.socketio, "emit"),
        (manager, "update"), (manager, "enrich_active"),
    ]:
        mock = Mock(side_effect=AssertionError(f"GET called {name}"))
        monkeypatch.setattr(obj, name, mock)
        prohibited.append(mock)
    before = manager.get_display_snapshot()
    for _ in range(3):
        get_feed(client)
    assert manager.get_display_snapshot() == before
    for mock in prohibited:
        mock.assert_not_called()
    legacy = client.get("/api/state").get_json()
    assert set(legacy) == {"active", "inflight"}


def test_server_body_guard_returns_small_explicit_error(feed, monkeypatch):
    import display_projection

    _, client = feed
    monkeypatch.setattr(display_projection, "MAX_BODY_BYTES", 10)
    response = client.get("/api/v1/display")
    assert response.status_code == 503
    assert response.get_json() == {"error": "Display feed unavailable"}
    assert response.headers["Cache-Control"] == "no-store"


def test_invalid_radar_config_is_not_silently_substituted(feed, monkeypatch):
    _, client = feed
    monkeypatch.setattr(flight_app.config, "RADAR_RADIUS_FT", 0)
    assert client.get("/api/v1/display").status_code == 503
