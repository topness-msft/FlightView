"""Tests for the callsign_decoder module."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
from callsign_decoder import decode_callsign


class TestDecodeKnownAirline:
    def test_southwest(self):
        result = decode_callsign("SWA1234")
        assert result["airline"] == "Southwest Airlines"
        assert result["iata"] == "WN"
        assert result["icao"] == "SWA"
        assert result["flight_number"] == "1234"
        assert result["display"] == "WN 1234"


class TestDecodeMultipleAirlines:
    @pytest.mark.parametrize("callsign,airline,iata,icao", [
        ("UAL567", "United Airlines", "UA", "UAL"),
        ("DAL890", "Delta Air Lines", "DL", "DAL"),
        ("AAL321", "American Airlines", "AA", "AAL"),
    ])
    def test_airline(self, callsign, airline, iata, icao):
        result = decode_callsign(callsign)
        assert result["airline"] == airline
        assert result["iata"] == iata
        assert result["icao"] == icao
        assert result["flight_number"] != ""


class TestDecodeUnknownPrefix:
    def test_unknown_three_letter(self):
        result = decode_callsign("ZZZ999")
        assert result["airline"] == "Unknown"
        assert result["icao"] == "ZZZ"
        assert result["flight_number"] == "999"


class TestDecodeEmptyCallsign:
    def test_empty_string(self):
        result = decode_callsign("")
        assert result["airline"] == "Unknown"
        assert result["display"] == ""

    def test_none(self):
        result = decode_callsign(None)
        assert result["airline"] == "Unknown"

    def test_whitespace_only(self):
        result = decode_callsign("   ")
        assert result["airline"] == "Unknown"
        assert result["display"] == ""


class TestDecodeNumericCallsign:
    def test_pure_digits(self):
        result = decode_callsign("12345")
        assert result["airline"] == "General Aviation"
        assert result["flight_number"] == "12345"
        assert result["display"] == "12345"


class TestDecodeCallsignWithSpaces:
    def test_trailing_space(self):
        result = decode_callsign("SWA1234 ")
        assert result["airline"] == "Southwest Airlines"
        assert result["flight_number"] == "1234"

    def test_leading_space(self):
        result = decode_callsign(" SWA1234")
        assert result["airline"] == "Southwest Airlines"
        assert result["flight_number"] == "1234"
