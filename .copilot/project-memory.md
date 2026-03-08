# FlightView — Project Memory

## Repository
- **GitHub:** https://github.com/topness-msft/FlightView
- **Branch:** main

## What It Is
Real-time overhead flight tracker for Raspberry Pi touchscreen kiosks (7" 800×480 and 10" 1024×600). Two distinctive visual themes with auto-switching between multi-plane radar and single-plane detail views based on aircraft proximity.

## Tech Stack
- **Backend:** Python 3.11+ / Flask / Flask-SocketIO (threading async mode)
- **Frontend:** Vanilla JS + CSS (no build tools), Google Fonts (Outfit + JetBrains Mono)
- **Primary data:** OpenSky Network API (free, no key required)
- **Route enrichment:** FlightAware AeroAPI (free $5/month tier, single-plane only)
- **Aircraft DB:** OpenSky aircraft database (520K records, auto-downloaded ~90MB CSV)
- **Enrichment:** Callsign decoder (100+ airlines including regional carriers), ICAO type lookup
- **Config:** .env file + touch-friendly config screen with .env persistence
- **Tests:** pytest unit tests

## Themes
### Classic
- Warm amber color palette (#F0C850 on #0E0E0C)
- Split-flap cells for airline name and flight code + typecode
- LED dot-matrix display for route (origin → destination)
- Vintage cockpit gauge instruments (SVG with needle, bezels, tick marks, mounting screws)
- Amber radar scope with sweep arm and amber blips
- Card strip list with direction-colored left borders

### Modern
- **Multi-plane:** Cool blue radar (#3B82F6 on #0F172A) with aircraft list
- **Single-plane:** Heathrow airport signage (bright yellow #FECB00, bold black text)
- 4-column grid card strips: flight | airline | typecode | ↕alt ↔dist

## Architecture
```
poll_aircraft() loop (every 15s)
  → OpenSkyClient.fetch_aircraft() OR MockDataSource.fetch_aircraft()
  → geo_filter.filter_aircraft() (haversine + altitude, uses RADAR zone)
  → enrich: callsign_decoder + icao_db (520K records) + mock routes
  → AircraftStateManager.update() (near/far zone classification)
  → FlightAwareClient.get_route() (single-plane display only, 10-min cache)
  → socketio.emit("aircraft_update") → browser WebSocket
```

## Dual-Zone Filtering
- **Near zone** (RADIUS_LIMIT_FT / ALTITUDE_LIMIT_FT): Triggers single-plane detail view + FlightAware route lookup
- **Far zone** (RADAR_RADIUS_FT / RADAR_ALTITUDE_FT): Shown on radar scope and card strip list
- Auto-switching: display field is non-null only when aircraft in near zone

## Key Files
- src/app.py — Flask entry point, poller, FlightAware integration, config API
- src/config.py — .env loader, Config dataclass with dual-zone fields
- src/opensky_client.py — OpenSky REST API client (bbox from RADAR zone, rebuilt each poll)
- src/flightaware_client.py — FlightAware AeroAPI route lookup with 10-min cache
- src/geo_filter.py — Haversine distance, bearing, compass, altitude filter
- src/icao_db.py — Auto-downloads 520K-record OpenSky aircraft database on first run
- src/callsign_decoder.py — 100+ ICAO airline prefixes including regional carriers (UCA→United, etc.)
- src/state_manager.py — Near/far zone classification, aircraft summaries with bearing/direction
- src/mock_data.py — 8 aircraft with 5 behavior types (approaching, departing, passing, far_cruise, far_descend)
- src/static/index.html — 5 screens (classic multi/single, modern multi/single, config)
- src/static/style.css — Complete stylesheet with responsive clamp() sizing
- src/static/app.js — Screen manager, flap engine, gauge engine, dot-matrix engine, radar blips
- deploy-pi.sh — Automated Raspberry Pi deployment (venv, systemd, Chromium kiosk)

## Important Decisions
- OpenSky bbox uses RADAR_RADIUS_FT (not near zone) to catch all regional aircraft
- FlightAware only called for near-zone display aircraft (conserves free-tier API budget)
- FlightAware operator field used as airline fallback when callsign decoder returns "Unknown"
- Regional carriers mapped to parent airlines (UCA/GJS→United, JIA/MXY→American, etc.)
- ICAO aircraft database auto-downloaded to data/ directory (gitignored)
- Cache-busting via ?v=N query params on CSS/JS links
- shortAirline() strips "Airlines" suffix for compact card display

## How to Run
```bash
pip install -r requirements.txt
cp .env.example .env  # Edit with your lat/lon and FlightAware key
cd src && python app.py
# Open http://localhost:5000
```

## Raspberry Pi Deployment
```bash
chmod +x deploy-pi.sh && ./deploy-pi.sh
sudo reboot  # Starts kiosk mode
```
