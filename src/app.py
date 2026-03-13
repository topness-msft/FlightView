"""FlightView — Flask application entry point with Flask-SocketIO.

Serves the static frontend and provides real-time aircraft data
over WebSocket connections.
"""

import logging
import threading
import time

import os

from flask import Flask, send_from_directory, request, jsonify
from flask_socketio import SocketIO, emit

from config import config
from opensky_client import OpenSkyClient
from dump1090_client import Dump1090Client, Dump1090Error
from geo_filter import filter_aircraft, haversine_distance_ft
from callsign_decoder import decode_callsign
from icao_db import icao_db
from adsbx_client import ADSBXClient
from flightaware_client import FlightAwareClient
from state_manager import AircraftStateManager
from mock_data import MockDataSource

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder="static")
app.config["SECRET_KEY"] = "flightview-dev-key"

socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")

# --- Shared module instances ---
state_mgr = AircraftStateManager()
opensky = OpenSkyClient()
dump1090 = Dump1090Client(base_url=config.DUMP1090_URL)
adsbx = ADSBXClient(api_key=config.ADSBX_API_KEY)
flightaware = FlightAwareClient(api_key=config.FLIGHTAWARE_API_KEY or config.ADSBX_API_KEY)
mock_source = MockDataSource(config.HOME_LAT, config.HOME_LON)

# Track which icao24s we've already fetched routes for
_known_icaos: set[str] = set()
_known_fa_callsigns: set[str] = set()  # FlightAware lookups (near zone only)

# --- Health state (pushed to frontend with each update) ---
_health: dict = {
    "status": "ok",         # "ok" | "error"
    "message": "",          # Human-readable description
    "last_success": None,   # Epoch timestamp of last successful poll
    "data_source": config.DATA_SOURCE,
}


def _fetch_from_source() -> list[dict]:
    """Fetch aircraft from the configured data source.

    Returns the aircraft list on success.
    Raises Dump1090Error for RTL-SDR failures so the caller can
    update health state.  OpenSky failures return [] (non-critical).
    """
    src = config.DATA_SOURCE

    if src == "mock":
        return mock_source.fetch_aircraft()
    elif src == "rtlsdr":
        return dump1090.fetch_aircraft()  # raises Dump1090Error on failure
    else:  # "opensky" or unknown
        return opensky.fetch_aircraft()


def poll_aircraft():
    """Background loop: fetch, filter, enrich, and broadcast aircraft data."""
    logger.info("Poller started — data source: %s", config.DATA_SOURCE)
    while True:
        try:
            # 1. Fetch raw aircraft (with health tracking)
            try:
                raw = _fetch_from_source()
                _health["status"] = "ok"
                _health["message"] = ""
                _health["last_success"] = time.time()
                _health["data_source"] = config.DATA_SOURCE
            except Dump1090Error as exc:
                _health["status"] = "error"
                _health["message"] = str(exc)
                _health["data_source"] = config.DATA_SOURCE
                # Broadcast error state so frontend shows the alert
                error_state = state_mgr.get_display_state()
                error_state["health"] = dict(_health)
                socketio.emit("aircraft_update", error_state)
                time.sleep(config.POLL_INTERVAL_SEC)
                continue

            # 2. Geographic filter — use wider radar zone
            filtered = filter_aircraft(
                raw,
                config.HOME_LAT,
                config.HOME_LON,
                config.RADAR_RADIUS_FT,
                config.RADAR_ALTITUDE_FT,
            )

            # 3. Enrich each aircraft
            enriched = []
            for ac in filtered:
                icao24 = ac.get("icao24", "")
                callsign = ac.get("callsign", "")

                callsign_info = decode_callsign(callsign)
                icao_info = icao_db.lookup(icao24)

                # Route enrichment: use mock data fields only (live routes via FlightAware in step 5)
                route_info = None
                if config.MOCK_MODE and ac.get("origin"):
                    route_info = {"origin": ac["origin"], "destination": ac["destination"]}

                # In mock mode, supply typecode when ICAO DB lookup misses
                if not icao_info and config.MOCK_MODE and ac.get("typecode"):
                    icao_info = {"typecode": ac["typecode"]}

                enriched.append(
                    state_mgr.enrich_aircraft(ac, callsign_info, icao_info, route_info)
                )

            # 4. Update state manager and broadcast
            state = state_mgr.update(
                enriched,
                near_radius_ft=config.RADIUS_LIMIT_FT,
                near_altitude_ft=config.ALTITUDE_LIMIT_FT,
            )

            # 5. FlightAware route lookup — only for display aircraft (near zone)
            # get_route() has internal 10-min cache so repeated calls are free
            display = state.get("display")
            if display and not config.MOCK_MODE:
                callsign = display.get("callsign_raw", "").strip()
                if callsign:
                    fa_route = flightaware.get_route(callsign)
                    if fa_route and fa_route.get("origin"):
                        display["route_origin"] = fa_route["origin"]
                        display["route_destination"] = fa_route["destination"]
                        display["route_display"] = f"{fa_route['origin']} → {fa_route['destination']}"
                        # Use FA operator as airline fallback
                        if display.get("airline") == "Unknown" and fa_route.get("operator"):
                            display["airline"] = fa_route["operator"]

            # 6. Attach health state and broadcast
            state["health"] = dict(_health)
            socketio.emit("aircraft_update", state)

            if state.get("events"):
                logger.info("Events: %s", state["events"])

        except Exception:
            logger.exception("Error in poll_aircraft loop")

        time.sleep(config.POLL_INTERVAL_SEC)


@app.route("/")
def index():
    """Serve the main frontend page."""
    return send_from_directory(app.static_folder, "index.html")


@socketio.on("connect")
def handle_connect():
    """Handle new WebSocket client connections."""
    logger.info("Client connected")
    emit("aircraft_update", state_mgr.get_display_state())


@socketio.on("disconnect")
def handle_disconnect():
    """Handle WebSocket client disconnections."""
    logger.info("Client disconnected")


@socketio.on("request_update")
def handle_request_update():
    """Handle manual update requests from the client."""
    emit("aircraft_update", state_mgr.get_display_state())


# --- Config API ---

@app.route("/api/config", methods=["GET"])
def get_config():
    """Return current configuration values."""
    return jsonify({
        "home_lat": config.HOME_LAT,
        "home_lon": config.HOME_LON,
        "altitude_limit_ft": config.ALTITUDE_LIMIT_FT,
        "radius_limit_ft": config.RADIUS_LIMIT_FT,
        "radar_altitude_ft": config.RADAR_ALTITUDE_FT,
        "radar_radius_ft": config.RADAR_RADIUS_FT,
        "poll_interval_sec": config.POLL_INTERVAL_SEC,
        "adsbx_api_key": config.ADSBX_API_KEY,
        "mock_mode": config.MOCK_MODE,
        "data_source": config.DATA_SOURCE,
        "dump1090_url": config.DUMP1090_URL,
    })


@app.route("/api/config", methods=["POST"])
def set_config():
    """Update configuration values and persist to .env."""
    data = request.json or {}

    if "home_lat" in data:
        config.HOME_LAT = float(data["home_lat"])
    if "home_lon" in data:
        config.HOME_LON = float(data["home_lon"])
    if "altitude_limit_ft" in data:
        config.ALTITUDE_LIMIT_FT = int(data["altitude_limit_ft"])
    if "radius_limit_ft" in data:
        config.RADIUS_LIMIT_FT = int(data["radius_limit_ft"])
    if "radar_altitude_ft" in data:
        config.RADAR_ALTITUDE_FT = int(data["radar_altitude_ft"])
    if "radar_radius_ft" in data:
        config.RADAR_RADIUS_FT = int(data["radar_radius_ft"])
    if "poll_interval_sec" in data:
        config.POLL_INTERVAL_SEC = max(1, int(data["poll_interval_sec"]))
    if "adsbx_api_key" in data:
        config.ADSBX_API_KEY = str(data["adsbx_api_key"])
        adsbx.api_key = config.ADSBX_API_KEY
        adsbx.enabled = bool(config.ADSBX_API_KEY)
    if "mock_mode" in data:
        config.MOCK_MODE = str(data["mock_mode"]).lower() in ("true", "1", "yes")
    if "data_source" in data:
        config.DATA_SOURCE = str(data["data_source"]).lower()
        config.MOCK_MODE = config.DATA_SOURCE == "mock"
    if "dump1090_url" in data:
        config.DUMP1090_URL = str(data["dump1090_url"]).rstrip("/")
        dump1090.base_url = config.DUMP1090_URL
        dump1090._aircraft_url = None  # reset to re-detect endpoint
        dump1090._aircraft_urls = [
            f"{config.DUMP1090_URL}/?all",
            f"{config.DUMP1090_URL}/data/aircraft.json",
        ]

    _save_env(data)
    logger.info("Config updated: %s", list(data.keys()))
    return jsonify({"ok": True})


@app.route("/api/receiver", methods=["GET"])
def get_receiver_status():
    """Return raw unfiltered aircraft data from the receiver for diagnostics."""
    src = config.DATA_SOURCE
    result = {
        "data_source": src,
        "dump1090_url": config.DUMP1090_URL,
        "health": dict(_health),
        "aircraft": [],
        "total": 0,
    }

    try:
        if src == "rtlsdr":
            raw = dump1090.fetch_aircraft()
        elif src == "mock":
            raw = mock_source.fetch_aircraft()
        else:
            raw = opensky.fetch_aircraft()

        # Sort by altitude descending for readability
        raw.sort(key=lambda a: a.get("altitude_ft", 0), reverse=True)
        # Add distance from home
        for ac in raw:
            lat = ac.get("latitude")
            lon = ac.get("longitude")
            if lat is not None and lon is not None:
                ac["distance_ft"] = round(haversine_distance_ft(
                    config.HOME_LAT, config.HOME_LON, lat, lon
                ))
                ac["distance_nm"] = round(ac["distance_ft"] / 6076.12, 1)
        result["aircraft"] = raw
        result["total"] = len(raw)
        result["health"]["status"] = "ok"
    except Exception as exc:
        result["health"]["status"] = "error"
        result["health"]["message"] = str(exc)

    return jsonify(result)


def _save_env(updates: dict) -> None:
    """Persist config changes to the .env file."""
    key_map = {
        "home_lat": "HOME_LAT",
        "home_lon": "HOME_LON",
        "altitude_limit_ft": "ALTITUDE_LIMIT_FT",
        "radius_limit_ft": "RADIUS_LIMIT_FT",
        "radar_altitude_ft": "RADAR_ALTITUDE_FT",
        "radar_radius_ft": "RADAR_RADIUS_FT",
        "poll_interval_sec": "POLL_INTERVAL_SEC",
        "adsbx_api_key": "ADSBX_API_KEY",
        "mock_mode": "MOCK_MODE",
        "data_source": "DATA_SOURCE",
        "dump1090_url": "DUMP1090_URL",
    }
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")

    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            lines = f.readlines()

    for json_key, env_key in key_map.items():
        if json_key not in updates:
            continue
        value = str(updates[json_key])
        found = False
        for i, line in enumerate(lines):
            if line.strip().startswith(env_key + "="):
                lines[i] = f"{env_key}={value}\n"
                found = True
                break
        if not found:
            lines.append(f"{env_key}={value}\n")

    with open(env_path, "w") as f:
        f.writelines(lines)


if __name__ == "__main__":
    logger.info("FlightView starting — Home: (%s, %s)", config.HOME_LAT, config.HOME_LON)
    logger.info("  Data source: %s | Poll interval: %ss", config.DATA_SOURCE, config.POLL_INTERVAL_SEC)
    logger.info("  Altitude limit: %s ft | Radius limit: %s ft", config.ALTITUDE_LIMIT_FT, config.RADIUS_LIMIT_FT)
    socketio.start_background_task(poll_aircraft)
    socketio.run(app, host="0.0.0.0", port=5000, debug=False, allow_unsafe_werkzeug=True)
