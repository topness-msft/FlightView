"""FlightAware AeroAPI client for FlightView.

Enriches aircraft data with route information (origin/destination)
using FlightAware's AeroAPI. Only called for single-plane detail view
to stay within free-tier API limits.
"""

import logging
import time

import requests

logger = logging.getLogger(__name__)

AEROAPI_BASE = "https://aeroapi.flightaware.com/aeroapi"


class FlightAwareClient:
    """Client for FlightAware AeroAPI route enrichment."""

    CACHE_TTL_SEC = 600  # 10 minute cache per callsign

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.enabled = bool(api_key)
        self._cache: dict = {}

    def get_route(self, callsign: str) -> dict | None:
        """Fetch route info for a flight by callsign (ICAO format, e.g. SWA499).

        Returns a dict with origin, destination, origin_name, destination_name,
        or None on failure / disabled client.
        """
        if not self.enabled or not callsign:
            return None

        callsign = callsign.strip()

        # Check cache
        cached = self._cache.get(callsign)
        if cached and (time.time() - cached["timestamp"]) < self.CACHE_TTL_SEC:
            return cached["route_data"]

        try:
            url = f"{AEROAPI_BASE}/flights/{callsign}"
            resp = requests.get(
                url,
                headers={"x-apikey": self.api_key},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            flights = data.get("flights", [])
            if not flights:
                logger.debug("No flights returned from FlightAware for %s", callsign)
                return None

            # Use the first (most recent) flight
            fl = flights[0]
            orig = fl.get("origin") or {}
            dest = fl.get("destination") or {}

            route_data = {
                "origin": orig.get("code_iata") or orig.get("code", ""),
                "destination": dest.get("code_iata") or dest.get("code", ""),
                "origin_name": orig.get("name", ""),
                "destination_name": dest.get("name", ""),
                "operator": (fl.get("operator") or "").strip(),
                "aircraft_type": (fl.get("aircraft_type") or "").strip(),
            }

            self._cache[callsign] = {
                "route_data": route_data,
                "timestamp": time.time(),
            }

            logger.info("FlightAware route for %s: %s → %s",
                        callsign, route_data["origin"], route_data["destination"])
            return route_data

        except Exception:
            logger.warning("FlightAware request failed for %s", callsign, exc_info=True)
            return None
