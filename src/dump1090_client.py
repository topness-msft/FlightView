"""dump1090 / readsb local JSON client for FlightView.

Reads aircraft data from a locally-running dump1090 or readsb decoder
via its HTTP JSON interface.  The decoder handles all SDR/RF work —
this client simply fetches and normalises the JSON output.
"""

import logging
import time

import requests

logger = logging.getLogger(__name__)


class Dump1090Error(Exception):
    """Raised when the dump1090/readsb endpoint is unreachable or unhealthy."""


class Dump1090Client:
    """Client for reading aircraft data from a local dump1090/readsb instance."""

    def __init__(self, base_url: str = "http://localhost:8080"):
        self.base_url = base_url.rstrip("/")
        self._aircraft_url = f"{self.base_url}/data/aircraft.json"
        self._last_success: float | None = None
        self._consecutive_failures: int = 0

    # -- Public API ----------------------------------------------------------

    def fetch_aircraft(self) -> list[dict]:
        """Fetch current aircraft from dump1090 JSON endpoint.

        Returns a list of normalised aircraft dicts compatible with
        the FlightView enrichment pipeline.

        Raises Dump1090Error when the decoder is unreachable so the
        caller can surface the problem instead of silently returning [].
        """
        try:
            resp = requests.get(self._aircraft_url, timeout=5)
            resp.raise_for_status()
        except requests.ConnectionError as exc:
            self._record_failure()
            raise Dump1090Error(
                f"Cannot connect to dump1090 at {self.base_url} — "
                "is the decoder running?"
            ) from exc
        except requests.RequestException as exc:
            self._record_failure()
            raise Dump1090Error(
                f"dump1090 request failed: {exc}"
            ) from exc

        try:
            data = resp.json()
        except ValueError as exc:
            self._record_failure()
            raise Dump1090Error("dump1090 returned invalid JSON") from exc

        self._record_success()

        raw_aircraft = data.get("aircraft", [])
        result = []
        for ac in raw_aircraft:
            parsed = self._parse_aircraft(ac)
            if parsed:
                result.append(parsed)

        logger.info(
            "Fetched %d aircraft from dump1090 (%d raw)",
            len(result), len(raw_aircraft),
        )
        return result

    def health_check(self) -> dict:
        """Quick connectivity check against the decoder.

        Returns a dict with 'ok' (bool), 'message' (str), and
        'last_success' (float timestamp or None).
        """
        try:
            resp = requests.get(self._aircraft_url, timeout=3)
            resp.raise_for_status()
            return {
                "ok": True,
                "message": "dump1090 reachable",
                "last_success": time.time(),
            }
        except requests.RequestException as exc:
            return {
                "ok": False,
                "message": str(exc),
                "last_success": self._last_success,
            }

    @property
    def last_success(self) -> float | None:
        return self._last_success

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    # -- Internal ------------------------------------------------------------

    def _record_success(self) -> None:
        self._last_success = time.time()
        if self._consecutive_failures > 0:
            logger.info(
                "dump1090 connection recovered after %d failure(s)",
                self._consecutive_failures,
            )
        self._consecutive_failures = 0

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures <= 3:
            logger.warning(
                "dump1090 fetch failed (attempt %d)",
                self._consecutive_failures,
            )
        else:
            logger.error(
                "dump1090 unreachable — %d consecutive failures",
                self._consecutive_failures,
            )

    @staticmethod
    def _parse_aircraft(ac: dict) -> dict | None:
        """Normalise a single dump1090 aircraft dict.

        dump1090/readsb JSON fields of interest:
          hex        — ICAO 24-bit address (string)
          flight     — callsign (string, may have trailing spaces)
          lat, lon   — position (float)
          alt_baro   — barometric altitude in feet (int | "ground")
          gs         — ground speed in knots (float)
          track      — true track heading in degrees (float)
          baro_rate  — vertical rate in ft/min (int)
          seen       — seconds since last message (float)

        Returns None for aircraft without usable position data.
        """
        lat = ac.get("lat")
        lon = ac.get("lon")
        if lat is None or lon is None:
            return None

        alt_baro = ac.get("alt_baro")
        if alt_baro == "ground" or alt_baro is None:
            return None

        hex_code = ac.get("hex", "").strip().lower()
        if not hex_code:
            return None

        return {
            "icao24": hex_code,
            "callsign": (ac.get("flight") or "").strip(),
            "latitude": float(lat),
            "longitude": float(lon),
            "altitude_ft": float(alt_baro),
            "velocity_kts": float(ac.get("gs", 0) or 0),
            "heading": float(ac.get("track", 0) or 0),
            "vertical_rate_fpm": float(ac.get("baro_rate", 0) or 0),
            "on_ground": False,
            "last_contact": time.time() - float(ac.get("seen", 0) or 0),
        }
