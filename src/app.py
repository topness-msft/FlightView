"""FlightView — Flask application entry point with Flask-SocketIO.

Serves the static frontend and provides real-time aircraft data
over WebSocket connections.
"""

import logging
import threading
import time

from flask import Flask, send_from_directory
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

            # 2. Geographic filter
            filtered = filter_aircraft(
                raw,
                config.HOME_LAT,
                config.HOME_LON,
                config.RADIUS_LIMIT_FT,
                config.ALTITUDE_LIMIT_FT,
            )

            # 3. Enrich each aircraft
            enriched = []
            for ac in filtered:
                icao24 = ac.get("icao24", "")
                callsign = ac.get("callsign", "")

                callsign_info = decode_callsign(callsign)
                icao_info = icao_db.lookup(icao24)

                # Only call ADSBX for aircraft we haven't seen yet
                route_info = None
                if icao24 and icao24 not in _known_icaos:
                    try:
                        route_info = adsbx.get_route(icao24)
                    except Exception:
                        logger.debug("ADSBX route lookup failed for %s", icao24)
                    _known_icaos.add(icao24)

                enriched.append(
                    state_mgr.enrich_aircraft(ac, callsign_info, icao_info, route_info)
                )

            # 4. Update state manager and broadcast
            state = state_mgr.update(enriched)
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


if __name__ == "__main__":
    logger.info("FlightView starting — Home: (%s, %s)", config.HOME_LAT, config.HOME_LON)
    logger.info("  Altitude limit: %s ft | Radius limit: %s ft", config.ALTITUDE_LIMIT_FT, config.RADIUS_LIMIT_FT)
    logger.info("  Poll interval: %ss | Mock mode: %s", config.POLL_INTERVAL_SEC, config.MOCK_MODE)
    socketio.start_background_task(poll_aircraft)
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)
