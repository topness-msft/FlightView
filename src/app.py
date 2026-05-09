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
from adsblol_client import AdsbLolClient
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
route_client = AdsbLolClient()
mock_source = MockDataSource(config.HOME_LAT, config.HOME_LON)

# Track which icao24s we've already fetched routes for
_known_icaos: set[str] = set()
# Track which callsigns have an in-flight or recent route fetch (prevents
# re-firing every poll for callsigns that returned no route).
_routed_callsigns: set[str] = set()


def _prefetch_route(icao24: str, callsign: str) -> None:
    """Background task: look up route, merge into state, broadcast."""
    if config.MOCK_MODE:
        return
    try:
        route = route_client.get_route(callsign)
        if not route or not route.get("origin"):
            return
        enrichment = {
            "route_origin": route["origin"],
            "route_destination": route["destination"],
            "route_display": f"{route['origin']} → {route['destination']}",
            "origin_city": route.get("origin_name", ""),
            "destination_city": route.get("destination_name", ""),
        }
        state_mgr.enrich_active(icao24, enrichment)
        state = state_mgr.get_display_state()
        state["health"] = dict(_health)
        socketio.emit("aircraft_update", state)
    except Exception:
        logger.exception("prefetch_route failed for %s", callsign)

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

            # 5. Attach health state and broadcast
            state["health"] = dict(_health)
            socketio.emit("aircraft_update", state)

            # 6. Pre-warm route enrichment for any new callsigns (background)
            #    adsb.lol is free and fast; doing this proactively eliminates the
            #    1–2s lag when the user taps a flight or it auto-promotes to
            #    the detail view.
            for ac in state.get("aircraft_list", []):
                callsign = (ac.get("callsign_raw") or ac.get("callsign") or "").strip()
                icao24 = (ac.get("icao24") or "").strip()
                if not callsign or not icao24:
                    continue
                if ac.get("route_origin"):
                    continue  # already enriched
                if callsign in _routed_callsigns:
                    continue  # in-flight or cached miss this cycle
                if len(_routed_callsigns) > 500:
                    _routed_callsigns.clear()
                _routed_callsigns.add(callsign)
                socketio.start_background_task(_prefetch_route, icao24, callsign)

            if state.get("events"):
                logger.info("Events: %s", state["events"])

        except Exception:
            logger.exception("Error in poll_aircraft loop")

        time.sleep(config.POLL_INTERVAL_SEC)


@app.route("/")
def index():
    """Serve the main frontend page."""
    return send_from_directory(app.static_folder, "index.html")


@app.after_request
def add_no_cache_headers(response):
    """Prevent browser caching of static assets during development."""
    if response.content_type and ("javascript" in response.content_type or "text/css" in response.content_type or "text/html" in response.content_type):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


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


@socketio.on("pin_flight")
def handle_pin_flight(data):
    """Fetch route enrichment for a pinned aircraft and push update."""
    callsign = (data.get("callsign") or "").strip()
    icao24 = (data.get("icao24") or "").strip()
    if not callsign or config.MOCK_MODE:
        return
    route = route_client.get_route(callsign)
    if not route or not route.get("origin"):
        return
    enrichment = {
        "route_origin": route["origin"],
        "route_destination": route["destination"],
        "route_display": f"{route['origin']} → {route['destination']}",
        "origin_city": route.get("origin_name", ""),
        "destination_city": route.get("destination_name", ""),
    }
    if route.get("operator"):
        enrichment["fa_operator"] = route["operator"]
    if route.get("aircraft_type"):
        enrichment["fa_aircraft_type"] = route["aircraft_type"]

    # Persist enrichment into state manager's active aircraft (survives poll cycles)
    state_mgr.enrich_active(icao24, enrichment)

    # Emit updated state
    state = state_mgr.get_display_state()
    state["health"] = dict(_health)
    emit("aircraft_update", state)


# --- Config API ---

def _mask_key(key: str) -> str:
    """Mask an API key, showing only the last 4 characters."""
    if not key or len(key) <= 4:
        return key
    return "••••" + key[-4:]


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
        "adsbx_api_key": _mask_key(config.ADSBX_API_KEY),
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


@app.route("/api/route", methods=["GET"])
def get_route():
    """Diagnostic: return raw route lookup for a callsign (no caching effect)."""
    callsign = request.args.get("callsign", "").strip()
    if not callsign:
        return jsonify({"error": "callsign required"}), 400
    try:
        route = route_client.get_route(callsign)
        return jsonify({"callsign": callsign, "route": route, "client_enabled": route_client.enabled})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/update", methods=["POST"])
def do_update():
    """Git pull (or force-reset to origin/main) and restart the FlightView service.

    Pass {"force": true} or ?force=true to discard local changes and
    hard-reset to origin/main before restart. Use this when the Pi has
    drifted from main (uncommitted edits, manual hotfixes, etc.).
    """
    import subprocess
    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    body = request.get_json(silent=True) or {}
    force = bool(body.get("force")) or request.args.get("force", "").lower() in ("1", "true", "yes")
    try:
        if force:
            fetch = subprocess.run(
                ["git", "fetch", "origin", "main"],
                cwd=repo_dir, capture_output=True, text=True, timeout=30,
            )
            if fetch.returncode != 0:
                return jsonify({"ok": False, "error": fetch.stderr.strip()}), 500
            reset = subprocess.run(
                ["git", "reset", "--hard", "origin/main"],
                cwd=repo_dir, capture_output=True, text=True, timeout=30,
            )
            if reset.returncode != 0:
                return jsonify({"ok": False, "error": reset.stderr.strip()}), 500
            output = reset.stdout.strip()
        else:
            pull = subprocess.run(
                ["git", "pull", "origin", "main"],
                cwd=repo_dir, capture_output=True, text=True, timeout=30,
            )
            if pull.returncode != 0:
                return jsonify({"ok": False, "error": pull.stderr.strip()}), 500
            output = pull.stdout.strip()

        subprocess.Popen(
            ["sudo", "systemctl", "restart", "flightview"],
            cwd=repo_dir,
        )
        return jsonify({"ok": True, "output": output, "forced": force})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


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
    logger.info("  Listening on port %s", config.PORT)
    socketio.start_background_task(poll_aircraft)
    socketio.run(app, host="0.0.0.0", port=config.PORT, debug=False, allow_unsafe_werkzeug=True)
