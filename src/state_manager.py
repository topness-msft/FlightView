"""Aircraft tracking state manager for FlightView.

Maintains the current set of tracked aircraft, detects new arrivals
and departures, and manages the display queue.
"""

import logging
import threading
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
        self._near_radius_ft: int = 1500
        self._near_altitude_ft: int = 3000
        self._state: dict = {
            "display": None,
            "nearby_count": 0,
            "aircraft_list": [],
            "events": [],
        }
        # Guards mutations of self._active. The poll thread is the
        # primary writer (via update), and worker threads from the route
        # prefetch pool write route fields via enrich_active. The lock
        # serialises those two so the active dict can't be mutated
        # mid-iteration.
        self._lock = threading.RLock()

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
        with self._lock:
            return self._update_locked(aircraft_list, near_radius_ft, near_altitude_ft)

    def _update_locked(self, aircraft_list: list[dict], near_radius_ft: int, near_altitude_ft: int) -> dict:
        now = time.time()
        events: list[str] = []
        incoming_icaos: set[str] = set()
        self._near_radius_ft = near_radius_ft
        self._near_altitude_ft = near_altitude_ft

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

            # Carry forward fields that the live polling pipeline never
            # repopulates on its own.
            if icao in self._active:
                prev = self._active[icao]
                prev_callsign = (prev.get("callsign_raw") or prev.get("callsign") or "").strip().upper()
                curr_callsign = (ac.get("callsign_raw") or ac.get("callsign") or "").strip().upper()
                # Only invalidate route info when BOTH sides are non-empty
                # AND they differ — a transient blank callsign read from
                # the receiver shouldn't drop a valid route.
                callsign_changed = (
                    bool(prev_callsign) and bool(curr_callsign)
                    and prev_callsign != curr_callsign
                )
                route_fields = (
                    "route_origin", "route_destination", "route_display",
                    "origin_city", "destination_city", "route_checked_at",
                )
                if not callsign_changed:
                    for field in route_fields:
                        if prev.get(field) and not ac.get(field):
                            ac[field] = prev[field]
                # Airframe-level fields (tied to icao24, not callsign) always carry forward
                if prev.get("typecode") and not ac.get("typecode"):
                    ac["typecode"] = prev["typecode"]
                # Preserve API-sourced airline/type (prefixed to avoid overwriting real data)
                if prev.get("airline") not in ("", "Unknown") and ac.get("airline") in ("", "Unknown"):
                    ac["airline"] = prev["airline"]
                if prev.get("flight_display") and not ac.get("flight_display"):
                    ac["flight_display"] = prev["flight_display"]
                if prev.get("aircraft_type") and not ac.get("aircraft_type"):
                    ac["aircraft_type"] = prev["aircraft_type"]

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

        self._rebuild_state(events)
        return self._state

    def _rebuild_state(self, events: list[str] | None = None) -> None:
        """Rebuild the broadcast state dict from current _active aircraft."""
        sorted_active = sorted(
            self._active.values(),
            key=lambda a: a.get("distance_ft", float("inf")),
        )

        near_aircraft = [
            ac for ac in sorted_active
            if ac.get("distance_ft", float("inf")) <= self._near_radius_ft
            and ac.get("altitude_ft", float("inf")) <= self._near_altitude_ft
        ]

        # Build summary list for all active aircraft (rich data for radar + board views)
        aircraft_summaries = [
            {
                "icao24": ac.get("icao24"),
                "callsign": ac.get("callsign_raw", ""),
                "airline": ac.get("airline", ""),
                "flight_display": ac.get("flight_display", ""),
                "aircraft_type": ac.get("aircraft_type", ""),
                "typecode": ac.get("typecode", ""),
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
                "route_display": ac.get("route_display", ""),
                "origin_city": ac.get("origin_city", ""),
                "destination_city": ac.get("destination_city", ""),
                "route_checked_at": ac.get("route_checked_at"),
            }
            for ac in sorted_active
        ]

        self._state = {
            "display": self._display_aircraft,
            "nearby_count": len(near_aircraft),
            "aircraft_count": len(self._active),
            "aircraft_list": aircraft_summaries,
            "events": events or [],
        }

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
        aircraft_type = get_aircraft_type(typecode) if typecode else ""        # Route fields
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
            "typecode": typecode,
            "registration": (icao_info or {}).get("registration", ""),
            "route_origin": route_origin,
            "route_destination": route_destination,
            "route_display": route_display,
            "origin_city": "",
            "destination_city": "",
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

    def get_active(self, icao24: str) -> dict | None:
        """Return the active aircraft dict for icao24, or None.

        Used by the prefetch pipeline to validate that the callsign hasn't
        changed (and the aircraft hasn't left the zone) before applying
        a route enrichment that may have been computed on a worker thread.
        """
        return self._active.get(icao24)

    def enrich_active(
        self,
        icao24: str,
        enrichment: dict,
        expected_callsign: str | None = None,
    ) -> bool:
        """Apply API enrichment data to an active aircraft (persists across polls).

        Thread-safe — may be called from worker threads in the route
        prefetch pool. Acquires the manager lock so a concurrent poll-thread
        update() can't see a half-written aircraft dict.

        Args:
            icao24: Aircraft ICAO24 hex address.
            enrichment: Dict of fields to merge (route, city, operator, type).
            expected_callsign: If provided, the enrichment is applied only
                when the aircraft's current callsign (normalised) matches.
                Used by the async route prefetch so a route fetched for
                callsign X is never applied to an airframe that has since
                switched to flight Y.

        Returns:
            True when the active state changed.
        """
        with self._lock:
            ac = self._active.get(icao24)
            if not ac:
                return False
            if expected_callsign is not None:
                curr = (ac.get("callsign_raw") or ac.get("callsign") or "").strip().upper()
                if curr and curr != expected_callsign.strip().upper():
                    return False
            changed = False
            if enrichment.get("callsign_raw") and not (ac.get("callsign_raw") or ac.get("callsign")):
                callsign = enrichment["callsign_raw"]
                decoded = decode_callsign(callsign)
                for field, value in (
                    ("callsign", callsign),
                    ("callsign_raw", callsign),
                    ("airline", decoded["airline"]),
                    ("flight_display", decoded["display"]),
                ):
                    changed = changed or ac.get(field) != value
                    ac[field] = value
            # Always set route/city fields
            for field in ("route_origin", "route_destination", "route_display",
                           "origin_city", "destination_city", "route_checked_at"):
                if enrichment.get(field) is not None and enrichment.get(field) != "":
                    changed = changed or ac.get(field) != enrichment[field]
                    ac[field] = enrichment[field]
            # Backfill airline from FA operator if local decode was Unknown
            if ac.get("airline") in ("", "Unknown") and enrichment.get("fa_operator"):
                changed = changed or ac.get("airline") != enrichment["fa_operator"]
                ac["airline"] = enrichment["fa_operator"]
            # Backfill aircraft type from FA if local ICAO DB had nothing
            if not ac.get("aircraft_type") and enrichment.get("fa_aircraft_type"):
                changed = changed or ac.get("aircraft_type") != enrichment["fa_aircraft_type"]
                ac["aircraft_type"] = enrichment["fa_aircraft_type"]
            # Rebuild the state so get_display_state() reflects the enrichment
            if changed:
                self._rebuild_state()
            return changed
