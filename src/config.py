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
    FLIGHTAWARE_API_KEY: str = os.getenv("FLIGHTAWARE_API_KEY", "")
    OPENSKY_CLIENT_ID: str = os.getenv("OPENSKY_CLIENT_ID", "")
    OPENSKY_CLIENT_SECRET: str = os.getenv("OPENSKY_CLIENT_SECRET", "")
    MOCK_MODE: bool = os.getenv("MOCK_MODE", "False").lower() in ("true", "1", "yes")
    DATA_SOURCE: str = os.getenv("DATA_SOURCE", "")
    DUMP1090_URL: str = os.getenv("DUMP1090_URL", "http://localhost:8080")

    def __post_init__(self):
        """Resolve DATA_SOURCE with backward compatibility for MOCK_MODE."""
        if not self.DATA_SOURCE:
            # Legacy: MOCK_MODE=true → data_source=mock, else default to rtlsdr
            self.DATA_SOURCE = "mock" if self.MOCK_MODE else "rtlsdr"
        # Keep MOCK_MODE in sync for backward compat
        self.MOCK_MODE = self.DATA_SOURCE == "mock"


config = Config()
