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
                    takeoff_point: tuple[float, float] | None) -> dict:
    """Combine canonical adsb.lol data with track-derived takeoff coords.

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

    origin_ap = airports[best_idx]
    next_idx = best_idx + 1
    dest_ap = airports[next_idx] if next_idx < len(airports) else None

    return {
        "origin": _airport_code(origin_ap),
        "destination": _airport_code(dest_ap) if dest_ap else "",
        "origin_name": _airport_name(origin_ap),
        "destination_name": _airport_name(dest_ap) if dest_ap else "",
        "confidence": "high",
        "reason": f"track matched airports[{best_idx}] ({best_dist:.1f}nm)",
    }
