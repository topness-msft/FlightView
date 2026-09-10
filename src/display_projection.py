"""Bounded, display-only version-1 contract for LAN companion devices."""

import json
import math


MAX_AIRCRAFT = 32
MAX_BODY_BYTES = 64 * 1024
TEXT_LIMITS = {
    "icao24": 6,
    "callsign": 16,
    "flight_display": 24,
    "airline": 96,
    "typecode": 8,
    "aircraft_type": 96,
    "registration": 24,
    "route_origin": 8,
    "route_destination": 8,
    "origin_city": 96,
    "destination_city": 96,
    "compass": 4,
    "direction": 16,
}
NUMERIC_FIELDS = (
    "altitude_ft", "velocity_kts", "distance_ft", "vertical_rate_fpm",
    "bearing", "heading",
)


def _text(value: object, byte_limit: int) -> str:
    if not isinstance(value, str):
        return ""
    printable = "".join(character for character in value if character.isprintable())
    # Drop only the incomplete code point at the byte boundary.
    return printable.encode("utf-8")[:byte_limit].decode("utf-8", errors="ignore")


def _number(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not -1e12 <= value <= 1e12 or not math.isfinite(value):
        return None
    return value


def _positive_setting(value: object, name: str) -> int | float:
    number = _number(value)
    if number is None or number <= 0:
        raise ValueError(f"Invalid display setting: {name}")
    return number


def _aircraft(aircraft: dict) -> dict:
    fields = {
        key: _text(aircraft.get(key), limit)
        for key, limit in TEXT_LIMITS.items()
    }
    fields["callsign"] = _text(
        aircraft.get("callsign_raw") or aircraft.get("callsign"), TEXT_LIMITS["callsign"],
    )
    fields.update({key: _number(aircraft.get(key)) for key in NUMERIC_FIELDS})
    return fields


def project_display(snapshot: dict, settings: dict, health: dict) -> dict:
    """Project a detached state without changing it or consulting external data."""
    poll_interval = _positive_setting(settings["poll_interval_sec"], "poll_interval_sec")
    radar_radius = _positive_setting(settings["radar_radius_ft"], "radar_radius_ft")
    near_radius = _positive_setting(snapshot["near_radius_ft"], "near_radius_ft")
    stale_after_ms = max(10000, int(poll_interval * 3000))
    age_ms = snapshot["state_age_ms"]
    initial = snapshot["source_state_observed_at"] is None
    source = health.get("data_source", "")
    if source not in ("rtlsdr", "opensky", "mock"):
        source = "unknown"
    source_ok = health.get("status") == "ok"
    aircraft = snapshot["aircraft_list"]
    returned = [_aircraft(item) for item in aircraft[:MAX_AIRCRAFT]]
    return {
        "schema_version": 1,
        "display": _aircraft(snapshot["display"]) if snapshot["display"] is not None else None,
        "aircraft": returned,
        "counts": {
            "total_aircraft": len(aircraft),
            "nearby_aircraft": snapshot["nearby_count"],
            "returned_aircraft": len(returned),
            "truncated": len(aircraft) > len(returned),
        },
        "zones": {"near_radius_ft": near_radius, "radar_radius_ft": radar_radius},
        "freshness": {
            "source_state_observed_at": snapshot["source_state_observed_at"],
            "state_age_ms": age_ms,
            "stale_after_ms": stale_after_ms,
            "is_initial": initial,
            "is_stale": initial or age_ms is None or age_ms >= stale_after_ms,
        },
        "health": {
            "status": "ok" if source_ok else "error",
            "data_source": source,
            "message": "" if source_ok else "Aircraft data source unavailable",
        },
        "server_version": _text(settings.get("server_version"), 40),
    }


def serialize_display(payload: dict) -> bytes:
    """Enforce the wire limit after JSON escaping, before sending any bytes."""
    body = json.dumps(
        payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"),
    ).encode("utf-8")
    if len(body) > MAX_BODY_BYTES:
        raise ValueError("Display response exceeds byte limit")
    return body
