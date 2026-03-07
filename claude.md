# FlightView - Project Decisions

## Overview

Real-time overhead flight tracker. Polls ADS-B data, filters aircraft within a configurable radius/altitude of the user's home, and displays flight details on a 7" Raspberry Pi screen in kiosk mode.

## Technology Choices

| Component | Choice | Rationale |
|-----------|--------|-----------|
| **Backend** | Python + Flask | Lightweight, great Pi support, simple API integrations |
| **Frontend** | Vanilla JS + CSS | No build step, minimal resources, fast on Pi |
| **Primary data source** | OpenSky Network API | Free, 5-sec polling, good coverage |
| **Aircraft enrichment** | Static ICAO database (OpenSky CSV) | Free, offline, covers aircraft type/registration/operator |
| **Airline decoding** | ICAO airline prefix table | Decode callsign → airline name + flight number |
| **Route enrichment** | ADS-B Exchange (RapidAPI) | One-time call per new aircraft for origin/destination |
| **Configuration** | .env file | Simple lat/lon + API key config |
| **Display mode** | Fullscreen kiosk browser | Chromium kiosk on Pi, dark theme |
| **Testing** | pytest + Playwright (E2E) | Standard Python testing, browser-based E2E |

## Architecture Decisions

### Data Flow
1. **Poller service** (background thread) calls OpenSky every 5 seconds with bounding box
2. **Filter** checks altitude ≤ 3000 ft and distance ≤ 1500 ft radius from home
3. **Enrichment pipeline**: new aircraft → static ICAO DB lookup → ADSBX route lookup (cached)
4. **WebSocket** pushes updates to the browser frontend
5. **Frontend** renders flight card with priority sorting (closest first)

### Display Behavior
- Single flight card at a time, prioritized by proximity
- Auto-advances when the current aircraft leaves the zone
- Dark theme optimized for 7" 800×480 screen
- Shows: airline logo/name, flight number, aircraft type, route, altitude, speed, distance, direction

### Future Phases
- Aircraft photos (planespotters.net API or similar)
- RTL-SDR receiver integration for direct ADS-B reception
