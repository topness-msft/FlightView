# FlightView — Project Memory

## Repository
- **GitHub:** https://github.com/topness-msft/FlightView
- **Local path:** C:\Users\user\copilot\projects\flightview
- **Branch:** main

## What It Is
Real-time overhead flight tracker for Raspberry Pi with a 7" screen. Polls ADS-B data, detects aircraft within 3000 ft altitude and 1500 ft radius of the user's home, displays flight details in a dark-themed web UI via kiosk browser.

## Tech Stack
- **Backend:** Python / Flask / Flask-SocketIO (threading async mode)
- **Frontend:** Vanilla JS + CSS, dark theme, 800x480 optimized
- **Primary data:** OpenSky Network API (free, 5-sec polling)
- **Enrichment:** Static ICAO aircraft DB (80 types) + airline callsign decoder (74 airlines)
- **Route data:** ADS-B Exchange via RapidAPI (one-time per aircraft, cached)
- **Config:** .env file (lat/lon, radius, altitude, API key, mock mode)
- **Tests:** pytest, 53 unit tests across 4 modules

## Architecture
```
poll_aircraft() loop (every 5s)
  -> OpenSkyClient.fetch_aircraft() OR MockDataSource.fetch_aircraft()
  -> geo_filter.filter_aircraft() (haversine + altitude)
  -> enrich: callsign_decoder + icao_db + adsbx_client
  -> AircraftStateManager.update() (enter/leave detection, closest-first priority)
  -> socketio.emit("aircraft_update") -> browser WebSocket
```

## Key Files
- src/app.py — Flask entry point, integration pipeline, background poller
- src/config.py — .env loader, Config dataclass
- src/opensky_client.py — OpenSky REST API client with bounding box
- src/geo_filter.py — Haversine distance, bearing, compass, altitude filter
- src/icao_db.py — Static ICAO aircraft type database (80 typecodes)
- src/callsign_decoder.py — ICAO 3-letter airline prefix to name (74 airlines)
- src/adsbx_client.py — ADS-B Exchange route enrichment with TTL cache
- src/state_manager.py — Active aircraft tracking, enter/leave events, display priority
- src/mock_data.py — 8 simulated aircraft with movement for local dev
- src/static/index.html — Flight card UI
- src/static/style.css — Dark theme (#0a0a1a bg, #4ecca3 accent)
- src/static/app.js — WebSocket client, card rendering, fade transitions
- tests/ — 4 test files, 53 tests (geo_filter, callsign_decoder, icao_db, state_manager)

## Task Status (as of 2026-03-07)
- 13/14 tasks complete
- Pending: #014 E2E tests (Playwright) — not yet started
- Future: aircraft photos, Pi deployment docs, RTL-SDR receiver integration

## Important Decisions
- Switched from eventlet to threading async mode (eventlet was unstable/deprecated)
- Mock mode enabled via MOCK_MODE=True in .env for local testing
- Display: single flight card, closest-first priority, auto-advance when aircraft leaves zone
- ADSBX route lookup only fires once per new aircraft (cached), minimizing API calls
- User wants aircraft images in a future phase

## How to Run
```bash
cd projects/flightview
pip install -r requirements.txt
# .env already configured with MOCK_MODE=True
cd src && python app.py
# Open http://localhost:5000
```
