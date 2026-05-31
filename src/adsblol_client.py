"""adsb.lol route API client for FlightView.

Enriches aircraft data with route information (origin/destination)
using the free, key-less adsb.lol community route database.

Endpoint: https://vrs-standing-data.adsb.lol/routes/{CS[:2]}/{CALLSIGN}.json
where CS[:2] is the first two characters of the callsign.

This hits the static route data host directly. The previous endpoint
(https://api.adsb.lol/api/0/route/{callsign}) is now deprecated: it only
302-redirects to this static file, and that redirect hop adds ~7-26s of
latency per lookup. Fetching the static JSON directly returns in ~1-2s.

Returns airport pairs with IATA, ICAO, location (city), and full name.
"""

import logging
import threading
import time

import requests

logger = logging.getLogger(__name__)

ADSBLOL_BASE = "https://vrs-standing-data.adsb.lol/routes"


class AdsbLolClient:
    """Client for adsb.lol route enrichment."""

    CACHE_TTL_SEC = 600       # 10 min cache for successful lookups
    NEG_CACHE_TTL_SEC = 600   # 10 min cache for definitive no-route responses
    REQUEST_TIMEOUT_SEC = 6   # static host responds in ~1-2s; 6s leaves margin

    def __init__(self) -> None:
        self.enabled = True
        self._cache: dict = {}
        self._neg_cache: dict = {}  # callsign -> timestamp of last definitive miss
        self._lock = threading.Lock()

    def get_route(self, callsign: str) -> dict | None:
        """Fetch route info for a flight by callsign (e.g. 'GJS4527').

        Returns a dict with origin, destination, origin_name, destination_name,
        or None on failure / unknown callsign.

        The shape matches the legacy FlightAwareClient response so callers
        don't need to change.
        """
        if not self.enabled or not callsign:
            return None

        callsign = callsign.strip().upper()

        with self._lock:
            cached = self._cache.get(callsign)
            if cached and (time.time() - cached["timestamp"]) < self.CACHE_TTL_SEC:
                return cached["route_data"]

            neg = self._neg_cache.get(callsign)
            if neg and (time.time() - neg) < self.NEG_CACHE_TTL_SEC:
                return None

            if len(self._cache) > 200:
                now = time.time()
                self._cache = {
                    k: v for k, v in self._cache.items()
                    if (now - v["timestamp"]) < self.CACHE_TTL_SEC
                }
            if len(self._neg_cache) > 200:
                now = time.time()
                self._neg_cache = {
                    k: v for k, v in self._neg_cache.items()
                    if (now - v) < self.NEG_CACHE_TTL_SEC
                }

        try:
            url = f"{ADSBLOL_BASE}/{callsign[:2]}/{callsign}.json"
            resp = requests.get(url, timeout=self.REQUEST_TIMEOUT_SEC)
            if resp.status_code == 404:
                logger.debug("adsb.lol has no route for %s", callsign)
                with self._lock:
                    self._neg_cache[callsign] = time.time()
                return None
            resp.raise_for_status()
            data = resp.json()

            airports = data.get("_airports") or []
            if len(airports) < 2:
                logger.debug("adsb.lol returned no airport pair for %s", callsign)
                with self._lock:
                    self._neg_cache[callsign] = time.time()
                return None

            origin_ap = airports[0] or {}
            dest_ap = airports[-1] or {}

            # Normalise the airport list so callers (reconciler, tests) don't
            # need to know the raw upstream shape.  Each entry includes lat/lon
            # so the reconciler can match the live takeoff coords back to a
            # canonical airport.
            normalised_airports = []
            for ap in airports:
                if not isinstance(ap, dict):
                    continue
                normalised_airports.append({
                    "iata": (ap.get("iata") or "").strip(),
                    "icao": (ap.get("icao") or "").strip(),
                    "name": (ap.get("name") or "").strip(),
                    "location": (ap.get("location") or "").strip(),
                    "lat": ap.get("lat"),
                    "lon": ap.get("lon"),
                })

            route_data = {
                "origin": (origin_ap.get("iata") or origin_ap.get("icao") or "").strip(),
                "destination": (dest_ap.get("iata") or dest_ap.get("icao") or "").strip(),
                "origin_name": (origin_ap.get("location") or origin_ap.get("name") or "").strip(),
                "destination_name": (dest_ap.get("location") or dest_ap.get("name") or "").strip(),
                "airports": normalised_airports,
                "operator": "",
                "aircraft_type": "",
            }

            with self._lock:
                self._cache[callsign] = {
                    "route_data": route_data,
                    "timestamp": time.time(),
                }
                self._neg_cache.pop(callsign, None)

            logger.info("adsb.lol route for %s: %s → %s",
                        callsign, route_data["origin"], route_data["destination"])
            return route_data

        except Exception:
            # Transient failure — do NOT negative-cache; will retry next call.
            logger.warning("adsb.lol request failed for %s", callsign, exc_info=True)
            return None
