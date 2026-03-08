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
from geo_filter import filter_aircraft
from callsign_decoder import decode_callsign
from icao_db import icao_db
from adsbx_client import ADSBXClient
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
adsbx = ADSBXClient(api_key=config.ADSBX_API_KEY)
mock_source = MockDataSource(config.HOME_LAT, config.HOME_LON)

# Track which icao24s we've already fetched routes for
_known_icaos: set[str] = set()


def poll_aircraft():
    """Background loop: fetch, filter, enrich, and broadcast aircraft data."""
    logger.info("Poller started")
    while True:
        try:
            # 1. Fetch raw aircraft
            if config.MOCK_MODE:
                raw = mock_source.fetch_aircraft()
            else:
                raw = opensky.fetch_aircraft()

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

                # Route enrichment: use mock data fields or ADSBX lookup
                route_info = None
                if config.MOCK_MODE and ac.get("origin"):
                    route_info = {"origin": ac["origin"], "destination": ac["destination"]}
                elif icao24 and icao24 not in _known_icaos:
                    try:
                        route_info = adsbx.get_route(icao24)
                    except Exception:
                        logger.debug("ADSBX route lookup failed for %s", icao24)
                    _known_icaos.add(icao24)

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
            socketio.emit("aircraft_update", state)

            if state.get("events"):
                logger.info("Events: %s", state["events"])

            # Debug: log first aircraft summary route data
            if state.get("aircraft_list"):
                a0 = state["aircraft_list"][0]
                logger.info("DEBUG first summary keys: %s", list(a0.keys()))
                logger.info("DEBUG route: %s -> %s", a0.get("route_origin"), a0.get("route_destination"))

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


@app.route("/api/debug_state")
def debug_state():
    """Return current state as JSON for debugging."""
    return jsonify(state_mgr.get_display_state())


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

    _save_env(data)
    logger.info("Config updated: %s", list(data.keys()))
    return jsonify({"ok": True})


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
    logger.info("  Altitude limit: %s ft | Radius limit: %s ft", config.ALTITUDE_LIMIT_FT, config.RADIUS_LIMIT_FT)
    logger.info("  Poll interval: %ss | Mock mode: %s", config.POLL_INTERVAL_SEC, config.MOCK_MODE)
    socketio.start_background_task(poll_aircraft)
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)
