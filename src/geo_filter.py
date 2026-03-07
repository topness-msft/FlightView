"""Geographic filtering for FlightView.

Filters aircraft by distance from home location and altitude,
computing bearing and distance for display.
"""

import logging
import math

logger = logging.getLogger(__name__)

EARTH_RADIUS_FT = 20_902_231  # 3959 miles in feet

_COMPASS_DIRECTIONS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def haversine_distance_ft(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance in feet between two lat/lon points."""
    lat1, lon1, lat2, lon2 = (math.radians(v) for v in (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_FT * c


def bearing_from(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the bearing in degrees (0-360) from point 1 to point 2."""
    lat1, lon1, lat2, lon2 = (math.radians(v) for v in (lat1, lon1, lat2, lon2))
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return math.degrees(math.atan2(x, y)) % 360


def compass_direction(bearing: float) -> str:
    """Convert a bearing (0-360) to a compass direction (N, NE, E, …)."""
    index = round(bearing / 45) % 8
    return _COMPASS_DIRECTIONS[index]


def filter_aircraft(
    aircraft_list: list[dict],
    home_lat: float,
    home_lon: float,
    radius_ft: float,
    altitude_limit_ft: float,
) -> list[dict]:
    """Filter aircraft by distance and altitude, enriching with geo fields.

    Returns aircraft within *radius_ft* of home and at or below
    *altitude_limit_ft*, sorted by distance (closest first).
    Aircraft with altitude_ft of None or 0 are excluded.
    """
    results: list[dict] = []

    for ac in aircraft_list:
        alt = ac.get("altitude_ft")
        if not alt:  # None or 0
            continue

        if alt > altitude_limit_ft:
            continue

        ac_lat = ac.get("latitude")
        ac_lon = ac.get("longitude")
        if ac_lat is None or ac_lon is None:
            continue

        dist = haversine_distance_ft(home_lat, home_lon, ac_lat, ac_lon)
        if dist > radius_ft:
            continue

        brng = bearing_from(home_lat, home_lon, ac_lat, ac_lon)
        ac["distance_ft"] = dist
        ac["bearing"] = brng
        ac["compass"] = compass_direction(brng)
        results.append(ac)

    results.sort(key=lambda a: a["distance_ft"])
    logger.debug("Filtered %d aircraft from %d total", len(results), len(aircraft_list))
    return results
