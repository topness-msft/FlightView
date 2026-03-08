"""Configuration loader for FlightView.

Loads settings from a .env file in the project root using python-dotenv
and exposes them via a Config dataclass.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (projects/flightview/.env)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


@dataclass
class Config:
    """Application configuration loaded from environment variables."""

    HOME_LAT: float = float(os.getenv("HOME_LAT", "0.0"))
    HOME_LON: float = float(os.getenv("HOME_LON", "0.0"))
    ALTITUDE_LIMIT_FT: int = int(os.getenv("ALTITUDE_LIMIT_FT", "3000"))
    RADIUS_LIMIT_FT: int = int(os.getenv("RADIUS_LIMIT_FT", "1500"))
    RADAR_ALTITUDE_FT: int = int(os.getenv("RADAR_ALTITUDE_FT", "15000"))
    RADAR_RADIUS_FT: int = int(os.getenv("RADAR_RADIUS_FT", "15000"))
    POLL_INTERVAL_SEC: int = int(os.getenv("POLL_INTERVAL_SEC", "5"))
    ADSBX_API_KEY: str = os.getenv("ADSBX_API_KEY", "")
    OPENSKY_CLIENT_ID: str = os.getenv("OPENSKY_CLIENT_ID", "")
    OPENSKY_CLIENT_SECRET: str = os.getenv("OPENSKY_CLIENT_SECRET", "")
    MOCK_MODE: bool = os.getenv("MOCK_MODE", "False").lower() in ("true", "1", "yes")


config = Config()
