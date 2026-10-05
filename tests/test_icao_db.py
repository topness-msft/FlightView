"""Tests for the icao_db module."""

import os
import sys
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
import icao_db as icao_db_module
from icao_db import get_aircraft_type, COMMON_TYPECODES, ICAODatabase


VALID_CSV_BYTES = (
    b"icao24,registration,manufacturericao,manufacturername,model,"
    b"typecode,serialnumber,linenumber,icaoaircrafttype,operator,"
    b"operatorcallsign,operatoricao,operatoriata,owner\n"
    b"abc123,N12345,BOEING,Boeing,737-800,B738,12345,1234,L2J,"
    b"Southwest Airlines,SOUTHWEST,SWA,WN,Southwest Airlines\n"
)
SECOND_VALID_CSV_BYTES = VALID_CSV_BYTES.replace(b"abc123", b"def456").replace(
    b"N12345", b"N67890"
)


class FakeResponse:
    def __init__(self, *chunks, content_length=None):
        self._chunks = chunks
        self.raise_for_status = Mock()
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)

    def iter_content(self, chunk_size):
        assert chunk_size == 1_000_000
        yield from self._chunks


@pytest.fixture
def isolated_db_path(tmp_path, monkeypatch):
    db_dir = tmp_path / "data"
    db_path = db_dir / "aircraftDatabase.csv"
    monkeypatch.setattr(icao_db_module, "DB_DIR", db_dir)
    monkeypatch.setattr(icao_db_module, "DB_PATH", db_path)
    monkeypatch.setattr(icao_db_module, "MIN_AIRCRAFT_DB_SIZE_BYTES", 1)
    return db_path


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


class TestEnsureAircraftDatabase:
    def test_uses_valid_existing_cache_without_downloading(
        self, isolated_db_path, monkeypatch
    ):
        isolated_db_path.parent.mkdir()
        isolated_db_path.write_bytes(VALID_CSV_BYTES)
        get = Mock(side_effect=AssertionError("download should not be attempted"))
        monkeypatch.setattr("requests.get", get)

        result = icao_db_module.ensure_aircraft_db()

        assert result == str(isolated_db_path)
        get.assert_not_called()
        assert ICAODatabase(result).lookup("abc123")["registration"] == "N12345"

    def test_replaces_invalid_existing_cache_only_after_valid_download(
        self, isolated_db_path, monkeypatch
    ):
        isolated_db_path.parent.mkdir()
        original = b"<html>upstream error</html>"
        isolated_db_path.write_bytes(original)
        response = FakeResponse(
            SECOND_VALID_CSV_BYTES[:50],
            SECOND_VALID_CSV_BYTES[50:],
            content_length=len(SECOND_VALID_CSV_BYTES),
        )
        get = Mock(return_value=response)
        monkeypatch.setattr("requests.get", get)
        real_replace = os.replace

        def assert_then_replace(source, destination):
            assert isolated_db_path.read_bytes() == original
            assert source != isolated_db_path
            assert Path(destination) == isolated_db_path
            assert ICAODatabase(source).lookup("def456")["registration"] == "N67890"
            real_replace(source, destination)

        replace = Mock(side_effect=assert_then_replace)
        monkeypatch.setattr(icao_db_module.os, "replace", replace)

        result = icao_db_module.ensure_aircraft_db()

        assert result == str(isolated_db_path)
        get.assert_called_once_with(
            icao_db_module.OPENSKY_DB_URL, timeout=120, stream=True
        )
        response.raise_for_status.assert_called_once()
        replace.assert_called_once()
        assert isolated_db_path.read_bytes() == SECOND_VALID_CSV_BYTES
        assert ICAODatabase(result).lookup("def456")["registration"] == "N67890"
        assert list(isolated_db_path.parent.glob("aircraftDatabase-*.tmp")) == []

    def test_downloads_missing_cache_to_temp_before_publishing(
        self, isolated_db_path, monkeypatch
    ):
        response = FakeResponse(
            VALID_CSV_BYTES[:50],
            VALID_CSV_BYTES[50:],
            content_length=len(VALID_CSV_BYTES),
        )
        monkeypatch.setattr("requests.get", Mock(return_value=response))
        real_replace = os.replace

        def assert_then_replace(source, destination):
            assert not isolated_db_path.exists()
            assert source != isolated_db_path
            assert Path(destination) == isolated_db_path
            assert ICAODatabase(source).lookup("abc123")["registration"] == "N12345"
            real_replace(source, destination)

        replace = Mock(side_effect=assert_then_replace)
        monkeypatch.setattr(icao_db_module.os, "replace", replace)

        result = icao_db_module.ensure_aircraft_db()

        assert result == str(isolated_db_path)
        replace.assert_called_once()
        assert ICAODatabase(result).lookup("abc123")["registration"] == "N12345"
        assert list(isolated_db_path.parent.glob("aircraftDatabase-*.tmp")) == []

    def test_does_not_publish_truncated_download(
        self, isolated_db_path, monkeypatch
    ):
        response = FakeResponse(
            VALID_CSV_BYTES,
            content_length=len(VALID_CSV_BYTES) + 1,
        )
        monkeypatch.setattr("requests.get", Mock(return_value=response))
        replace = Mock()
        monkeypatch.setattr(icao_db_module.os, "replace", replace)

        result = icao_db_module.ensure_aircraft_db()

        assert result is None
        replace.assert_not_called()
        assert not isolated_db_path.exists()
        assert list(isolated_db_path.parent.glob("aircraftDatabase-*.tmp")) == []

    def test_rejects_undersized_existing_cache(self, isolated_db_path, monkeypatch):
        monkeypatch.setattr(
            icao_db_module,
            "MIN_AIRCRAFT_DB_SIZE_BYTES",
            len(VALID_CSV_BYTES) + 1,
        )
        isolated_db_path.parent.mkdir()
        isolated_db_path.write_bytes(VALID_CSV_BYTES)
        monkeypatch.setattr(
            "requests.get",
            Mock(return_value=FakeResponse(SECOND_VALID_CSV_BYTES)),
        )

        result = icao_db_module.ensure_aircraft_db()

        assert result is None
        assert isolated_db_path.read_bytes() == VALID_CSV_BYTES

    def test_replace_failure_preserves_existing_cache_and_removes_temp(
        self, isolated_db_path, monkeypatch
    ):
        isolated_db_path.parent.mkdir()
        original = b"<html>upstream error</html>"
        isolated_db_path.write_bytes(original)
        response = FakeResponse(
            SECOND_VALID_CSV_BYTES,
            content_length=len(SECOND_VALID_CSV_BYTES),
        )
        monkeypatch.setattr("requests.get", Mock(return_value=response))
        monkeypatch.setattr(icao_db_module.os, "replace", Mock(side_effect=OSError))

        result = icao_db_module.ensure_aircraft_db()

        assert result is None
        assert isolated_db_path.read_bytes() == original
        assert list(isolated_db_path.parent.glob("aircraftDatabase-*.tmp")) == []

    @pytest.mark.parametrize(
        "payload",
        [
            b"",
            b"<html>upstream error</html>",
            VALID_CSV_BYTES.split(b"\n", 1)[0] + b"\n",
        ],
    )
    def test_does_not_publish_invalid_download(
        self, isolated_db_path, monkeypatch, payload
    ):
        monkeypatch.setattr("requests.get", Mock(return_value=FakeResponse(payload)))
        replace = Mock()
        monkeypatch.setattr(icao_db_module.os, "replace", replace)

        result = icao_db_module.ensure_aircraft_db()

        assert result is None
        replace.assert_not_called()
        assert not isolated_db_path.exists()
        assert list(isolated_db_path.parent.glob("aircraftDatabase-*.tmp")) == []
