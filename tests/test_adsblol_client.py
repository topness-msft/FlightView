"""Tests for AdsbLolClient."""

import os
import sys
import time
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from adsblol_client import AdsbLolClient  # noqa: E402


def _mock_response(status_code: int = 200, json_data: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.raise_for_status = MagicMock()
    return resp


SAMPLE_PAYLOAD = {
    "callsign": "GJS4527",
    "number": "4527",
    "airline_code": "GJS",
    "airport_codes": "KIAD-KSTL",
    "_airport_codes_iata": "IAD-STL",
    "_airports": [
        {
            "name": "Washington Dulles International Airport",
            "icao": "KIAD",
            "iata": "IAD",
            "location": "Washington",
        },
        {
            "name": "Lambert St Louis International Airport",
            "icao": "KSTL",
            "iata": "STL",
            "location": "St Louis",
        },
    ],
}


def test_get_route_returns_iata_pair():
    client = AdsbLolClient()
    with patch("adsblol_client.requests.get", return_value=_mock_response(200, SAMPLE_PAYLOAD)):
        route = client.get_route("GJS4527")
    assert route is not None
    assert route["origin"] == "IAD"
    assert route["destination"] == "STL"
    assert route["origin_name"] == "Washington"
    assert route["destination_name"] == "St Louis"
    assert route["operator"] == ""
    assert route["aircraft_type"] == ""


def test_get_route_404_returns_none():
    client = AdsbLolClient()
    with patch("adsblol_client.requests.get", return_value=_mock_response(404)):
        assert client.get_route("UNKNOWN1") is None


def test_get_route_empty_airports_returns_none():
    client = AdsbLolClient()
    payload = {"callsign": "X", "_airports": []}
    with patch("adsblol_client.requests.get", return_value=_mock_response(200, payload)):
        assert client.get_route("X") is None


def test_get_route_falls_back_to_icao_when_no_iata():
    client = AdsbLolClient()
    payload = {
        "_airports": [
            {"icao": "KAAA", "name": "A"},
            {"icao": "KBBB", "name": "B"},
        ]
    }
    with patch("adsblol_client.requests.get", return_value=_mock_response(200, payload)):
        route = client.get_route("TEST1")
    assert route["origin"] == "KAAA"
    assert route["destination"] == "KBBB"


def test_get_route_caches_result():
    client = AdsbLolClient()
    with patch("adsblol_client.requests.get", return_value=_mock_response(200, SAMPLE_PAYLOAD)) as m:
        client.get_route("GJS4527")
        client.get_route("GJS4527")
        client.get_route("gjs4527")  # case-insensitive
    assert m.call_count == 1


def test_get_route_cache_expires():
    client = AdsbLolClient()
    client.CACHE_TTL_SEC = 0  # immediate expiry
    with patch("adsblol_client.requests.get", return_value=_mock_response(200, SAMPLE_PAYLOAD)) as m:
        client.get_route("GJS4527")
        time.sleep(0.01)
        client.get_route("GJS4527")
    assert m.call_count == 2


def test_get_route_empty_callsign_returns_none():
    client = AdsbLolClient()
    assert client.get_route("") is None
    assert client.get_route("   ") is None


def test_get_route_network_error_returns_none():
    client = AdsbLolClient()
    with patch("adsblol_client.requests.get", side_effect=Exception("boom")):
        assert client.get_route("ABC123") is None
