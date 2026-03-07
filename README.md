# FlightView

Real-time overhead flight tracker for Raspberry Pi. Detects aircraft flying near your home and displays flight details on a 7" screen.

## Features

- 🛩️ Real-time ADS-B tracking via OpenSky Network
- 📍 Configurable home location with radius/altitude filters
- ✈️ Rich flight data: airline, flight number, aircraft type, route
- 🖥️ Dark-themed display optimized for 7" Pi screen
- 🔄 Auto-cycling display prioritized by proximity

## Tech Stack

- **Backend:** Python / Flask / Flask-SocketIO
- **Frontend:** Vanilla JS + CSS (dark theme)
- **Data Sources:** OpenSky Network (polling) + ADS-B Exchange (route enrichment)
- **Enrichment:** Static ICAO aircraft database + airline callsign decoder

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Configure your location
cp .env.example .env
# Edit .env with your lat/lon and optional ADSBX API key

# Run
python src/app.py
```

Open `http://localhost:5000` in a browser (or Chromium kiosk on Pi).

## Configuration

Create a `.env` file:

```env
HOME_LAT=47.6062
HOME_LON=-122.3321
ALTITUDE_LIMIT_FT=3000
RADIUS_LIMIT_FT=1500
POLL_INTERVAL_SEC=5
ADSBX_API_KEY=your_key_here  # Optional, for route enrichment
```

## License

MIT
