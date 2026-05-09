# FlightView — Copilot Instructions

## Quick Reference

```bash
# Run the app (from repo root)
cd src && python app.py

# Run all tests
python -m pytest tests\ -v --tb=short

# Run a single test file
python -m pytest tests\test_geo_filter.py -v

# Run a single test by name
python -m pytest tests\test_state_manager.py -v -k "test_aircraft_enters_near_zone"

# Install dependencies
pip install -r requirements.txt
```

There is no linter or build step configured. The frontend is vanilla JS/CSS with no build tools.

## Architecture

Real-time overhead flight tracker for Raspberry Pi kiosk displays. A Flask backend polls ADS-B data, filters/enriches it, and pushes updates to a vanilla JS frontend via WebSocket.

### Data Flow

```
Data Source (RTL-SDR / OpenSky / Mock)
  → geo_filter: haversine distance + bearing from home, filter by altitude/radius
  → callsign_decoder: ICAO airline prefix → airline name + flight number
  → icao_db: typecode → full aircraft type name
  → state_manager: classify near/far zone, detect enter/leave, pick display aircraft
  → adsblol_client: route lookup for display aircraft only (cached 10 min)
  → WebSocket broadcast → frontend renders themed views
```

### Two-Zone Model

This is the central design concept. Aircraft are classified into two zones based on distance and altitude from the configured home location:

- **Near zone** (small radius/low altitude): Triggers a single-plane detail card showing full flight info. The closest aircraft in this zone is selected as the "display" aircraft.
- **Far zone** (large radius/higher altitude): Aircraft appear on a radar scope and departure-board list.

The frontend auto-switches between multi-plane view (radar + list) and single-plane view (detail card) based on whether any aircraft are in the near zone.

### Key Modules

| Module | Role |
|--------|------|
| `app.py` | Flask + SocketIO server, background polling thread, REST config API, health tracking |
| `state_manager.py` | Tracks active aircraft, classifies zones, detects enter/leave events, selects display aircraft by proximity |
| `geo_filter.py` | Haversine distance (ft), bearing, compass direction, filters + sorts by distance |
| `callsign_decoder.py` | Maps 3-letter ICAO airline prefixes to airline names/IATA codes (74+ airlines) |
| `icao_db.py` | Maps ICAO typecodes to full aircraft type names (80+ types), CSV database fallback |
| `flightaware_client` | (removed — replaced by `adsblol_client`) |
| `adsblol_client.py` | adsb.lol route API client (free, no key), 10-min cache per callsign |
| `dump1090_client.py` | Local RTL-SDR receiver HTTP client (readsb/dump1090 JSON) |
| `opensky_client.py` | OpenSky Network REST API client with OAuth2 support |
| `mock_data.py` | Generates 4–8 simulated aircraft with realistic flight behaviors |
| `config.py` | Loads `.env` into a Config dataclass, exposes all settings |

### Frontend

Vanilla JS + CSS in `src/static/`. Two visual themes:
- **Classic**: Solari split-flap board, amber radar, LED dot-matrix route display, cockpit gauges
- **Modern**: Heathrow airport signage (yellow/black detail), cool blue radar with aircraft list

The frontend connects via Socket.IO (`aircraft_update` event) and auto-reconnects on disconnect. Theme preference is stored in localStorage.

## Conventions

### Static Asset Cache Busting

All static assets use `?v=N` query parameters for cache busting. **Bump the version number whenever you modify these files:**

- `index.html` references `style.css?v=44` and `app.js?v=47`
- The Pi kiosk runs Chromium with `--disk-cache-dir=/dev/null`, but the version params are still needed for development browsers

### API Key Masking

The `GET /api/config` endpoint masks API keys in responses (shows `••••xyz`). The frontend only sends a key on save if the user actually changed it (detects the bullet character prefix). See `_mask_key()` in `app.py`.

### Aircraft Type Display

When displaying aircraft type from the ICAO database, use `codeParts.slice(1).join(" ")` to strip the manufacturer prefix — not `codeParts[last]`, which breaks multi-word types like "Boeing 737 MAX 9".

### Route Enrichment

Route lookups via [adsb.lol](https://adsb.lol)'s free community database run only for the display aircraft (nearest in near zone) and are cached 10 minutes per callsign. Route data is propagated back to the matching `aircraft_list` entry for pinned flight views. No API key is required.

### Units

All internal values use aviation units: distance in feet, altitude in feet, velocity in knots, vertical rate in ft/min, bearing in degrees (0–360).

### Test Structure

Tests use `sys.path.insert(0, ...)` to resolve `src/` imports. Helper factories like `_make_aircraft()` build test data dicts. External APIs are mocked with `unittest.mock`.

### Configuration

All settings live in `.env` (see `.env.example`). The config screen (`POST /api/config`) updates settings live and persists them to `.env`. Key settings: `HOME_LAT`/`HOME_LON` (location), `DATA_SOURCE` (rtlsdr/opensky/mock), `MOCK_MODE` (dev/testing), and zone radii/altitudes. Route enrichment via adsb.lol requires no key.

### Deployment

The Pi runs FlightView as a systemd service (`flightview.service`). The `/api/update` endpoint does `git pull` + `systemctl restart`. Passwordless sudo is configured for `systemctl restart flightview` via `/etc/sudoers.d/flightview`.
