"""FlightView — Flask application entry point with Flask-SocketIO.

Serves the static frontend and provides real-time aircraft data
over WebSocket connections.
"""

import logging
import threading
import time

import os

from concurrent.futures import ThreadPoolExecutor

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
from route_reconciler import find_takeoff_point, reconcile_route

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

# Server version: short git SHA at startup. Sent with every state broadcast so
# the frontend can detect a deploy and auto-reload to pick up new HTML/JS/CSS.
def _read_server_version() -> str:
    import subprocess
    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_dir, capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


SERVER_VERSION = _read_server_version()

# --- Route enrichment prefetch (async fire-and-forget) ---
# When a new callsign appears in the radar list, we schedule an adsb.lol
# lookup on a small thread pool. The worker writes the route fields
# directly into state_mgr._active and broadcasts the refreshed state
# immediately, so origin/destination appears as soon as the lookup completes.
ROUTE_PREFETCH_MAX_WORKERS = 5
# After a successful or suppressed reconcile, wait this long before retrying.
# Suppressed entries (stale adsb data) shouldn't be polled every cycle, but
# also shouldn't be permanently blocked — schedules update over time.
ROUTE_RECHECK_INTERVAL_SEC = 300
_route_executor = ThreadPoolExecutor(
    max_workers=ROUTE_PREFETCH_MAX_WORKERS,
    thread_name_prefix="route-fetch",
)
_route_inflight_lock = threading.Lock()
_route_inflight: set[str] = set()  # route lookup keys currently being fetched
# icao24 -> epoch of first radar contact while still lacking a route. Used to
# measure end-to-end lead time (first contact → origin/destination available)
# so we can verify routes warm up before an aircraft reaches the detail zone.
_route_first_seen: dict[str, float] = {}


def _normalize_callsign(cs: str) -> str:
    return (cs or "").strip().upper()


def _mark_route_inflight(route_key: str) -> bool:
    """Return True when this caller owns the route lookup key."""
    with _route_inflight_lock:
        if route_key in _route_inflight:
            return False
        _route_inflight.add(route_key)
        return True


def _clear_route_inflight(route_key: str) -> None:
    with _route_inflight_lock:
        _route_inflight.discard(route_key)


def _route_key(icao24: str, callsign: str) -> str:
    return callsign or f"icao:{icao24.strip().lower()}"


def _resolve_route_callsign(icao24: str, callsign: str) -> str | None:
    callsign = _normalize_callsign(callsign)
    if callsign:
        return callsign
    resolved = _normalize_callsign(opensky.get_callsign(icao24))
    if resolved:
        logger.info("OpenSky callsign backfill %s → %s", icao24, resolved)
        return resolved
    return None


def _build_route_enrichment(icao24: str, callsign: str) -> dict:
    """Fetch and reconcile route data for an active aircraft.

    The adsb.lol route lookup and the OpenSky track lookup are independent
    network calls, each with a ~6s timeout.  Running them sequentially meant
    origin/destination could take ~10s+ to appear.  We run them concurrently
    so total latency is bounded by the slower of the two, not their sum.
    """
    t0 = time.time()
    track_holder: dict = {}

    def _fetch_track() -> None:
        tt0 = time.time()
        try:
            track_holder["path"] = opensky.get_track(icao24)
        except Exception:
            logger.warning("track fetch failed for %s", icao24, exc_info=True)
            track_holder["path"] = None
        track_holder["ms"] = int((time.time() - tt0) * 1000)

    track_thread = threading.Thread(
        target=_fetch_track, name="route-track", daemon=True
    )
    track_thread.start()

    ta0 = time.time()
    adsb_route = route_client.get_route(callsign)
    adsb_ms = int((time.time() - ta0) * 1000)

    track_thread.join()
    track_path = track_holder.get("path")
    track_ms = track_holder.get("ms", 0)
    takeoff = find_takeoff_point(track_path)

    result = reconcile_route(adsb_route, takeoff)
    total_ms = int((time.time() - t0) * 1000)
    logger.info(
        "route timing %s/%s: total=%dms adsb=%dms(%s) track=%dms(%s) → %s→%s conf=%s (%s)",
        icao24, callsign, total_ms,
        adsb_ms, "hit" if adsb_route else "miss",
        track_ms, "hit" if track_path else "none",
        result.get("origin") or "-",
        result.get("destination") or "-",
        result.get("confidence"),
        result.get("reason"),
    )

    enrichment: dict = {
        "route_checked_at": time.time(),
        "callsign_raw": callsign,
    }
    if result.get("origin"):
        enrichment["route_origin"] = result["origin"]
        enrichment["route_destination"] = result.get("destination", "")
        if result.get("destination"):
            enrichment["route_display"] = f"{result['origin']} → {result['destination']}"
        else:
            # Known origin, unknown destination (e.g. matched terminal
            # airport of a multi-leg canonical route).  Show the partial.
            enrichment["route_display"] = f"{result['origin']} → ?"
        enrichment["origin_city"] = result.get("origin_name", "")
        enrichment["destination_city"] = result.get("destination_name", "")

    if adsb_route:
        if adsb_route.get("operator"):
            enrichment["fa_operator"] = adsb_route["operator"]
        if adsb_route.get("aircraft_type"):
            enrichment["fa_aircraft_type"] = adsb_route["aircraft_type"]

    return enrichment


def _prefetch_route_async(icao24: str, callsign: str, route_key: str | None = None) -> None:
    """Worker-thread function: fetch + reconcile route, then write to state.

    Pulls the canonical route from adsb.lol and the LIVE flight track from
    OpenSky.  The reconciler decides whether to trust the canonical route,
    pick a specific leg of a multi-leg route, or suppress stale data.  In
    every case we set ``route_checked_at`` so the scheduler doesn't re-fetch
    immediately even when the result was suppression.
    """
    route_key = route_key or _route_key(icao24, callsign)
    callsign_key = None
    try:
        resolved_callsign = _resolve_route_callsign(icao24, callsign)
        if not resolved_callsign:
            logger.info("route prefetch skipped for %s: no callsign yet", icao24)
            return
        callsign_key = resolved_callsign
        if callsign_key != route_key and not _mark_route_inflight(callsign_key):
            return
        enrichment = _build_route_enrichment(icao24, resolved_callsign)
        if state_mgr.enrich_active(icao24, enrichment, expected_callsign=resolved_callsign):
            if enrichment.get("route_origin"):
                with _route_inflight_lock:
                    first_seen = _route_first_seen.pop(icao24, None)
                if first_seen is not None:
                    logger.info(
                        "route lead-time %s/%s: %.1fs from first radar contact "
                        "to route available (%s→%s)",
                        icao24, resolved_callsign, time.time() - first_seen,
                        enrichment.get("route_origin"),
                        enrichment.get("route_destination") or "?",
                    )
            _emit_current_state()
    except Exception:
        logger.exception("prefetch_route_async failed for %s", callsign)
    finally:
        _clear_route_inflight(route_key)
        if callsign_key and callsign_key != route_key:
            _clear_route_inflight(callsign_key)


def _schedule_route_prefetches(aircraft_list: list[dict]) -> None:
    """Fire-and-forget: queue route lookups for any aircraft in the radar
    list that don't yet have route info.

    Runs at the END of each poll cycle, AFTER the aircraft positions have
    already been broadcast — so the radar dot / list row appears with zero
    added latency. Workers populate state_mgr._active in the background and
    immediately emit a refreshed state when route data changes.
    """
    if config.MOCK_MODE:
        return

    to_submit: list[tuple[str, str, str]] = []
    now = time.time()
    current_icaos: set[str] = set()
    for ac in aircraft_list:
        icao24 = (ac.get("icao24") or "").strip()
        callsign = _normalize_callsign(ac.get("callsign_raw") or ac.get("callsign"))
        if not icao24:
            continue
        current_icaos.add(icao24)
        if ac.get("route_origin"):
            continue  # already enriched
        # First poll this aircraft appears without a route: stamp the moment of
        # radar contact so the worker can report end-to-end lead time.
        with _route_inflight_lock:
            if icao24 not in _route_first_seen:
                _route_first_seen[icao24] = now
                logger.info(
                    "route first contact %s/%s (dist=%sft alt=%sft)",
                    icao24, callsign or "?",
                    ac.get("distance_ft"), ac.get("altitude_ft"),
                )
        # Skip aircraft we recently checked and suppressed (no useful
        # data available right now); they'll be retried after the
        # recheck interval.
        checked_at = ac.get("route_checked_at")
        if checked_at and (now - float(checked_at)) < ROUTE_RECHECK_INTERVAL_SEC:
            continue
        route_key = _route_key(icao24, callsign)
        if _mark_route_inflight(route_key):
            to_submit.append((icao24, callsign, route_key))

    # Drop first-contact stamps for aircraft that have left the radar zone so
    # the dict can't grow unbounded.
    with _route_inflight_lock:
        for stale in [i for i in _route_first_seen if i not in current_icaos]:
            _route_first_seen.pop(stale, None)

    for icao24, callsign, route_key in to_submit:
        _route_executor.submit(_prefetch_route_async, icao24, callsign, route_key)

# --- Health state (pushed to frontend with each update) ---
_health: dict = {
    "status": "ok",         # "ok" | "error"
    "message": "",          # Human-readable description
    "last_success": None,   # Epoch timestamp of last successful poll
    "data_source": config.DATA_SOURCE,
}


def _emit_current_state() -> None:
    """Broadcast current state after out-of-band enrichment updates."""
    state = state_mgr.get_display_state()
    state["health"] = dict(_health)
    if SERVER_VERSION:
        state["server_version"] = SERVER_VERSION
    socketio.emit("aircraft_update", state)


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
                if SERVER_VERSION:
                    error_state["server_version"] = SERVER_VERSION
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

                # Route enrichment: use mock data fields only (live routes via adsb.lol below)
                route_info = None
                if config.MOCK_MODE and ac.get("origin"):
                    route_info = {"origin": ac["origin"], "destination": ac["destination"]}

                # In mock mode, supply typecode when ICAO DB lookup misses
                if not icao_info and config.MOCK_MODE and ac.get("typecode"):
                    icao_info = {"typecode": ac["typecode"]}

                enriched.append(
                    state_mgr.enrich_aircraft(ac, callsign_info, icao_info, route_info)
                )

            # 4. Update state manager
            state = state_mgr.update(
                enriched,
                near_radius_ft=config.RADIUS_LIMIT_FT,
                near_altitude_ft=config.ALTITUDE_LIMIT_FT,
            )

            # 5. Broadcast IMMEDIATELY so aircraft appear on the radar and
            #    list with zero added latency. Cached routes (from prior
            #    polls' async prefetches) are already in state via the
            #    carry-forward logic in state_manager.update().
            state["health"] = dict(_health)
            if SERVER_VERSION:
                state["server_version"] = SERVER_VERSION
            socketio.emit("aircraft_update", state)

            if state.get("events"):
                logger.info("Events: %s", state["events"])

            # 6. Fire-and-forget: schedule async route lookups for any new
            #    callsigns. Workers write back to state_mgr._active and emit
            #    a refreshed state as soon as route data is available.
            _schedule_route_prefetches(state.get("aircraft_list", []))

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
    state = state_mgr.get_display_state()
    if SERVER_VERSION:
        state["server_version"] = SERVER_VERSION
    emit("aircraft_update", state)


@socketio.on("disconnect")
def handle_disconnect():
    """Handle WebSocket client disconnections."""
    logger.info("Client disconnected")


@socketio.on("request_update")
def handle_request_update():
    """Handle manual update requests from the client."""
    state = state_mgr.get_display_state()
    if SERVER_VERSION:
        state["server_version"] = SERVER_VERSION
    emit("aircraft_update", state)


@socketio.on("pin_flight")
def handle_pin_flight(data):
    """Fetch route enrichment for a pinned aircraft and push update."""
    callsign = _normalize_callsign(data.get("callsign"))
    icao24 = (data.get("icao24") or "").strip()
    if not icao24 or config.MOCK_MODE:
        return
    route_key = _route_key(icao24, callsign)
    if not _mark_route_inflight(route_key):
        return
    resolved_callsign = None
    try:
        resolved_callsign = _resolve_route_callsign(icao24, callsign)
        if not resolved_callsign:
            return
        if resolved_callsign != route_key and not _mark_route_inflight(resolved_callsign):
            return
        enrichment = _build_route_enrichment(icao24, resolved_callsign)
    finally:
        _clear_route_inflight(route_key)
        if resolved_callsign and resolved_callsign != route_key:
            _clear_route_inflight(resolved_callsign)

    # Persist enrichment into state manager's active aircraft (survives poll cycles)
    applied = state_mgr.enrich_active(icao24, enrichment, expected_callsign=resolved_callsign)
    if not applied:
        return

    # Emit updated state
    state = state_mgr.get_display_state()
    state["health"] = dict(_health)
    if SERVER_VERSION:
        state["server_version"] = SERVER_VERSION
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


@app.route("/api/reconcile", methods=["GET"])
def diagnostic_reconcile():
    """Diagnostic: run the full reconcile pipeline synchronously."""
    callsign = request.args.get("callsign", "").strip()
    icao24 = request.args.get("icao24", "").strip().lower()
    if not callsign or not icao24:
        return jsonify({"error": "callsign and icao24 required"}), 400
    try:
        t0 = time.time()
        adsb = route_client.get_route(callsign)
        t1 = time.time()
        track = opensky.get_track(icao24)
        t2 = time.time()
        takeoff = find_takeoff_point(track)
        result = reconcile_route(adsb, takeoff)
        return jsonify({
            "callsign": callsign,
            "icao24": icao24,
            "adsb_route": adsb,
            "track_first_point": track[0] if track else None,
            "track_len": len(track) if track else 0,
            "takeoff": takeoff,
            "reconcile": result,
            "timing": {"adsb_ms": int((t1-t0)*1000), "track_ms": int((t2-t1)*1000)},
        })
    except Exception as exc:
        logger.exception("diagnostic_reconcile failed")
        return jsonify({"error": str(exc)}), 500


@app.route("/api/state", methods=["GET"])
def diagnostic_state():
    """Diagnostic: dump current state_manager active aircraft."""
    items = []
    for icao, ac in state_mgr._active.items():
        items.append({
            "icao24": icao,
            "callsign_raw": ac.get("callsign_raw"),
            "altitude_ft": ac.get("altitude_ft"),
            "route_origin": ac.get("route_origin"),
            "route_destination": ac.get("route_destination"),
            "route_display": ac.get("route_display"),
            "route_checked_at": ac.get("route_checked_at"),
        })
    return jsonify({"active": items, "inflight": list(_route_inflight)})


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
