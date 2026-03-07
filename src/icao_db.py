"""Static ICAO aircraft database for FlightView.

Provides aircraft metadata lookup by ICAO hex address using a bundled
dataset, and a static mapping of ICAO type designators to human-readable
aircraft names.
"""

import csv
import logging

logger = logging.getLogger(__name__)

# Common ICAO type designators mapped to readable aircraft names
COMMON_TYPECODES: dict[str, str] = {
    # Boeing narrow-body
    "B731": "Boeing 737-100",
    "B732": "Boeing 737-200",
    "B733": "Boeing 737-300",
    "B734": "Boeing 737-400",
    "B735": "Boeing 737-500",
    "B736": "Boeing 737-600",
    "B737": "Boeing 737-700",
    "B738": "Boeing 737-800",
    "B739": "Boeing 737-900",
    "B37M": "Boeing 737 MAX 7",
    "B38M": "Boeing 737 MAX 8",
    "B39M": "Boeing 737 MAX 9",
    "B3XM": "Boeing 737 MAX 10",
    # Boeing wide-body
    "B741": "Boeing 747-100",
    "B742": "Boeing 747-200",
    "B743": "Boeing 747-300",
    "B744": "Boeing 747-400",
    "B748": "Boeing 747-8",
    "B752": "Boeing 757-200",
    "B753": "Boeing 757-300",
    "B762": "Boeing 767-200",
    "B763": "Boeing 767-300",
    "B764": "Boeing 767-400",
    "B772": "Boeing 777-200",
    "B77L": "Boeing 777-200LR",
    "B773": "Boeing 777-300",
    "B77W": "Boeing 777-300ER",
    "B778": "Boeing 777-8",
    "B779": "Boeing 777-9",
    "B788": "Boeing 787-8 Dreamliner",
    "B789": "Boeing 787-9 Dreamliner",
    "B78X": "Boeing 787-10 Dreamliner",
    # Airbus narrow-body
    "A318": "Airbus A318",
    "A319": "Airbus A319",
    "A320": "Airbus A320",
    "A321": "Airbus A321",
    "A19N": "Airbus A319neo",
    "A20N": "Airbus A320neo",
    "A21N": "Airbus A321neo",
    # Airbus wide-body
    "A332": "Airbus A330-200",
    "A333": "Airbus A330-300",
    "A338": "Airbus A330-800neo",
    "A339": "Airbus A330-900neo",
    "A342": "Airbus A340-200",
    "A343": "Airbus A340-300",
    "A345": "Airbus A340-500",
    "A346": "Airbus A340-600",
    "A359": "Airbus A350-900",
    "A35K": "Airbus A350-1000",
    "A380": "Airbus A380",
    # Embraer
    "E135": "Embraer ERJ-135",
    "E145": "Embraer ERJ-145",
    "E170": "Embraer E170",
    "E175": "Embraer E175",
    "E190": "Embraer E190",
    "E195": "Embraer E195",
    "E290": "Embraer E190-E2",
    "E295": "Embraer E195-E2",
    # Bombardier / De Havilland Canada
    "CRJ1": "Bombardier CRJ-100",
    "CRJ2": "Bombardier CRJ-200",
    "CRJ7": "Bombardier CRJ-700",
    "CRJ9": "Bombardier CRJ-900",
    "CRJX": "Bombardier CRJ-1000",
    "DH8A": "De Havilland Canada Dash 8-100",
    "DH8D": "De Havilland Canada Dash 8-400",
    # ATR
    "AT43": "ATR 42-300",
    "AT45": "ATR 42-500",
    "AT72": "ATR 72-200",
    "AT76": "ATR 72-600",
    # General aviation
    "C172": "Cessna 172 Skyhawk",
    "C208": "Cessna 208 Caravan",
    "C510": "Cessna Citation Mustang",
    "C56X": "Cessna Citation Excel",
    "C680": "Cessna Citation Sovereign",
    "PA28": "Piper PA-28 Cherokee",
    "PC12": "Pilatus PC-12",
    "GLF6": "Gulfstream G650",
    "GL7T": "Gulfstream G700",
    "GA6C": "Gulfstream G600",
    "CL35": "Bombardier Challenger 350",
}


def get_aircraft_type(typecode: str) -> str:
    """Look up the readable aircraft name for a given ICAO type designator.

    Returns the human-readable name if found, otherwise returns the
    typecode itself.
    """
    if not typecode:
        return ""
    return COMMON_TYPECODES.get(typecode.upper().strip(), typecode)


class ICAODatabase:
    """Aircraft metadata lookup by ICAO 24-bit hex address.

    Loads aircraft data from a CSV file (OpenSky aircraft database format)
    into an in-memory dict for fast lookups.
    """

    # Column indices in the OpenSky aircraft database CSV
    _COLUMNS = {
        "icao24": 0,
        "registration": 1,
        "manufacturericao": 2,
        "manufacturername": 3,
        "model": 4,
        "typecode": 5,
        "serialnumber": 6,
        "linenumber": 7,
        "icaoaircrafttype": 8,
        "operator": 9,
        "operatorcallsign": 10,
        "operatoricao": 11,
        "operatoriata": 12,
        "owner": 13,
    }

    def __init__(self, db_path: str | None = None):
        self._db: dict[str, dict] = {}
        if db_path:
            self._load(db_path)

    def _load(self, db_path: str) -> None:
        """Load the OpenSky aircraft database CSV into memory."""
        count = 0
        try:
            with open(db_path, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.reader(f)
                header = next(reader, None)

                # Build column map from header if available
                col_map = self._COLUMNS.copy()
                if header:
                    header_lower = [h.strip().lower() for h in header]
                    for col_name, default_idx in self._COLUMNS.items():
                        if col_name in header_lower:
                            col_map[col_name] = header_lower.index(col_name)

                for row in reader:
                    if not row:
                        continue
                    try:
                        icao24 = row[col_map["icao24"]].strip().lower()
                        if not icao24:
                            continue
                        self._db[icao24] = {
                            "manufacturer": self._safe_get(row, col_map["manufacturername"]),
                            "model": self._safe_get(row, col_map["model"]),
                            "typecode": self._safe_get(row, col_map["typecode"]),
                            "registration": self._safe_get(row, col_map["registration"]),
                            "owner": self._safe_get(row, col_map["owner"]),
                            "operator": self._safe_get(row, col_map["operator"]),
                        }
                        count += 1
                    except (IndexError, ValueError):
                        continue

            logger.info("Loaded %d aircraft records from %s", count, db_path)
        except FileNotFoundError:
            logger.warning("Aircraft database file not found: %s", db_path)
        except Exception:
            logger.exception("Error loading aircraft database from %s", db_path)

    @staticmethod
    def _safe_get(row: list, index: int) -> str:
        """Safely get a value from a CSV row by index."""
        try:
            return row[index].strip() if index < len(row) else ""
        except (IndexError, AttributeError):
            return ""

    def lookup(self, icao24: str) -> dict | None:
        """Look up aircraft info by ICAO 24-bit hex address.

        Returns a dict with keys: manufacturer, model, typecode,
        registration, owner, operator — or None if not found.
        """
        if not icao24:
            return None
        return self._db.get(icao24.strip().lower())

    def __len__(self) -> int:
        return len(self._db)

    def __contains__(self, icao24: str) -> bool:
        if not icao24:
            return False
        return icao24.strip().lower() in self._db


# Module-level singleton
icao_db = ICAODatabase()
