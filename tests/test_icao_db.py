"""Tests for the icao_db module."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
from icao_db import get_aircraft_type, COMMON_TYPECODES, ICAODatabase


class TestGetAircraftType:
    def test_known_typecode(self):
        assert get_aircraft_type("B738") == "Boeing 737-800"

    def test_known_typecode_lowercase(self):
        assert get_aircraft_type("b738") == "Boeing 737-800"

    def test_unknown_typecode_returns_itself(self):
        assert get_aircraft_type("ZZZZ") == "ZZZZ"

    def test_empty_typecode(self):
        assert get_aircraft_type("") == ""

    def test_none_typecode(self):
        assert get_aircraft_type(None) == ""


class TestCommonTypecodes:
    def test_populated(self):
        assert len(COMMON_TYPECODES) > 0

    def test_contains_common_types(self):
        for code in ("B738", "A320", "B77W", "E175"):
            assert code in COMMON_TYPECODES


class TestICAODatabase:
    def test_lookup_no_csv(self):
        """Lookup returns None when no CSV is loaded."""
        db = ICAODatabase()
        assert db.lookup("a1b2c3") is None

    def test_len_empty(self):
        db = ICAODatabase()
        assert len(db) == 0

    def test_contains_empty(self):
        db = ICAODatabase()
        assert "a1b2c3" not in db

    def test_lookup_empty_icao(self):
        db = ICAODatabase()
        assert db.lookup("") is None
        assert db.lookup(None) is None

    def test_load_from_csv(self, tmp_path):
        """Load a small CSV and verify lookup works."""
        csv_file = tmp_path / "aircraft.csv"
        csv_file.write_text(
            "icao24,registration,manufacturericao,manufacturername,model,"
            "typecode,serialnumber,linenumber,icaoaircrafttype,operator,"
            "operatorcallsign,operatoricao,operatoriata,owner\n"
            "abc123,N12345,BOEING,Boeing,737-800,B738,12345,1234,L2J,"
            "Southwest Airlines,SOUTHWEST,SWA,WN,Southwest Airlines\n"
        )
        db = ICAODatabase(str(csv_file))
        assert len(db) == 1
        assert "abc123" in db
        info = db.lookup("abc123")
        assert info is not None
        assert info["manufacturer"] == "Boeing"
        assert info["typecode"] == "B738"
        assert info["registration"] == "N12345"

    def test_load_nonexistent_file(self):
        """Loading a nonexistent CSV doesn't raise, just logs warning."""
        db = ICAODatabase("/nonexistent/path.csv")
        assert len(db) == 0
