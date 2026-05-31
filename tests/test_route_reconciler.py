"""Tests for route reconciliation (adsb.lol schedule × OpenSky live track)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from route_reconciler import find_takeoff_point, reconcile_route, compute_track_phase  # noqa: E402


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
        # Path picked up mid-flight at cruise — no confident origin signal
        path = _track_path(
            (1000, 40.0, -75.0, 10000, 90, False),
            (1100, 40.5, -74.0, 10500, 90, False),
        )
        assert find_takeoff_point(path) is None

    def test_climbing_aircraft_below_threshold_counts(self):
        # OpenSky often picks up planes during climb-out at a few thousand
        # feet — still a strong origin signal.
        path = _track_path(
            (1000, 36.09, -86.69, 304, 194, False),  # near BNA, climbing
            (1200, 36.20, -86.50, 1500, 30, False),
        )
        assert find_takeoff_point(path) == (36.09, -86.69)

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

    def test_threshold_boundary(self):
        # Exactly at TAKEOFF_ALT_THRESHOLD_M should count
        path = _track_path((1000, 40.0, -75.0, 1500, 90, False))
        assert find_takeoff_point(path) == (40.0, -75.0)

    def test_just_above_threshold_is_unknown(self):
        path = _track_path((1000, 40.0, -75.0, 1600, 90, False))
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

    def test_track_match_last_airport_treated_as_arrival(self):
        # Track captured near the FINAL airport (no phase signal) — the plane
        # is arriving there, not departing from it.  Use the preceding leg.
        adsb = {"airports": [CLT, BOS, IAD]}
        takeoff = (38.9445, -77.4558)  # IAD
        result = reconcile_route(adsb, takeoff)
        assert result["origin"] == "BOS"
        assert result["destination"] == "IAD"
        assert result["confidence"] == "high"

    def test_track_no_match_suppresses_stale_adsb(self):
        # AAL1904 today: adsb says CLT-BOS-CLT but plane took off from IAD
        adsb = {"airports": [CLT, BOS, CLT]}
        takeoff = (38.9445, -77.4558)  # IAD — not in adsb list
        result = reconcile_route(adsb, takeoff)
        assert result["origin"] == ""
        assert result["destination"] == ""
        assert result["confidence"] == "suppress"

    def test_track_threshold_match(self):
        # Aircraft a few nm from airport centre (typical for climb-out
        # captures) — within match radius.
        adsb = {"airports": [IAD, DFW]}
        # ~10nm SW of IAD
        takeoff = (38.81, -77.58)
        result = reconcile_route(adsb, takeoff)
        assert result["origin"] == "IAD"
        assert result["destination"] == "DFW"
        assert result["confidence"] == "high"

    def test_track_far_outside_threshold_suppresses(self):
        # Real-world case: SWA594 — adsb says MCI-STL, OpenSky takeoff
        # at BNA (Nashville).  BNA is hundreds of nm from MCI/STL.
        adsb = {"airports": [
            {"icao": "KMCI", "iata": "MCI", "name": "Kansas City",
             "location": "Kansas City", "lat": 39.2976, "lon": -94.7139},
            {"icao": "KSTL", "iata": "STL", "name": "St Louis",
             "location": "St Louis", "lat": 38.7487, "lon": -90.3700},
        ]}
        # First track point near BNA
        takeoff = (36.09, -86.69)
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


# --- Phase-aware reconciliation (climb vs descent) --------------------------

MCO = {"icao": "KMCO", "iata": "MCO", "name": "Orlando International",
       "location": "Orlando", "lat": 28.4294, "lon": -81.3090}


class TestReconcileRoutePhase:
    def test_descent_into_final_airport_is_arrival(self):
        # UAL413: scheduled MCO→IAD, OpenSky caught it descending into IAD
        # (home airport). Track start is near IAD; phase=descent must yield
        # the full MCO→IAD route, not "IAD → ?".
        adsb = {"airports": [MCO, IAD]}
        takeoff = (38.9445, -77.4558)  # IAD
        result = reconcile_route(adsb, takeoff, "descent")
        assert result["origin"] == "MCO"
        assert result["destination"] == "IAD"
        assert result["confidence"] == "high"

    def test_climb_from_first_airport_is_departure(self):
        adsb = {"airports": [MCO, IAD]}
        takeoff = (28.4294, -81.3090)  # MCO
        result = reconcile_route(adsb, takeoff, "climb")
        assert result["origin"] == "MCO"
        assert result["destination"] == "IAD"
        assert result["confidence"] == "high"

    def test_two_airport_route_same_result_from_either_end(self):
        # Robustness: matching either endpoint of a 2-airport route gives A→B.
        adsb = {"airports": [MCO, IAD]}
        near_mco = reconcile_route(adsb, (28.4294, -81.3090))  # unknown phase
        near_iad = reconcile_route(adsb, (38.9445, -77.4558))  # unknown phase
        assert (near_mco["origin"], near_mco["destination"]) == ("MCO", "IAD")
        assert (near_iad["origin"], near_iad["destination"]) == ("MCO", "IAD")

    def test_descent_into_scheduled_origin_suppresses(self):
        # Contradictory: descending into the scheduled origin (no prior leg).
        adsb = {"airports": [MCO, IAD]}
        takeoff = (28.4294, -81.3090)  # MCO
        result = reconcile_route(adsb, takeoff, "descent")
        assert result["confidence"] == "suppress"
        assert result["origin"] == ""

    def test_climb_out_of_final_airport_suppresses(self):
        # Contradictory: climbing out of the scheduled final airport.
        adsb = {"airports": [MCO, IAD]}
        takeoff = (38.9445, -77.4558)  # IAD
        result = reconcile_route(adsb, takeoff, "climb")
        assert result["confidence"] == "suppress"
        assert result["destination"] == ""

    def test_descent_picks_arrival_leg_of_multi_leg(self):
        # CLT→BOS→IAD, descending into BOS (middle) → arriving BOS from CLT.
        adsb = {"airports": [CLT, BOS, IAD]}
        takeoff = (42.3656, -71.0096)  # BOS
        result = reconcile_route(adsb, takeoff, "descent")
        assert result["origin"] == "CLT"
        assert result["destination"] == "BOS"

    def test_climb_picks_departure_leg_of_multi_leg(self):
        # CLT→BOS→IAD, climbing out of BOS (middle) → departing BOS to IAD.
        adsb = {"airports": [CLT, BOS, IAD]}
        takeoff = (42.3656, -71.0096)  # BOS
        result = reconcile_route(adsb, takeoff, "climb")
        assert result["origin"] == "BOS"
        assert result["destination"] == "IAD"


class TestComputeTrackPhase:
    def test_climbing_track_is_climb(self):
        path = [
            (1000, 28.43, -81.31, 0, 30, True),
            (1100, 28.50, -81.20, 800, 30, False),
            (1200, 28.60, -81.10, 2000, 30, False),
        ]
        assert compute_track_phase(path) == "climb"

    def test_descending_track_is_descent(self):
        path = [
            (1000, 38.80, -77.60, 1400, 90, False),
            (1100, 38.88, -77.52, 600, 90, False),
            (1200, 38.94, -77.46, 100, 90, False),
        ]
        assert compute_track_phase(path) == "descent"

    def test_level_track_is_unknown(self):
        path = [
            (1000, 40.0, -75.0, 1000, 90, False),
            (1100, 40.1, -74.9, 1010, 90, False),
        ]
        assert compute_track_phase(path) == "unknown"

    def test_empty_or_single_point_is_unknown(self):
        assert compute_track_phase([]) == "unknown"
        assert compute_track_phase(None) == "unknown"
        assert compute_track_phase([(1000, 40.0, -75.0, 500, 90, False)]) == "unknown"

    def test_missing_first_altitude_is_unknown(self):
        path = [
            (1000, 40.0, -75.0, None, 90, False),
            (1100, 40.1, -74.9, 800, 90, False),
        ]
        assert compute_track_phase(path) == "unknown"

    def test_skips_missing_later_altitudes(self):
        path = [
            (1000, 28.43, -81.31, 100, 30, False),
            (1100, 28.50, -81.20, None, 30, False),
            (1200, 28.60, -81.10, 1500, 30, False),
        ]
        assert compute_track_phase(path) == "climb"
