"""ADS-B Exchange API client for FlightView.

Enriches aircraft data with route information (origin/destination)
using the ADS-B Exchange API via RapidAPI.
"""

import logging
import time

import requests

logger = logging.getLogger(__name__)


class ADSBXClient:
    """Client for ADS-B Exchange route enrichment."""

    CACHE_TTL_SEC = 300

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.enabled = bool(api_key)
        self._cache: dict = {}

    def get_route(self, icao24: str) -> dict | None:
        """Fetch route info for an aircraft by ICAO24 hex address.

        Returns a dict with flight, origin, destination, route, and operator
        keys, or None on failure / disabled client.
        """
        if not self.enabled:
            return None

        icao24 = icao24.lower().strip()

        # Check cache
        cached = self._cache.get(icao24)
        if cached and (time.time() - cached["timestamp"]) < self.CACHE_TTL_SEC:
            return cached["route_data"]

        try:
            url = f"https://adsbexchange-com1.p.rapidapi.com/v2/icao/{icao24}/"
            headers = {
                "X-RapidAPI-Key": self.api_key,
                "X-RapidAPI-Host": "adsbexchange-com1.p.rapidapi.com",
            }
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            ac_list = data.get("ac")
            if not ac_list:
                logger.warning("No aircraft data in ADSBX response for %s", icao24)
                return None

            ac = ac_list[0]
            route_data = self._parse_aircraft(ac)

            self._cache[icao24] = {
                "route_data": route_data,
                "timestamp": time.time(),
            }
            return route_data

        except Exception:
            logger.warning("ADSBX request failed for %s", icao24, exc_info=True)
            return None

    def get_route_display(self, icao24: str) -> str:
        """Return a human-readable route string like 'DAL → ORD'."""
        route = self.get_route(icao24)
        if route and route.get("origin") and route.get("destination"):
            return f"{route['origin']} → {route['destination']}"
        return "Unknown route"

    @staticmethod
    def _parse_aircraft(ac: dict) -> dict:
        """Extract route fields from a single ADSBX aircraft entry."""
        flight = (ac.get("flight") or "").strip()
        operator = (ac.get("ownOp") or ac.get("op") or "").strip()

        origin = ""
        destination = ""
        route_str = ""

        # Try the 'r' field first (combined route string, e.g. "KJFK-KLAX")
        r_field = (ac.get("r") or "").strip()
        if "-" in r_field:
            parts = r_field.split("-")
            origin = parts[0].strip()
            destination = parts[-1].strip()
            route_str = r_field

        # Fall back to explicit from/to fields
        if not origin:
            origin = (ac.get("from") or "").strip()
        if not destination:
            destination = (ac.get("to") or "").strip()

        if origin and destination and not route_str:
            route_str = f"{origin}-{destination}"

        return {
            "flight": flight,
            "route": route_str,
            "origin": origin,
            "destination": destination,
            "operator": operator,
        }
