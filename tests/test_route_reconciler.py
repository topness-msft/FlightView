"""Tests for route reconciliation (adsb.lol schedule × OpenSky live track)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from route_reconciler import find_takeoff_point, reconcile_route  # noqa: E402


# --- Track helpers ----------------------------------------------------------

def _track_path(*points):
    """Build an OpenSky track path. Each point: (time, lat, lon, alt_m, hdg, on_ground)."""
    return list(points)


# Airport coords (rough centres)
IAD = {"icao": "KIAD", "iata": "IAD", "name": "Washington Dulles", "location": "Washington",
       "lat": 38.9445, "lon": -77.4558}
DFW = {"icao": "KDFW", "iata": "DFW", "name": "Dallas-Fort Worth", "location": "Dallas",
       "lat": 32.8998, "lon": -97.0403}
CLT = {"icao": "KCLT", "iata": "CLT", "name": "Charlotte Douglas", "location": "Charlotte",
       "lat": 35.2140, "lon": -80.9431}
BOS = {"icao": "KBOS", "iata": "BOS", "name": "Boston Logan", "location": "Boston",
       "lat": 42.3656, "lon": -71.0096}
RDU = {"icao": "KRDU", "iata": "RDU", "name": "Raleigh Durham", "location": "Raleigh",
       "lat": 35.8776, "lon": -78.7875}
KEF = {"icao": "BIKF", "iata": "KEF", "name": "Keflavik", "location": "Reykjavik",
       "lat": 63.985, "lon": -22.6056}


# --- find_takeoff_point tests ----------------------------------------------

class TestFindTakeoffPoint:
    def test_low_alt_first_point_is_takeoff(self):
        path = _track_path(
            (1000, 35.87, -78.79, 0, 225, False),     # RDU on ground
            (1200, 36.10, -78.50, 1500, 30, False),   # climbing
        )
        pt = find_takeoff_point(path)
        assert pt == (35.87, -78.79)

    def test_high_first_point_is_unknown(self):
        # Path picked up mid-flight at cruise — no confident takeoff
        path = _track_path(
            (1000, 40.0, -75.0, 10000, 90, False),
            (1100, 40.5, -74.0, 10500, 90, False),
        )
        assert find_takeoff_point(path) is None

    def test_none_alt_in_first_point_is_unknown(self):
        path = _track_path(
            (1000, 40.0, -75.0, None, 90, False),
            (1100, 40.5, -74.0, 200, 90, False),
        )
        assert find_takeoff_point(path) is None

    def test_empty_path_returns_none(self):
        assert find_takeoff_point([]) is None

    def test_none_path_returns_none(self):
        assert find_takeoff_point(None) is None

    def test_threshold_boundary_200m(self):
        # Exactly at 200m should count as takeoff
        path = _track_path((1000, 40.0, -75.0, 200, 90, False))
        assert find_takeoff_point(path) == (40.0, -75.0)

    def test_just_above_threshold_is_unknown(self):
        path = _track_path((1000, 40.0, -75.0, 250, 90, False))
        assert find_takeoff_point(path) is None


# --- reconcile_route tests --------------------------------------------------

class TestReconcileRoute:
    def test_no_adsb_no_track_returns_suppress(self):
        result = reconcile_route(None, None)
        assert result["origin"] == ""
        assert result["destination"] == ""
        assert result["confidence"] == "suppress"

    def test_adsb_no_track_uses_adsb_when_non_circular(self):
        adsb = {"airports": [IAD, DFW]}
        result = reconcile_route(adsb, None)
        assert result["origin"] == "IAD"
        assert result["destination"] == "DFW"
        assert result["confidence"] == "medium"

    def test_adsb_no_track_suppresses_circular(self):
        # Same first/last airport — clear stale data (e.g., CLT-CLT collapse)
        adsb = {"airports": [CLT, CLT]}
        result = reconcile_route(adsb, None)
        assert result["origin"] == ""
        assert result["destination"] == ""
        assert result["confidence"] == "suppress"

    def test_adsb_no_track_suppresses_circular_multi_leg(self):
        # CLT-BOS-CLT: first and last are same — naive collapse would say CLT-CLT
        adsb = {"airports": [CLT, BOS, CLT]}
        result = reconcile_route(adsb, None)
        assert result["origin"] == ""
        assert result["destination"] == ""
        assert result["confidence"] == "suppress"

    def test_track_match_first_airport_uses_first_leg(self):
        # ICE820 case: takeoff at RDU, adsb says RDU-KEF
        adsb = {"airports": [RDU, KEF]}
        takeoff = (35.8776, -78.7875)  # RDU exact
        result = reconcile_route(adsb, takeoff)
        assert result["origin"] == "RDU"
        assert result["destination"] == "KEF"
        assert result["confidence"] == "high"

    def test_track_match_middle_airport_uses_next_leg(self):
        # Three-leg route, takeoff at middle airport
        adsb = {"airports": [CLT, BOS, IAD]}
        takeoff = (42.3656, -71.0096)  # BOS
        result = reconcile_route(adsb, takeoff)
        assert result["origin"] == "BOS"
        assert result["destination"] == "IAD"
        assert result["confidence"] == "high"

    def test_track_match_last_airport_has_no_next_leg(self):
        # Takeoff at terminal airport — no next leg known
        adsb = {"airports": [CLT, BOS, IAD]}
        takeoff = (38.9445, -77.4558)  # IAD
        result = reconcile_route(adsb, takeoff)
        assert result["origin"] == "IAD"
        assert result["destination"] == ""
        assert result["confidence"] == "high"

    def test_track_no_match_suppresses_stale_adsb(self):
        # AAL1904 today: adsb says CLT-BOS-CLT but plane took off from IAD
        adsb = {"airports": [CLT, BOS, CLT]}
        takeoff = (38.9445, -77.4558)  # IAD — not in adsb list
        result = reconcile_route(adsb, takeoff)
        assert result["origin"] == ""
        assert result["destination"] == ""
        assert result["confidence"] == "suppress"

    def test_track_threshold_5nm_match(self):
        # Aircraft slightly off airport centre — within 5nm should still match
        adsb = {"airports": [IAD, DFW]}
        # ~3nm NE of IAD
        takeoff = (38.99, -77.41)
        result = reconcile_route(adsb, takeoff)
        assert result["origin"] == "IAD"
        assert result["destination"] == "DFW"
        assert result["confidence"] == "high"

    def test_track_far_outside_threshold_suppresses(self):
        # Takeoff 50nm from any adsb airport
        adsb = {"airports": [IAD, DFW]}
        takeoff = (40.5, -75.0)  # near Philadelphia, not in list
        result = reconcile_route(adsb, takeoff)
        assert result["confidence"] == "suppress"

    def test_track_duplicate_airports_picks_first_occurrence(self):
        # CLT-BOS-CLT, takeoff at CLT → use outbound leg CLT→BOS (first match)
        adsb = {"airports": [CLT, BOS, CLT]}
        takeoff = (35.214, -80.943)  # CLT
        result = reconcile_route(adsb, takeoff)
        assert result["origin"] == "CLT"
        assert result["destination"] == "BOS"
        assert result["confidence"] == "high"

    def test_track_return_leg_of_circular(self):
        # CLT-BOS-CLT, takeoff at BOS → return leg BOS→CLT
        adsb = {"airports": [CLT, BOS, CLT]}
        takeoff = (42.3656, -71.0096)  # BOS
        result = reconcile_route(adsb, takeoff)
        assert result["origin"] == "BOS"
        assert result["destination"] == "CLT"
        assert result["confidence"] == "high"

    def test_adsb_with_no_airports_field(self):
        # Defensive: adsb response missing airports list
        adsb = {}
        result = reconcile_route(adsb, (35.0, -78.0))
        assert result["confidence"] == "suppress"

    def test_adsb_with_empty_airports_list(self):
        adsb = {"airports": []}
        result = reconcile_route(adsb, (35.0, -78.0))
        assert result["confidence"] == "suppress"

    def test_origin_name_preserved(self):
        adsb = {"airports": [RDU, KEF]}
        takeoff = (35.8776, -78.7875)
        result = reconcile_route(adsb, takeoff)
        assert result["origin_name"] == "Raleigh"
        assert result["destination_name"] == "Reykjavik"

    def test_airport_with_no_iata_uses_icao(self):
        # Some smaller airports may lack IATA codes
        ap = {"icao": "KXYZ", "iata": "", "name": "Tiny Field", "location": "Nowhere",
              "lat": 40.0, "lon": -75.0}
        adsb = {"airports": [ap, DFW]}
        takeoff = (40.0, -75.0)
        result = reconcile_route(adsb, takeoff)
        assert result["origin"] == "KXYZ"
        assert result["destination"] == "DFW"
