"""Mock data provider for FlightView development.

Generates realistic fake aircraft data for testing the UI
without requiring live API access.
"""

import math
import random
import time

MOCK_AIRCRAFT = [
    {"icao24": "a1b2c3", "callsign": "SWA1234", "typecode": "B738", "origin": "DAL", "destination": "ORD"},
    {"icao24": "d4e5f6", "callsign": "UAL567", "typecode": "A320", "origin": "SFO", "destination": "JFK"},
    {"icao24": "789abc", "callsign": "DAL890", "typecode": "B763", "origin": "ATL", "destination": "LAX"},
    {"icao24": "def012", "callsign": "AAL321", "typecode": "A321", "origin": "DFW", "destination": "MIA"},
    {"icao24": "345678", "callsign": "JBU456", "typecode": "A320", "origin": "BOS", "destination": "FLL"},
    {"icao24": "9abcde", "callsign": "NKS789", "typecode": "A320", "origin": "LAS", "destination": "MSP"},
    {"icao24": "f01234", "callsign": "ASA111", "typecode": "B739", "origin": "SEA", "destination": "PDX"},
    {"icao24": "567890", "callsign": "FFT222", "typecode": "E75L", "origin": "IAH", "destination": "DEN"},
]

# Feet per degree of latitude (approximate)
_FEET_PER_DEG_LAT = 364_000


class MockDataSource:
    """Generates simulated aircraft data for local testing."""

    def __init__(self, home_lat: float, home_lon: float) -> None:
        self.home_lat = home_lat
        self.home_lon = home_lon
        self._tick = 0
        # Pre-generate per-aircraft simulation state
        self._sim: dict[str, dict] = {}
        for ac in MOCK_AIRCRAFT:
            self._sim[ac["icao24"]] = self._init_sim(ac)

    def _init_sim(self, ac: dict) -> dict:
        """Create initial simulation state for one aircraft."""
        behaviour = random.choice(["approaching", "departing", "passing"])
        angle = random.uniform(0, 2 * math.pi)

        if behaviour == "approaching":
            distance_ft = random.uniform(2500, 3500)
            altitude_ft = random.uniform(2500, 4000)
            dist_rate = random.uniform(-120, -40)
            alt_rate = random.uniform(-80, -20)
        elif behaviour == "departing":
            distance_ft = random.uniform(200, 800)
            altitude_ft = random.uniform(500, 1200)
            dist_rate = random.uniform(40, 120)
            alt_rate = random.uniform(20, 80)
        else:  # passing
            distance_ft = random.uniform(800, 2500)
            altitude_ft = random.uniform(1500, 3500)
            dist_rate = random.uniform(-30, 30)
            alt_rate = random.uniform(-10, 10)

        return {
            **ac,
            "angle": angle,
            "distance_ft": distance_ft,
            "altitude_ft": altitude_ft,
            "dist_rate": dist_rate,
            "alt_rate": alt_rate,
            "heading": math.degrees(angle) % 360,
            "velocity_kts": random.uniform(120, 280),
        }

    def _advance(self, sim: dict) -> None:
        """Advance simulation state by one tick."""
        sim["distance_ft"] += sim["dist_rate"] + random.uniform(-15, 15)
        sim["altitude_ft"] += sim["alt_rate"] + random.uniform(-10, 10)
        sim["angle"] += random.uniform(-0.05, 0.05)
        sim["heading"] = (sim["heading"] + random.uniform(-2, 2)) % 360
        sim["velocity_kts"] += random.uniform(-5, 5)
        sim["velocity_kts"] = max(80, min(350, sim["velocity_kts"]))

        # Clamp and reset if out of range
        if sim["distance_ft"] < 100 or sim["distance_ft"] > 4000:
            sim["dist_rate"] = -sim["dist_rate"]
        if sim["altitude_ft"] < 400 or sim["altitude_ft"] > 4200:
            sim["alt_rate"] = -sim["alt_rate"]
        sim["distance_ft"] = max(100, min(4000, sim["distance_ft"]))
        sim["altitude_ft"] = max(400, min(4200, sim["altitude_ft"]))

    def fetch_aircraft(self) -> list[dict]:
        """Return a list of aircraft dicts matching OpenSkyClient.fetch_aircraft() format."""
        self._tick += 1

        # Advance all simulations
        for sim in self._sim.values():
            self._advance(sim)

        # Pick a random subset of 2-5 aircraft
        count = random.randint(2, 5)
        chosen = random.sample(list(self._sim.values()), min(count, len(self._sim)))

        results = []
        for sim in chosen:
            # Convert polar distance/angle to lat/lon offset
            dist_deg = sim["distance_ft"] / _FEET_PER_DEG_LAT
            cos_lat = math.cos(math.radians(self.home_lat)) or 1.0
            lat = self.home_lat + dist_deg * math.cos(sim["angle"])
            lon = self.home_lon + (dist_deg * math.sin(sim["angle"])) / cos_lat

            vertical_rate_fpm = sim["alt_rate"] * 60  # approximate ft/min

            results.append({
                "icao24": sim["icao24"],
                "callsign": sim["callsign"],
                "latitude": round(lat, 6),
                "longitude": round(lon, 6),
                "altitude_ft": round(sim["altitude_ft"], 1),
                "velocity_kts": round(sim["velocity_kts"], 1),
                "heading": round(sim["heading"], 1),
                "vertical_rate_fpm": round(vertical_rate_fpm, 1),
                "on_ground": False,
                "last_contact": int(time.time()),
            })

        return results
