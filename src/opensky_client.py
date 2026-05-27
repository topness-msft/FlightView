"""OpenSky Network API client for FlightView.

Polls the OpenSky REST API for live aircraft state vectors
within a bounding box around the configured home location.
Uses OAuth2 Client Credentials Flow when credentials are configured.
"""

import logging
import math
import threading
import time

import requests

from config import config

logger = logging.getLogger(__name__)

# Conversion constants
METERS_TO_FEET = 3.28084
MPS_TO_KNOTS = 1.94384
MPS_TO_FPM = METERS_TO_FEET * 60  # m/s -> ft/min

OPENSKY_API_URL = "https://opensky-network.org/api/states/all"
OPENSKY_TRACKS_URL = "https://opensky-network.org/api/tracks/all"
OPENSKY_TOKEN_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"

# Approximate feet per degree of latitude
FEET_PER_DEG_LAT = 364_000

# Track cache: takeoff point per airframe is stable for the duration of a
# flight; a short TTL means cross-flight changes naturally expire.
TRACK_CACHE_TTL_SEC = 600
TRACK_NEG_CACHE_TTL_SEC = 300  # shorter so a missed-on-takeoff plane gets retried
TRACK_REQUEST_TIMEOUT_SEC = 6


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
        self._access_token = None
        self._token_expires_at = 0
        # Per-airframe live track cache (icao24 -> {timestamp, path}).
        self._track_cache: dict[str, dict] = {}
        self._track_neg_cache: dict[str, float] = {}
        self._track_lock = threading.Lock()

    def _get_access_token(self) -> str | None:
        """Obtain or refresh an OAuth2 access token."""
        client_id = self.config.OPENSKY_CLIENT_ID
        client_secret = self.config.OPENSKY_CLIENT_SECRET
        if not client_id or not client_secret:
            return None

        if self._access_token and time.time() < self._token_expires_at - 30:
            return self._access_token

        try:
            resp = requests.post(OPENSKY_TOKEN_URL, data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            }, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=10)
            resp.raise_for_status()
            token_data = resp.json()
            self._access_token = token_data["access_token"]
            self._token_expires_at = time.time() + token_data.get("expires_in", 300)
            logger.info("OpenSky OAuth2 token acquired, expires in %ds", token_data.get("expires_in", 300))
            return self._access_token
        except requests.RequestException as exc:
            logger.warning("OpenSky OAuth2 token request failed: %s", exc)
            return None

    def fetch_aircraft(self) -> list[dict]:
        """Fetch live aircraft state vectors within the configured bounding box.

        Returns a list of aircraft dicts. Filters out aircraft that are
        on the ground or have no position data. Returns an empty list on
        HTTP errors.
        """
        # Rebuild bbox each call so config changes take effect
        lamin, lamax, lomin, lomax = build_bounding_box(
            self.config.HOME_LAT,
            self.config.HOME_LON,
            self.config.RADAR_RADIUS_FT,
        )
        params = {
            "lamin": lamin,
            "lamax": lamax,
            "lomin": lomin,
            "lomax": lomax,
        }

        headers = {}
        token = self._get_access_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            response = requests.get(OPENSKY_API_URL, params=params, timeout=15, headers=headers)
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

    def get_track(self, icao24: str) -> list | None:
        """Return the LIVE flight track for an airframe (most recent flight).

        Calls OpenSky's /tracks/all?icao24=X&time=0 endpoint.  Each path point
        is [time, lat, lon, baroAltitude_m, trueTrack, onGround].  The first
        point of the path is typically the takeoff coord (alt=0 on the runway)
        when OpenSky captured the aircraft from the ground up.

        Caching:
          - successes cached TRACK_CACHE_TTL_SEC (10 min) — takeoff coord is
            stable for the duration of a flight.
          - 404s (no flight) cached TRACK_NEG_CACHE_TTL_SEC (5 min) so a plane
            that just appeared but isn't yet indexed gets a retry soon.
          - transient errors NOT negative-cached.

        Returns:
            list of track points, or None on failure / no track available.
        """
        if not icao24:
            return None
        icao24 = icao24.strip().lower()
        now = time.time()

        with self._track_lock:
            cached = self._track_cache.get(icao24)
            if cached and (now - cached["timestamp"]) < TRACK_CACHE_TTL_SEC:
                return cached["path"]
            neg_ts = self._track_neg_cache.get(icao24)
            if neg_ts and (now - neg_ts) < TRACK_NEG_CACHE_TTL_SEC:
                return None
            # Garbage-collect oversized caches
            if len(self._track_cache) > 200:
                self._track_cache = {
                    k: v for k, v in self._track_cache.items()
                    if (now - v["timestamp"]) < TRACK_CACHE_TTL_SEC
                }
            if len(self._track_neg_cache) > 200:
                self._track_neg_cache = {
                    k: v for k, v in self._track_neg_cache.items()
                    if (now - v) < TRACK_NEG_CACHE_TTL_SEC
                }

        headers = {}
        token = self._get_access_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            resp = requests.get(
                OPENSKY_TRACKS_URL,
                params={"icao24": icao24, "time": 0},
                timeout=TRACK_REQUEST_TIMEOUT_SEC,
                headers=headers,
            )
            if resp.status_code == 404:
                with self._track_lock:
                    self._track_neg_cache[icao24] = now
                return None
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            logger.warning("OpenSky tracks/all request failed for %s: %s", icao24, exc)
            return None
        except ValueError:
            logger.warning("OpenSky tracks/all returned invalid JSON for %s", icao24)
            return None

        path = (data or {}).get("path") or []
        if not path:
            with self._track_lock:
                self._track_neg_cache[icao24] = now
            return None

        with self._track_lock:
            self._track_cache[icao24] = {"timestamp": now, "path": path}
            self._track_neg_cache.pop(icao24, None)

        logger.debug("OpenSky track for %s: %d points, first=%s", icao24, len(path), path[0])
        return path

