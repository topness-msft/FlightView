# FlightView ✈️

Real-time overhead flight tracker for Raspberry Pi touchscreen kiosks. Detects aircraft flying near your home and displays flight details on 7" (800×480) or 10" (1024×600) screens with two distinctive visual themes.

![Classic Theme](classic-board.png) ![Modern Theme](flightview-splitflap.png)

## Features

- 🛩️ **Real-time ADS-B tracking** via OpenSky Network API (free, no key required)
- 📍 **Dual-zone filtering** — near zone triggers detail view, far zone shows on radar/board
- ✈️ **Rich flight data** — airline, flight number, aircraft type, route (origin → destination)
- 🎨 **Two visual themes:**
  - **Classic** — Solari split-flap departure board with vintage cockpit gauges, LED dot-matrix route display, and amber radar scope
  - **Modern** — Heathrow airport signage (bright yellow, bold black) for detail view, cool blue radar with aircraft list for multi-plane
- 🔄 **Auto-switching** between multi-plane (radar + list) and single-plane (detail card) based on aircraft proximity
- 📱 **Touch-friendly config screen** for all settings
- 📐 **Responsive layout** for 800×480 and 1024×600 screens
- 🌐 **Route enrichment** via [adsb.lol](https://adsb.lol) (free, community-maintained, no key required)
- 🧪 **Mock data mode** for development and testing without live API access

## Tech Stack

- **Backend:** Python 3.11+ / Flask / Flask-SocketIO
- **Frontend:** Vanilla JS + CSS (no build tools needed)
- **Data Sources:**
  - OpenSky Network — live aircraft positions (free, no API key)
  - adsb.lol — route enrichment for single-plane view (free, no API key)
- **Enrichment:** Static ICAO aircraft database + airline callsign decoder (100+ airlines)
- **Fonts:** Outfit + JetBrains Mono (loaded from Google Fonts)

## Quick Start

```bash
# Clone
git clone https://github.com/topness-msft/FlightView.git
cd FlightView

# Install dependencies
pip install -r requirements.txt

# Configure your location
cp .env.example .env
# Edit .env with your lat/lon

# Run
cd src && python app.py
```

Open `http://localhost:5000` in a browser. Use the ⚙ button for settings, and the theme toggle (bottom-left) to switch between Classic and Modern.

## Raspberry Pi Deployment

A deployment script is included for kiosk mode on Raspberry Pi:

```bash
chmod +x deploy-pi.sh
./deploy-pi.sh
```

This will:
1. Install system dependencies (Python, Chromium, unclutter)
2. Create a Python virtual environment and install packages
3. Prompt you to configure `.env` (home location, API keys)
4. Install a systemd service for auto-start
5. Configure Chromium kiosk mode (fullscreen, no cursor)
6. Disable screen blanking

After deployment, reboot the Pi to start kiosk mode.

### Managing the Service

```bash
sudo systemctl status flightview    # Check status
sudo systemctl restart flightview   # Restart
sudo journalctl -u flightview -f    # View live logs
```

## Configuration

All settings can be changed via the touch-friendly config screen (⚙ button) or by editing `.env`:

| Setting | Default | Description |
|---------|---------|-------------|
| `HOME_LAT` | `47.6062` | Your latitude |
| `HOME_LON` | `-122.3321` | Your longitude |
| `ALTITUDE_LIMIT_FT` | `3000` | Near zone altitude ceiling (triggers detail view) |
| `RADIUS_LIMIT_FT` | `1500` | Near zone radius (triggers detail view) |
| `RADAR_ALTITUDE_FT` | `15000` | Far zone altitude ceiling (shown on radar/board) |
| `RADAR_RADIUS_FT` | `15000` | Far zone radius (shown on radar/board) |
| `POLL_INTERVAL_SEC` | `15` | How often to poll OpenSky (seconds) |
| `MOCK_MODE` | `False` | Enable mock data for testing |

### Zone Configuration Tips

- **Near a major airport:** Set near zone to 15,000–30,000 ft radius and 15,000 ft altitude to catch departing aircraft
- **Under a flight path:** Near zone of 5,000–10,000 ft radius and 5,000 ft altitude works well
- **Far zone:** Set to 60,000 ft for both to see all regional traffic on radar

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Browser (Vanilla JS + CSS)                          │
│  ├── Screen Manager (auto-switch multi ↔ single)     │
│  ├── Classic Theme (split-flap, gauges, dot-matrix)  │
│  ├── Modern Theme (Heathrow signage, blue radar)     │
│  └── Config Screen (touch-friendly)                  │
└──────────────────┬──────────────────────────────────┘
                   │ WebSocket (Socket.IO)
┌──────────────────┴──────────────────────────────────┐
│  Flask Server                                        │
│  ├── Poller Thread (OpenSky → geo_filter → enrich)   │
│  ├── State Manager (near/far zone classification)    │
│  ├── adsb.lol Client (route lookup, cached)         │
│  ├── Callsign Decoder (100+ airline ICAO codes)      │
│  └── Config API (GET/POST with .env persistence)     │
└─────────────────────────────────────────────────────┘
```

## Development

```bash
# Run with mock data (no API access needed)
# Set MOCK_MODE=True in .env, then:
cd src && python app.py

# Run tests
pytest tests/
```

Mock mode generates 4–7 simulated aircraft with realistic behaviors (approaching, departing, passing, far cruise) and full route/airline data.

## API Keys

No API keys required. Route enrichment uses [adsb.lol](https://adsb.lol)'s free community route database — origin → destination is looked up by callsign when an aircraft enters the near zone, with a 10-minute cache per callsign.

## ESP32 companion display

The Waveshare **ESP32-S3-Touch-LCD-7B** (1024×600 touchscreen model) can run a
read-only native version of the modern theme. Firmware and USB setup instructions
are in [`firmware/flightview-7b`](firmware/flightview-7b/README.md). The ESP32 is a
microcontroller, not a browser: the Pi keeps tracking and enriching flights, and
the companion renders its state using LVGL.

The firmware and SDK test application build with ESP-IDF 5.5.1; the resolved
component versions are committed in the firmware lockfile. Physical-board
bring-up is still pending. A successful build or host protocol probe is not
proof of correct rendering or Wi-Fi operation on the actual display.

The Pi exposes **`GET /api/v1/display`** on its existing HTTP port, normally
`http://<pi-address>:5000/api/v1/display`. Use a reserved LAN address or resolvable
hostname. No extra process, provider key, or receiver is needed on the companion.
The endpoint reads memory only: polling it does not trigger additional ADS-B or
route requests. Existing `/api/state` remains a diagnostic endpoint.

The companion polls once per second. A non-null `display` selects the overhead
detail screen; null selects radar/list. It follows the Pi's automatic selection,
not browser-local pinned flights, theme choices, or settings screens. It receives
up to 32 nearest aircraft and shows up to 10 list entries, with total counts when
the display is limited.

This endpoint has **no authentication** and is intended only for a trusted home
LAN. Do not expose or port-forward FlightView to the internet. The read-only
companion does not protect the existing settings/update endpoints.

### Display feed contract (version 1)

| Field | Meaning |
|-------|---------|
| `schema_version` | `1`; clients must reject unsupported versions |
| `display` | Authoritative selected flight, or `null` |
| `aircraft` | One distance-ordered array shared by radar/list, at most 32 entries |
| `counts` | `total_aircraft`, `nearby_aircraft`, `returned_aircraft`, `truncated` |
| `zones` | `near_radius_ft` and `radar_radius_ft`; no home coordinates |
| `freshness` | `source_state_observed_at`, `state_age_ms`, `stale_after_ms`, `is_initial`, `is_stale` |
| `health` | Safe `status`, `data_source`, and `message`; no raw receiver errors |
| `server_version` | Optional diagnostic revision; not the schema version |

Each aircraft contains `icao24`, `callsign`, `flight_display`, `airline`,
`typecode`, `aircraft_type`, `registration`, route airport/city fields,
`altitude_ft`, `velocity_kts`, `distance_ft`, `vertical_rate_fpm`, `bearing`,
`heading`, `compass`, and `direction`. Unknown text is empty; unknown numeric
values are `null`, distinct from zero. Bearing and heading are degrees clockwise
from north. List summaries may omit registration data, represented as an empty
string. Missing routes must not be presented as a known itinerary.

Observation age advances from the last completed aircraft-state update using
the Pi's monotonic clock. Neither GET requests nor route-only enrichment renews
it. The stale threshold is the greater of 10 seconds and three source polling
intervals. Before the first completed observation, the timestamp/age are null
and the feed is initial/stale. A successful empty observation is a fresh empty
sky. On transport failure, retain the last screen with an offline warning; on
source error or excessive age, mark the data accordingly. The ESP32 advances
received age locally and does not need internet clock synchronization.

The current OpenSky client can return an empty observation on a provider error;
this feed preserves that existing behavior rather than adding outage detection.

Responses use `Cache-Control: no-store` and a hard **64 KiB body limit**. Text is
bounded by UTF-8 bytes (see `TEXT_LIMITS` in `src/display_projection.py`), with
control characters removed. Invalid display configuration or a serialization
bound violation returns HTTP 503 with `{"error":"Display feed unavailable"}`;
clients must not replace their last valid model with an error response.

## License

MIT
