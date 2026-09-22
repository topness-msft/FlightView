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
        assert state["nearby_count"] == 2


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

    def test_csv_model_enriches_unknown_typecode(self):
        mgr = AircraftStateManager()
        aircraft = _make_aircraft("a7c881")
        icao_info = {
            "typecode": "E550",
            "manufacturer": "Embraer",
            "model": "Legacy 500",
            "registration": "N550EJ",
        }

        result = mgr.enrich_aircraft(aircraft, {}, icao_info, None)

        assert result["typecode"] == "E550"
        assert result["aircraft_type"] == "Embraer Legacy 500"
        assert result["registration"] == "N550EJ"

    def test_curated_type_name_beats_csv_model(self):
        mgr = AircraftStateManager()
        aircraft = _make_aircraft("a5f208")
        icao_info = {
            "typecode": "B738",
            "manufacturer": "Boeing",
            "model": "737-8H4",
            "registration": "N482WN",
        }

        result = mgr.enrich_aircraft(aircraft, {}, icao_info, None)

        assert result["aircraft_type"] == "Boeing 737-800"

    def test_receiver_metadata_fills_local_database_gaps(self):
        mgr = AircraftStateManager()
        aircraft = _make_aircraft(
            "a7c881",
            receiver_typecode="E550",
            receiver_registration="N550EJ",
            receiver_description="Embraer Legacy 500",
        )
        icao_info = {
            "typecode": "",
            "manufacturer": "",
            "model": "",
            "registration": "",
        }

        result = mgr.enrich_aircraft(aircraft, {}, icao_info, None)

        assert result["typecode"] == "E550"
        assert result["aircraft_type"] == "Embraer Legacy 500"
        assert result["registration"] == "N550EJ"

    def test_local_database_wins_over_conflicting_receiver_metadata(self):
        mgr = AircraftStateManager()
        aircraft = _make_aircraft(
            "a7c881",
            receiver_typecode="E550",
            receiver_registration="N550EJ",
            receiver_description="Embraer Legacy 500",
        )
        icao_info = {
            "typecode": "B738",
            "manufacturer": "Boeing",
            "model": "737-800",
            "registration": "N482WN",
        }

        result = mgr.enrich_aircraft(aircraft, {}, icao_info, None)

        assert result["typecode"] == "B738"
        assert result["aircraft_type"] == "Boeing 737-800"
        assert result["registration"] == "N482WN"

    def test_unknown_typecode_without_metadata_remains_code_only(self):
        mgr = AircraftStateManager()
        result = mgr.enrich_aircraft(
            _make_aircraft("a7c881"),
            {},
            {"typecode": "E550", "manufacturer": "", "model": "", "registration": ""},
            None,
        )

        assert result["typecode"] == "E550"
        assert result["aircraft_type"] == "E550"
        assert result["registration"] == ""

    @patch("requests.get", side_effect=AssertionError("remote metadata lookup"))
    def test_local_airframe_resolution_does_not_request_remote_metadata(self, mock_get):
        mgr = AircraftStateManager()
        result = mgr.enrich_aircraft(
            _make_aircraft("a7c881"),
            {},
            {
                "typecode": "E550",
                "manufacturer": "Embraer",
                "model": "Legacy 500",
                "registration": "N550EJ",
            },
            None,
        )

        assert result["aircraft_type"] == "Embraer Legacy 500"
        mock_get.assert_not_called()

    def test_code_only_update_does_not_downgrade_airframe_metadata(self):
        mgr = AircraftStateManager()
        rich = _make_aircraft(
            "a7c881",
            callsign="EJA606",
            typecode="E550",
            aircraft_type="Embraer Legacy 500",
            registration="N550EJ",
        )
        mgr.update([rich])

        code_only = _make_aircraft(
            "a7c881",
            callsign="EJA606",
            typecode="E550",
            aircraft_type="E550",
            registration="",
        )
        state = mgr.update([code_only])
        retained = state["display"]

        assert retained["typecode"] == "E550"
        assert retained["aircraft_type"] == "Embraer Legacy 500"
        assert retained["registration"] == "N550EJ"

    def test_rich_airframe_metadata_survives_three_omitted_polls(self):
        mgr = AircraftStateManager()
        mgr.update([_make_aircraft(
            "a7c881",
            typecode="E550",
            aircraft_type="Embraer Legacy 500",
            registration="N550EJ",
        )])

        for _ in range(3):
            state = mgr.update([_make_aircraft(
                "a7c881",
                typecode="",
                aircraft_type="",
                registration="",
            )])
            retained = state["display"]
            assert retained["typecode"] == "E550"
            assert retained["aircraft_type"] == "Embraer Legacy 500"
            assert retained["registration"] == "N550EJ"

    def test_callsign_change_keeps_airframe_metadata_but_drops_route(self):
        mgr = AircraftStateManager()
        mgr.update([_make_aircraft(
            "a7c881",
            callsign="EJA606",
            typecode="E550",
            aircraft_type="Embraer Legacy 500",
            registration="N550EJ",
            route_origin="IAD",
            route_destination="ORD",
            route_display="IAD \u2192 ORD",
        )])

        state = mgr.update([_make_aircraft(
            "a7c881",
            callsign="EJA607",
            typecode="",
            aircraft_type="",
            registration="",
        )])
        retained = state["display"]

        assert retained.get("route_origin", "") == ""
        assert retained.get("route_destination", "") == ""
        assert retained["typecode"] == "E550"
        assert retained["aircraft_type"] == "Embraer Legacy 500"
        assert retained["registration"] == "N550EJ"


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


class TestEnrichActive:
    def test_route_enrichment_updates_current_state_and_summary(self):
        mgr = AircraftStateManager()
        mgr.update([_make_aircraft("a1b2c3", callsign="SWA1234")])

        changed = mgr.enrich_active("a1b2c3", {
            "route_origin": "DAL",
            "route_destination": "ORD",
            "route_display": "DAL \u2192 ORD",
            "origin_city": "Dallas",
            "destination_city": "Chicago",
            "route_checked_at": 123.0,
        }, expected_callsign="SWA1234")

        assert changed is True
        state = mgr.get_display_state()
        assert state["display"]["route_origin"] == "DAL"
        summary = state["aircraft_list"][0]
        assert summary["route_origin"] == "DAL"
        assert summary["route_destination"] == "ORD"
        assert summary["route_display"] == "DAL \u2192 ORD"
        assert summary["route_checked_at"] == 123.0

    def test_route_enrichment_rejects_stale_callsign(self):
        mgr = AircraftStateManager()
        mgr.update([_make_aircraft("a1b2c3", callsign="SWA1234")])

        changed = mgr.enrich_active("a1b2c3", {
            "route_origin": "DAL",
            "route_destination": "ORD",
        }, expected_callsign="UAL123")

        assert changed is False
        assert mgr.get_display_state()["display"].get("route_origin") in (None, "")
