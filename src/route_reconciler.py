"""Route reconciliation: adsb.lol schedule × OpenSky live track.

adsb.lol publishes canonical (often scheduled) routes. Those entries can be:
  - stale (today's actual route differs from the published one), or
  - multi-leg (e.g., CLT-BOS-CLT for round-trip flight numbers).

We reconcile the canonical route against the airframe's actual takeoff
point (sourced from OpenSky's /tracks/all endpoint) to:
  1. Detect stale schedules — when the real takeoff doesn't match any
     airport in the canonical route, suppress to avoid showing wrong data.
  2. Disambiguate multi-leg routes — when the canonical route has more than
     two airports, pick the leg whose origin matches the takeoff point.

The output is a dict with `origin`, `destination`, `origin_name`,
`destination_name`, `confidence`, and `reason`.  Empty origin/destination
+ confidence="suppress" means we deliberately have no route to display.
"""

import logging
import math

logger = logging.getLogger(__name__)

EARTH_RADIUS_NM = 3440.065  # nautical miles
# First track point altitude threshold. We treat any first point at/below
# this as a reliable proxy for origin. Strict thresholds (e.g. 200m) miss
# the common case where OpenSky picked up the plane during the climb-out,
# not on the runway itself. 1500m (~5,000 ft) covers most takeoffs +
# initial climb without picking up cruise-altitude track starts.
TAKEOFF_ALT_THRESHOLD_M = 1500
# Match radius from track point to a canonical airport. Larger than the
# airport itself to account for tracks that start a few miles into the
# climb. Still tight enough that 200+nm-apart airports (e.g. MCI vs BNA)
# never falsely match.
AIRPORT_MATCH_NM = 15.0
# Minimum altitude change (metres) between the track start and a slightly
# later point needed to call the captured phase a climb or descent. Below
# this we treat the trend as ambiguous ("unknown").
PHASE_ALT_DELTA_M = 100.0


def _haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1, lon1, lat2, lon2 = (math.radians(v) for v in (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return EARTH_RADIUS_NM * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def find_takeoff_point(path) -> tuple[float, float] | None:
    """Identify the approximate origin coordinates from an OpenSky track.

    Track path format: list of [time, lat, lon, alt_m, hdg, on_ground].
    Returns (lat, lon) of the FIRST point when its altitude is at/below
    TAKEOFF_ALT_THRESHOLD_M — interpreted as "OpenSky picked the plane up
    on or shortly after takeoff", giving us a coordinate that's a few
    nautical miles from the origin airport at worst.

    Returns None when the first point is high-altitude (track started
    mid-cruise, common for transoceanic flights when OpenSky lacks
    over-water coverage) or when altitude is missing.  Treating "no
    confident origin signal" as "unknown" — instead of "stale schedule"
    — avoids falsely suppressing valid canonical routes for flights
    OpenSky didn't see lifting off.
    """
    if not path:
        return None
    first = path[0]
    try:
        lat = first[1]
        lon = first[2]
        alt_m = first[3]
    except (IndexError, TypeError):
        return None
    if lat is None or lon is None or alt_m is None:
        return None
    if alt_m > TAKEOFF_ALT_THRESHOLD_M:
        return None
    return (float(lat), float(lon))


def compute_track_phase(path) -> str:
    """Classify the captured phase of flight near the track start.

    The track-start coordinate (see :func:`find_takeoff_point`) sits near one
    of the canonical route's airports, but on its own it can't tell us whether
    that airport is the ORIGIN (we caught the climb-out) or the DESTINATION
    (OpenSky only picked the plane up on descent, common for flights arriving
    at an airport near the viewer).

    We disambiguate by the altitude trend right after the start: comparing the
    first usable altitude against a slightly later one.

    Returns:
        "climb"   — gaining altitude → start airport is the origin.
        "descent" — losing altitude → start airport is the destination.
        "unknown" — flat / insufficient / missing data.
    """
    if not path or len(path) < 2:
        return "unknown"

    def _alt(p):
        try:
            return p[3]
        except (IndexError, TypeError):
            return None

    first_alt = _alt(path[0])
    if first_alt is None:
        return "unknown"

    # Use the furthest valid altitude within the first few points so a single
    # flat pair doesn't mask the trend, while staying close to the start so a
    # full climb-cruise-descent track is judged by its departure end.
    later_alt = None
    for p in path[1:5]:
        a = _alt(p)
        if a is not None:
            later_alt = a
    if later_alt is None:
        return "unknown"

    if later_alt - first_alt >= PHASE_ALT_DELTA_M:
        return "climb"
    if first_alt - later_alt >= PHASE_ALT_DELTA_M:
        return "descent"
    return "unknown"


def _airport_code(ap: dict) -> str:
    return (ap.get("iata") or ap.get("icao") or "").strip()


def _airport_name(ap: dict) -> str:
    return (ap.get("location") or ap.get("name") or "").strip()


def _is_circular(airports: list[dict]) -> bool:
    """True if the route's first and last airports are the same."""
    if len(airports) < 2:
        return False
    first = _airport_code(airports[0]).upper()
    last = _airport_code(airports[-1]).upper()
    return bool(first) and first == last


def reconcile_route(adsb_route: dict | None,
                    takeoff_point: tuple[float, float] | None,
                    phase: str = "unknown") -> dict:
    """Combine canonical adsb.lol data with track-derived takeoff coords.

    Args:
        adsb_route: canonical route dict from adsb.lol (has an ``airports``
            list), or None.
        takeoff_point: (lat, lon) of the track start near an airport, or None.
        phase: "climb" | "descent" | "unknown" — the altitude trend at the
            track start (see :func:`compute_track_phase`).  Disambiguates
            whether the matched airport is the origin (climb) or the
            destination (descent).

    Returns:
        dict with:
          origin: str  (IATA preferred, ICAO fallback, "" if suppressed)
          destination: str  ("" if not known)
          origin_name: str
          destination_name: str
          confidence: "high" | "medium" | "suppress"
          reason: str  (for logging/debug)
    """
    blank = {
        "origin": "", "destination": "",
        "origin_name": "", "destination_name": "",
        "confidence": "suppress", "reason": "",
    }

    airports = (adsb_route or {}).get("airports") or []

    # No canonical route at all
    if not airports or len(airports) < 2:
        return {**blank, "reason": "no adsb airports"}

    # No track → can't validate
    if takeoff_point is None:
        if _is_circular(airports):
            # Multi-leg / round-trip schedule with same first/last airport.
            # Naively picking first+last would display "CLT → CLT" — clearly
            # wrong.  Without a track we can't pick a leg, so suppress.
            return {**blank, "reason": "circular adsb, no track"}
        return {
            "origin": _airport_code(airports[0]),
            "destination": _airport_code(airports[-1]),
            "origin_name": _airport_name(airports[0]),
            "destination_name": _airport_name(airports[-1]),
            "confidence": "medium",
            "reason": "adsb only (no track validation)",
        }

    # Have both adsb + track — find closest airport to takeoff coords.
    t_lat, t_lon = takeoff_point
    best_idx = -1
    best_dist = float("inf")
    for i, ap in enumerate(airports):
        ap_lat = ap.get("lat")
        ap_lon = ap.get("lon")
        if ap_lat is None or ap_lon is None:
            continue
        d = _haversine_nm(t_lat, t_lon, float(ap_lat), float(ap_lon))
        if d < best_dist:
            best_dist = d
            best_idx = i

    if best_idx == -1 or best_dist > AIRPORT_MATCH_NM:
        # adsb route doesn't include the actual takeoff airport — stale data.
        return {**blank, "reason": f"track does not match any adsb airport (best {best_dist:.1f}nm)"}

    # The matched airport is closest to where OpenSky first saw the plane at
    # low altitude. Whether that airport is the origin or the destination
    # depends on the captured phase of flight:
    #   - climb   → plane is leaving it          → it's the ORIGIN, next leg is dest.
    #   - descent → plane is arriving at it       → it's the DESTINATION, prev leg is origin.
    #   - unknown → fall back to position: matching the FINAL airport almost
    #               always means an arrival (track caught on descent near the
    #               viewer's home airport); anything earlier means a departure.
    last_idx = len(airports) - 1
    if phase == "descent":
        origin_idx, dest_idx = best_idx - 1, best_idx
    elif phase == "climb":
        origin_idx, dest_idx = best_idx, best_idx + 1
    elif best_idx == last_idx:
        origin_idx, dest_idx = best_idx - 1, best_idx
    else:
        origin_idx, dest_idx = best_idx, best_idx + 1

    if origin_idx < 0 or dest_idx > last_idx:
        # Contradictory signal: descending into the scheduled origin, or
        # climbing out of the scheduled final destination. The schedule is
        # likely stale/reversed and we can't infer the missing leg, so we'd
        # rather show nothing than guess.
        return {**blank,
                "reason": f"phase={phase} matched airports[{best_idx}] with no opposite leg ({best_dist:.1f}nm)"}

    origin_ap = airports[origin_idx]
    dest_ap = airports[dest_idx]

    return {
        "origin": _airport_code(origin_ap),
        "destination": _airport_code(dest_ap),
        "origin_name": _airport_name(origin_ap),
        "destination_name": _airport_name(dest_ap),
        "confidence": "high",
        "reason": f"phase={phase} matched airports[{best_idx}] → {origin_idx}->{dest_idx} ({best_dist:.1f}nm)",
    }
