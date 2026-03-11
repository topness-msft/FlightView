"""Tests for Dump1090Client — JSON parsing, field mapping, health tracking."""

import time
from unittest.mock import patch, MagicMock

import pytest

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dump1090_client import Dump1090Client, Dump1090Error


# --- Sample dump1090 JSON payloads ---

SAMPLE_AIRCRAFT_JSON = {
    "now": 1710000000.0,
    "messages": 12345,
    "aircraft": [
        {
            "hex": "a12345",
            "flight": "SWA1234 ",
            "lat": 47.6,
            "lon": -122.3,
            "alt_baro": 3500,
            "gs": 250.0,
            "track": 180.0,
            "baro_rate": -500,
            "seen": 1.2,
        },
        {
            "hex": "b67890",
            "flight": "UAL567",
            "lat": 47.7,
            "lon": -122.4,
            "alt_baro": 12000,
            "gs": 400.0,
            "track": 90.0,
            "baro_rate": 0,
            "seen": 0.5,
        },
    ],
}


class TestParseAircraft:
    """Test _parse_aircraft static method field mapping."""

    def test_basic_mapping(self):
        ac = SAMPLE_AIRCRAFT_JSON["aircraft"][0]
        result = Dump1090Client._parse_aircraft(ac)
        assert result is not None
        assert result["icao24"] == "a12345"
        assert result["callsign"] == "SWA1234"  # trailing space stripped
        assert result["latitude"] == 47.6
        assert result["longitude"] == -122.3
        assert result["altitude_ft"] == 3500.0
        assert result["velocity_kts"] == 250.0
        assert result["heading"] == 180.0
        assert result["vertical_rate_fpm"] == -500.0
        assert result["on_ground"] is False

    def test_no_position_returns_none(self):
        ac = {"hex": "aabbcc", "flight": "TST1", "alt_baro": 5000}
        assert Dump1090Client._parse_aircraft(ac) is None

    def test_no_lat_returns_none(self):
        ac = {"hex": "aabbcc", "lon": -122.0, "alt_baro": 5000}
        assert Dump1090Client._parse_aircraft(ac) is None

    def test_ground_returns_none(self):
        ac = {"hex": "aabbcc", "lat": 47.0, "lon": -122.0, "alt_baro": "ground"}
        assert Dump1090Client._parse_aircraft(ac) is None

    def test_no_altitude_returns_none(self):
        ac = {"hex": "aabbcc", "lat": 47.0, "lon": -122.0}
        assert Dump1090Client._parse_aircraft(ac) is None

    def test_no_hex_returns_none(self):
        ac = {"lat": 47.0, "lon": -122.0, "alt_baro": 5000}
        assert Dump1090Client._parse_aircraft(ac) is None

    def test_missing_optional_fields_default_zero(self):
        ac = {"hex": "abcdef", "lat": 47.0, "lon": -122.0, "alt_baro": 1000}
        result = Dump1090Client._parse_aircraft(ac)
        assert result is not None
        assert result["velocity_kts"] == 0.0
        assert result["heading"] == 0.0
        assert result["vertical_rate_fpm"] == 0.0
        assert result["callsign"] == ""

    def test_hex_normalized_lowercase(self):
        ac = {"hex": "AABBCC", "lat": 47.0, "lon": -122.0, "alt_baro": 1000}
        result = Dump1090Client._parse_aircraft(ac)
        assert result["icao24"] == "aabbcc"

    def test_last_contact_derived_from_seen(self):
        ac = {"hex": "abc123", "lat": 47.0, "lon": -122.0, "alt_baro": 5000, "seen": 2.0}
        before = time.time()
        result = Dump1090Client._parse_aircraft(ac)
        after = time.time()
        assert before - 2.0 <= result["last_contact"] <= after - 2.0


class TestFetchAircraft:
    """Test fetch_aircraft with mocked HTTP responses."""

    @patch("dump1090_client.requests.get")
    def test_successful_fetch(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = SAMPLE_AIRCRAFT_JSON
        mock_get.return_value = mock_resp

        client = Dump1090Client("http://localhost:8080")
        result = client.fetch_aircraft()
        assert len(result) == 2
        assert result[0]["icao24"] == "a12345"
        assert result[1]["icao24"] == "b67890"
        assert client.consecutive_failures == 0

    @patch("dump1090_client.requests.get")
    def test_empty_aircraft_list(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"now": 0, "aircraft": []}
        mock_get.return_value = mock_resp

        client = Dump1090Client()
        result = client.fetch_aircraft()
        assert result == []

    @patch("dump1090_client.requests.get")
    def test_filters_no_position(self, mock_get):
        data = {
            "aircraft": [
                {"hex": "aaa", "lat": 47.0, "lon": -122.0, "alt_baro": 5000},
                {"hex": "bbb", "alt_baro": 3000},  # no position
                {"hex": "ccc", "lat": 47.1, "lon": -122.1, "alt_baro": "ground"},  # on ground
            ]
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = data
        mock_get.return_value = mock_resp

        client = Dump1090Client()
        result = client.fetch_aircraft()
        assert len(result) == 1
        assert result[0]["icao24"] == "aaa"

    @patch("dump1090_client.requests.get")
    def test_connection_error_raises(self, mock_get):
        import requests
        mock_get.side_effect = requests.ConnectionError("Connection refused")

        client = Dump1090Client()
        with pytest.raises(Dump1090Error, match="Cannot connect"):
            client.fetch_aircraft()
        assert client.consecutive_failures == 1

    @patch("dump1090_client.requests.get")
    def test_invalid_json_raises(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("bad json")
        mock_get.return_value = mock_resp

        client = Dump1090Client()
        with pytest.raises(Dump1090Error, match="invalid JSON"):
            client.fetch_aircraft()

    @patch("dump1090_client.requests.get")
    def test_http_error_raises(self, mock_get):
        import requests
        mock_get.side_effect = requests.HTTPError("500 Server Error")

        client = Dump1090Client()
        with pytest.raises(Dump1090Error):
            client.fetch_aircraft()


class TestHealthTracking:
    """Test consecutive failure counting and recovery."""

    @patch("dump1090_client.requests.get")
    def test_failure_count_increments(self, mock_get):
        import requests
        mock_get.side_effect = requests.ConnectionError("fail")

        client = Dump1090Client()
        for i in range(3):
            with pytest.raises(Dump1090Error):
                client.fetch_aircraft()
            assert client.consecutive_failures == i + 1

    @patch("dump1090_client.requests.get")
    def test_recovery_resets_count(self, mock_get):
        import requests

        client = Dump1090Client()

        # Simulate 3 failures
        mock_get.side_effect = requests.ConnectionError("fail")
        for _ in range(3):
            with pytest.raises(Dump1090Error):
                client.fetch_aircraft()
        assert client.consecutive_failures == 3

        # Then a success
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"aircraft": []}
        mock_get.side_effect = None
        mock_get.return_value = mock_resp

        client._aircraft_url = None  # reset cached URL after failures
        client.fetch_aircraft()
        assert client.consecutive_failures == 0
        assert client.last_success is not None

    @patch("dump1090_client.requests.get")
    def test_last_success_updates(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"aircraft": []}
        mock_get.return_value = mock_resp

        client = Dump1090Client()
        assert client.last_success is None

        before = time.time()
        client.fetch_aircraft()
        after = time.time()

        assert before <= client.last_success <= after


class TestHealthCheck:
    """Test the health_check convenience method."""

    @patch("dump1090_client.requests.get")
    def test_healthy(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        client = Dump1090Client()
        result = client.health_check()
        assert result["ok"] is True

    @patch("dump1090_client.requests.get")
    def test_unhealthy(self, mock_get):
        import requests
        mock_get.side_effect = requests.ConnectionError("refused")

        client = Dump1090Client()
        result = client.health_check()
        assert result["ok"] is False
        assert "Cannot connect" in result["message"]


class TestConfigBackwardCompat:
    """Test DATA_SOURCE / MOCK_MODE backward compatibility."""

    def test_mock_mode_true_sets_data_source_mock(self):
        with patch.dict(os.environ, {"MOCK_MODE": "true", "DATA_SOURCE": ""}, clear=False):
            # Re-import to pick up env changes
            import importlib
            import config as cfg_mod
            importlib.reload(cfg_mod)
            assert cfg_mod.config.DATA_SOURCE == "mock"
            assert cfg_mod.config.MOCK_MODE is True

    def test_default_is_rtlsdr(self):
        with patch.dict(os.environ, {"MOCK_MODE": "false", "DATA_SOURCE": ""}, clear=False):
            import importlib
            import config as cfg_mod
            importlib.reload(cfg_mod)
            assert cfg_mod.config.DATA_SOURCE == "rtlsdr"
            assert cfg_mod.config.MOCK_MODE is False

    def test_explicit_data_source_wins(self):
        with patch.dict(os.environ, {"DATA_SOURCE": "opensky", "MOCK_MODE": "false"}, clear=False):
            import importlib
            import config as cfg_mod
            importlib.reload(cfg_mod)
            assert cfg_mod.config.DATA_SOURCE == "opensky"
            assert cfg_mod.config.MOCK_MODE is False
