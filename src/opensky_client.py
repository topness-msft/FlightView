"""OpenSky Network API client for FlightView.

Polls the OpenSky REST API for live aircraft state vectors
within a bounding box around the configured home location.
"""

import logging
import math

import requests

from config import config

logger = logging.getLogger(__name__)

# Conversion constants
METERS_TO_FEET = 3.28084
MPS_TO_KNOTS = 1.94384
MPS_TO_FPM = METERS_TO_FEET * 60  # m/s -> ft/min

OPENSKY_API_URL = "https://opensky-network.org/api/states/all"

# Approximate feet per degree of latitude
FEET_PER_DEG_LAT = 364_000


def build_bounding_box(lat: float, lon: float, radius_ft: float) -> tuple[float, float, float, float]:
    """Convert a center point + radius in feet to a lat/lon bounding box.

    Uses 2x the radius to ensure aircraft near edges are not missed.

    Returns:
        (lamin, lamax, lomin, lomax)
    """
    expanded_radius_ft = radius_ft * 2

    delta_lat = expanded_radius_ft / FEET_PER_DEG_LAT
    # Longitude degrees shrink with cosine of latitude
    delta_lon = expanded_radius_ft / (FEET_PER_DEG_LAT * math.cos(math.radians(lat)))

    lamin = lat - delta_lat
    lamax = lat + delta_lat
    lomin = lon - delta_lon
    lomax = lon + delta_lon

    return (lamin, lamax, lomin, lomax)


class OpenSkyClient:
    """Client for polling the OpenSky Network REST API."""

    def __init__(self, cfg=None):
        self.config = cfg or config
        self.bbox = build_bounding_box(
            self.config.HOME_LAT,
            self.config.HOME_LON,
            self.config.RADIUS_LIMIT_FT,
        )

    def fetch_aircraft(self) -> list[dict]:
        """Fetch live aircraft state vectors within the configured bounding box.

        Returns a list of aircraft dicts. Filters out aircraft that are
        on the ground or have no position data. Returns an empty list on
        HTTP errors.
        """
        lamin, lamax, lomin, lomax = self.bbox
        params = {
            "lamin": lamin,
            "lamax": lamax,
            "lomin": lomin,
            "lomax": lomax,
        }

        try:
            response = requests.get(OPENSKY_API_URL, params=params, timeout=15)
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("OpenSky API request failed: %s", exc)
            return []

        try:
            data = response.json()
        except ValueError:
            logger.warning("OpenSky API returned invalid JSON")
            return []

        states = data.get("states")
        if not states:
            logger.debug("No aircraft states returned from OpenSky")
            return []

        aircraft_list = []
        for state in states:
            try:
                on_ground = state[8]
                latitude = state[6]
                longitude = state[5]

                # Filter out grounded aircraft or those with no position
                if on_ground or latitude is None or longitude is None:
                    continue

                baro_altitude = state[7]  # meters, may be None
                velocity = state[9]       # m/s, may be None
                true_track = state[10]    # degrees, may be None
                vertical_rate = state[11] # m/s, may be None

                aircraft_list.append({
                    "icao24": state[0],
                    "callsign": (state[1] or "").strip(),
                    "latitude": latitude,
                    "longitude": longitude,
                    "altitude_ft": round(baro_altitude * METERS_TO_FEET, 1) if baro_altitude is not None else 0.0,
                    "velocity_kts": round(velocity * MPS_TO_KNOTS, 1) if velocity is not None else 0.0,
                    "heading": true_track if true_track is not None else 0.0,
                    "vertical_rate_fpm": round(vertical_rate * MPS_TO_FPM, 1) if vertical_rate is not None else 0.0,
                    "on_ground": on_ground,
                    "last_contact": state[4],
                })
            except (IndexError, TypeError) as exc:
                logger.debug("Skipping malformed state vector: %s", exc)
                continue

        logger.info("Fetched %d airborne aircraft from OpenSky", len(aircraft_list))
        return aircraft_list
