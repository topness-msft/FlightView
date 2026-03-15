"""Aircraft tracking state manager for FlightView.

Maintains the current set of tracked aircraft, detects new arrivals
and departures, and manages the display queue.
"""

import logging
import time

from callsign_decoder import decode_callsign
from icao_db import get_aircraft_type

logger = logging.getLogger(__name__)


class AircraftStateManager:
    """Tracks active aircraft in the zone and manages priority display."""

    STALE_TIMEOUT_SEC = 30

    def __init__(self) -> None:
        self._active: dict[str, dict] = {}
        self._display_aircraft: dict | None = None
        self._last_seen: dict[str, float] = {}
        self._prev_distances: dict[str, float] = {}
        self._state: dict = {
            "display": None,
            "nearby_count": 0,
            "aircraft_list": [],
            "events": [],
        }

    def update(self, aircraft_list: list[dict], near_radius_ft: int = 1500, near_altitude_ft: int = 3000) -> dict:
        """Update tracked aircraft from a filtered aircraft list.

        Args:
            aircraft_list: Output of geo_filter.filter_aircraft (already has
                distance_ft, bearing, compass fields), sorted by distance.
            near_radius_ft: Radius threshold for the near zone (triggers detail view).
            near_altitude_ft: Altitude threshold for the near zone.

        Returns:
            State dict with display, nearby_count, aircraft_list, and events.
        """
        now = time.time()
        events: list[str] = []
        incoming_icaos: set[str] = set()

        # Process incoming aircraft
        for ac in aircraft_list:
            icao = ac.get("icao24")
            if not icao:
                continue
            incoming_icaos.add(icao)

            # Detect zone entry
            if icao not in self._active:
                callsign = ac.get("callsign", ac.get("callsign_raw", icao))
                events.append(f"entered: {callsign}")
                logger.info("Aircraft entered zone: %s (%s)", icao, callsign)

            # Store previous distance for direction calculation
            if icao in self._active and "distance_ft" in self._active[icao]:
                self._prev_distances[icao] = self._active[icao]["distance_ft"]

            self._active[icao] = ac
            self._last_seen[icao] = now

        # Remove stale aircraft
        stale_icaos = [
            icao for icao, ts in self._last_seen.items()
            if (now - ts) >= self.STALE_TIMEOUT_SEC and icao not in incoming_icaos
        ]
        for icao in stale_icaos:
            ac = self._active.pop(icao, {})
            self._last_seen.pop(icao, None)
            self._prev_distances.pop(icao, None)
            callsign = ac.get("callsign", ac.get("callsign_raw", icao))
            events.append(f"left: {callsign}")
            logger.info("Aircraft left zone: %s (%s)", icao, callsign)

        # Build sorted aircraft list (by distance)
        sorted_active = sorted(
            self._active.values(),
            key=lambda a: a.get("distance_ft", float("inf")),
        )

        # Determine display aircraft: closest in the NEAR zone only
        near_aircraft = [
            ac for ac in sorted_active
            if ac.get("distance_ft", float("inf")) <= near_radius_ft
            and ac.get("altitude_ft", float("inf")) <= near_altitude_ft
        ]

        display_icao = self._display_aircraft.get("icao24") if self._display_aircraft else None
        if display_icao and any(ac.get("icao24") == display_icao for ac in near_aircraft):
            self._display_aircraft = self._active[display_icao]
        elif near_aircraft:
            self._display_aircraft = near_aircraft[0]
        else:
            self._display_aircraft = None

        # Build summary list for all active aircraft (rich data for radar + board views)
        aircraft_summaries = [
            {
                "icao24": ac.get("icao24"),
                "callsign": ac.get("callsign_raw", ""),
                "airline": ac.get("airline", ""),
                "flight_display": ac.get("flight_display", ""),
                "aircraft_type": ac.get("aircraft_type", ""),
                "distance_ft": ac.get("distance_ft"),
                "altitude_ft": ac.get("altitude_ft"),
                "velocity_kts": ac.get("velocity_kts"),
                "heading": ac.get("heading"),
                "bearing": ac.get("bearing", 0),
                "compass": ac.get("compass", ""),
                "direction": ac.get("direction", ""),
                "vertical_rate_fpm": ac.get("vertical_rate_fpm"),
                "callsign_raw": ac.get("callsign_raw", ""),
                "route_origin": ac.get("route_origin", ""),
                "route_destination": ac.get("route_destination", ""),
            }
            for ac in sorted_active
        ]

        self._state = {
            "display": self._display_aircraft,
            "nearby_count": len(near_aircraft),
            "aircraft_count": len(self._active),
            "aircraft_list": aircraft_summaries,
            "events": events,
        }
        return self._state

    def enrich_aircraft(
        self,
        aircraft: dict,
        callsign_info: dict,
        icao_info: dict | None,
        route_info: dict | None,
    ) -> dict:
        """Merge all enrichment data into a single display-ready dict.

        Args:
            aircraft: Base aircraft dict (from geo_filter with distance_ft, etc.)
            callsign_info: Output of callsign_decoder.decode_callsign.
            icao_info: Output of icao_db.lookup (or None).
            route_info: Output of ADSBXClient.get_route (or None).

        Returns:
            Enriched dict ready for display.
        """
        icao24 = aircraft.get("icao24", "")

        # Resolve aircraft type from icao_info typecode
        typecode = (icao_info or {}).get("typecode", "")
        aircraft_type = get_aircraft_type(typecode) if typecode else ""

        # Route fields
        route_origin = (route_info or {}).get("origin", "")
        route_destination = (route_info or {}).get("destination", "")
        route_display = ""
        if route_origin and route_destination:
            route_display = f"{route_origin} → {route_destination}"

        # Determine direction
        distance_ft = aircraft.get("distance_ft", 0)
        vertical_rate = aircraft.get("vertical_rate_fpm", 0)
        prev_distance = self._prev_distances.get(icao24)

        if distance_ft < 500:
            direction = "overhead"
        elif vertical_rate < 0 and prev_distance is not None and distance_ft < prev_distance:
            direction = "approaching"
        else:
            direction = "departing"

        return {
            "icao24": icao24,
            "callsign_raw": aircraft.get("callsign", ""),
            "airline": callsign_info.get("airline", "Unknown"),
            "flight_number": callsign_info.get("flight_number", ""),
            "flight_display": callsign_info.get("display", ""),
            "aircraft_type": aircraft_type,
            "registration": (icao_info or {}).get("registration", ""),
            "route_origin": route_origin,
            "route_destination": route_destination,
            "route_display": route_display,
            "altitude_ft": aircraft.get("altitude_ft", 0),
            "velocity_kts": aircraft.get("velocity_kts", 0),
            "heading": aircraft.get("heading", 0),
            "vertical_rate_fpm": vertical_rate,
            "distance_ft": distance_ft,
            "bearing": aircraft.get("bearing", 0),
            "compass": aircraft.get("compass", ""),
            "direction": direction,
        }

    def get_display_state(self) -> dict:
        """Return the current state without updating (for new WebSocket connections)."""
        return self._state
