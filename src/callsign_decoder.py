"""Airline callsign decoder for FlightView.

Decodes ICAO callsign prefixes (e.g., UAL -> United Airlines,
DAL -> Delta Air Lines) to airline names and flight numbers.
"""

import logging
import re

logger = logging.getLogger(__name__)

# ICAO 3-letter airline prefixes mapped to airline info
AIRLINE_CODES: dict[str, dict[str, str]] = {
    # United States
    "AAL": {"name": "American Airlines", "iata": "AA"},
    "UAL": {"name": "United Airlines", "iata": "UA"},
    "DAL": {"name": "Delta Air Lines", "iata": "DL"},
    "SWA": {"name": "Southwest Airlines", "iata": "WN"},
    "JBU": {"name": "JetBlue Airways", "iata": "B6"},
    "NKS": {"name": "Spirit Airlines", "iata": "NK"},
    "FFT": {"name": "Frontier Airlines", "iata": "F9"},
    "AAY": {"name": "Allegiant Air", "iata": "G4"},
    "ASA": {"name": "Alaska Airlines", "iata": "AS"},
    "HAL": {"name": "Hawaiian Airlines", "iata": "HA"},
    "SKW": {"name": "SkyWest Airlines", "iata": "OO"},
    "RPA": {"name": "Republic Airways", "iata": "YX"},
    "ENY": {"name": "Envoy Air", "iata": "MQ"},
    "PDT": {"name": "Piedmont Airlines", "iata": "PT"},
    "ASH": {"name": "Mesa Airlines", "iata": "YV"},
    "CPZ": {"name": "Compass Airlines", "iata": "CP"},
    "EDV": {"name": "Endeavor Air", "iata": "9E"},
    "UCA": {"name": "United Airlines", "iata": "UA"},  # CommutAir (United Express)
    "GJS": {"name": "United Airlines", "iata": "UA"},  # GoJet (United Express)
    "AJI": {"name": "United Airlines", "iata": "UA"},  # AmeriJet operating as United
    "JIA": {"name": "American Airlines", "iata": "AA"}, # PSA Airlines (American Eagle)
    "MXY": {"name": "American Airlines", "iata": "AA"}, # Breeze/regional operating as AA
    "EGF": {"name": "American Airlines", "iata": "AA"}, # American Eagle
    "QXE": {"name": "Alaska Airlines", "iata": "AS"},   # Horizon Air
    "FLG": {"name": "Delta Air Lines", "iata": "DL"},   # Chautauqua (Delta Connection)
    "FDX": {"name": "FedEx Express", "iata": "FX"},
    "UPS": {"name": "UPS Airlines", "iata": "5X"},
    # Canada
    "ACA": {"name": "Air Canada", "iata": "AC"},
    "WJA": {"name": "WestJet", "iata": "WS"},
    # Europe
    "BAW": {"name": "British Airways", "iata": "BA"},
    "DLH": {"name": "Lufthansa", "iata": "LH"},
    "AFR": {"name": "Air France", "iata": "AF"},
    "KLM": {"name": "KLM Royal Dutch Airlines", "iata": "KL"},
    "SAS": {"name": "Scandinavian Airlines", "iata": "SK"},
    "FIN": {"name": "Finnair", "iata": "AY"},
    "IBE": {"name": "Iberia", "iata": "IB"},
    "TAP": {"name": "TAP Air Portugal", "iata": "TP"},
    "AZA": {"name": "ITA Airways", "iata": "AZ"},
    "SWR": {"name": "Swiss International Air Lines", "iata": "LX"},
    "AUA": {"name": "Austrian Airlines", "iata": "OS"},
    "BEL": {"name": "Brussels Airlines", "iata": "SN"},
    "EIN": {"name": "Aer Lingus", "iata": "EI"},
    "RYR": {"name": "Ryanair", "iata": "FR"},
    "EZY": {"name": "easyJet", "iata": "U2"},
    "WZZ": {"name": "Wizz Air", "iata": "W6"},
    "VLG": {"name": "Vueling", "iata": "VY"},
    "NLY": {"name": "Norwegian Air Shuttle", "iata": "DY"},
    "THA": {"name": "Thai Airways", "iata": "TG"},
    "THY": {"name": "Turkish Airlines", "iata": "TK"},
    "VIR": {"name": "Virgin Atlantic", "iata": "VS"},
    "LOT": {"name": "LOT Polish Airlines", "iata": "LO"},
    "ICE": {"name": "Icelandair", "iata": "FI"},
    # Middle East
    "UAE": {"name": "Emirates", "iata": "EK"},
    "QTR": {"name": "Qatar Airways", "iata": "QR"},
    "ETD": {"name": "Etihad Airways", "iata": "EY"},
    "SVA": {"name": "Saudia", "iata": "SV"},
    "ELY": {"name": "El Al Israel Airlines", "iata": "LY"},
    # Asia-Pacific
    "CPA": {"name": "Cathay Pacific", "iata": "CX"},
    "SIA": {"name": "Singapore Airlines", "iata": "SQ"},
    "ANA": {"name": "All Nippon Airways", "iata": "NH"},
    "JAL": {"name": "Japan Airlines", "iata": "JL"},
    "KAL": {"name": "Korean Air", "iata": "KE"},
    "AAR": {"name": "Asiana Airlines", "iata": "OZ"},
    "CCA": {"name": "Air China", "iata": "CA"},
    "CES": {"name": "China Eastern Airlines", "iata": "MU"},
    "CSN": {"name": "China Southern Airlines", "iata": "CZ"},
    "EVA": {"name": "EVA Air", "iata": "BR"},
    "MAS": {"name": "Malaysia Airlines", "iata": "MH"},
    "GIA": {"name": "Garuda Indonesia", "iata": "GA"},
    "QFA": {"name": "Qantas", "iata": "QF"},
    "ANZ": {"name": "Air New Zealand", "iata": "NZ"},
    "AIC": {"name": "Air India", "iata": "AI"},
    "VTI": {"name": "Vistara", "iata": "UK"},
    # Latin America
    "TAM": {"name": "LATAM Airlines Brasil", "iata": "JJ"},
    "LAN": {"name": "LATAM Airlines", "iata": "LA"},
    "AVA": {"name": "Avianca", "iata": "AV"},
    "AMX": {"name": "Aeromexico", "iata": "AM"},
    "CMP": {"name": "Copa Airlines", "iata": "CM"},
    # Africa
    "ETH": {"name": "Ethiopian Airlines", "iata": "ET"},
    "SAA": {"name": "South African Airways", "iata": "SA"},
    "RAM": {"name": "Royal Air Maroc", "iata": "AT"},
    "MSR": {"name": "EgyptAir", "iata": "MS"},
}

# Regex: 3 alpha prefix followed by optional flight number (digits, possibly with trailing alpha)
_CALLSIGN_RE = re.compile(r"^([A-Z]{3})(.*)$", re.IGNORECASE)


def decode_callsign(callsign: str) -> dict:
    """Decode an ICAO callsign into airline name and flight number.

    Args:
        callsign: Raw callsign string, e.g. "SWA1234" or "UAL456".

    Returns:
        Dict with keys: airline, iata, icao, flight_number, display.
    """
    if not callsign or not isinstance(callsign, str):
        return {
            "airline": "Unknown",
            "iata": "",
            "icao": "",
            "flight_number": "",
            "display": "",
        }

    cs = callsign.strip()
    if not cs:
        return {
            "airline": "Unknown",
            "iata": "",
            "icao": "",
            "flight_number": "",
            "display": "",
        }

    # Purely numeric callsigns indicate general aviation
    if cs.isdigit():
        return {
            "airline": "General Aviation",
            "iata": "",
            "icao": "",
            "flight_number": cs,
            "display": cs,
        }

    match = _CALLSIGN_RE.match(cs)
    if not match:
        return {
            "airline": "Unknown",
            "iata": "",
            "icao": cs[:3] if len(cs) >= 3 else cs,
            "flight_number": cs[3:] if len(cs) > 3 else "",
            "display": cs,
        }

    prefix = match.group(1).upper()
    flight_num = match.group(2).strip()

    airline_info = AIRLINE_CODES.get(prefix)
    if airline_info:
        iata = airline_info["iata"]
        display = f"{iata} {flight_num}" if flight_num else iata
        return {
            "airline": airline_info["name"],
            "iata": iata,
            "icao": prefix,
            "flight_number": flight_num,
            "display": display,
        }

    return {
        "airline": "Unknown",
        "iata": "",
        "icao": prefix,
        "flight_number": flight_num,
        "display": cs,
    }
