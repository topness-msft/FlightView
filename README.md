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
- 🌐 **Route enrichment** via FlightAware AeroAPI (optional, free tier available)
- 🧪 **Mock data mode** for development and testing without live API access

## Tech Stack

- **Backend:** Python 3.11+ / Flask / Flask-SocketIO
- **Frontend:** Vanilla JS + CSS (no build tools needed)
- **Data Sources:**
  - OpenSky Network — live aircraft positions (free, no API key)
  - FlightAware AeroAPI — route enrichment for single-plane view (optional, $5/month free tier)
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
| `ADSBX_API_KEY` | | FlightAware AeroAPI key (optional, for route data) |
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
│  ├── FlightAware Client (route lookup, cached)       │
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

### FlightAware AeroAPI (optional)
Provides origin → destination route data for the single-plane detail view.

1. Sign up at [flightaware.com/aeroapi](https://www.flightaware.com/aeroapi/)
2. Get a Personal tier key ($5/month free credit — plenty for this use case)
3. Add to config screen or `.env` as `ADSBX_API_KEY`

Routes are only looked up when an aircraft enters the near zone (detail view), with a 10-minute cache per callsign. Typical usage: 20–50 API calls/day.

## License

MIT
