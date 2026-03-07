"""Tests for the geo_filter module."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
from geo_filter import (
    haversine_distance_ft,
    bearing_from,
    compass_direction,
    filter_aircraft,
)


class TestHaversineDistanceFt:
    def test_known_distance(self):
        """NYC (40.7128, -74.0060) to a point ~1 mile north."""
        # 1 degree of latitude ≈ 364,000 ft; 1 mile ≈ 5280 ft
        nyc_lat, nyc_lon = 40.7128, -74.0060
        # ~1 mile north is roughly +0.01449 degrees latitude
        north_lat = nyc_lat + (5280 / 364000)
        dist = haversine_distance_ft(nyc_lat, nyc_lon, north_lat, nyc_lon)
        assert abs(dist - 5280) < 200  # within 200 ft tolerance

    def test_zero_distance(self):
        """Same point returns 0."""
        assert haversine_distance_ft(40.0, -74.0, 40.0, -74.0) == 0.0


class TestBearingFrom:
    def test_bearing_north(self):
        """Point due north should be ~0 degrees."""
        b = bearing_from(40.0, -74.0, 41.0, -74.0)
        assert abs(b - 0) < 1 or abs(b - 360) < 1

    def test_bearing_south(self):
        """Point due south should be ~180 degrees."""
        b = bearing_from(41.0, -74.0, 40.0, -74.0)
        assert abs(b - 180) < 1

    def test_bearing_east(self):
        """Point due east should be ~90 degrees."""
        b = bearing_from(40.0, -74.0, 40.0, -73.0)
        assert abs(b - 90) < 5

    def test_bearing_west(self):
        """Point due west should be ~270 degrees."""
        b = bearing_from(40.0, -74.0, 40.0, -75.0)
        assert abs(b - 270) < 5


class TestCompassDirection:
    @pytest.mark.parametrize("bearing,expected", [
        (0, "N"),
        (45, "NE"),
        (90, "E"),
        (135, "SE"),
        (180, "S"),
        (225, "SW"),
        (270, "W"),
        (315, "NW"),
    ])
    def test_all_directions(self, bearing, expected):
        assert compass_direction(bearing) == expected


class TestFilterAircraft:
    HOME_LAT = 40.7128
    HOME_LON = -74.0060

    def _make_aircraft(self, icao24, lat_offset=0.001, lon_offset=0.0,
                       altitude_ft=2000):
        return {
            "icao24": icao24,
            "callsign": f"TST{icao24}",
            "latitude": self.HOME_LAT + lat_offset,
            "longitude": self.HOME_LON + lon_offset,
            "altitude_ft": altitude_ft,
        }

    def test_inside_radius_passes(self):
        """Aircraft within radius and altitude passes filter."""
        ac = [self._make_aircraft("a1", lat_offset=0.001)]
        result = filter_aircraft(ac, self.HOME_LAT, self.HOME_LON,
                                 radius_ft=500_000, altitude_limit_ft=10000)
        assert len(result) == 1

    def test_outside_radius_excluded(self):
        """Aircraft outside radius is excluded."""
        ac = [self._make_aircraft("a1", lat_offset=1.0)]  # ~364,000 ft away
        result = filter_aircraft(ac, self.HOME_LAT, self.HOME_LON,
                                 radius_ft=1000, altitude_limit_ft=50000)
        assert len(result) == 0

    def test_above_altitude_excluded(self):
        """Aircraft above altitude limit is excluded."""
        ac = [self._make_aircraft("a1", altitude_ft=50000)]
        result = filter_aircraft(ac, self.HOME_LAT, self.HOME_LON,
                                 radius_ft=500_000, altitude_limit_ft=10000)
        assert len(result) == 0

    def test_sorts_by_distance(self):
        """Result list is sorted by distance (closest first)."""
        ac = [
            self._make_aircraft("far", lat_offset=0.01),
            self._make_aircraft("close", lat_offset=0.001),
            self._make_aircraft("mid", lat_offset=0.005),
        ]
        result = filter_aircraft(ac, self.HOME_LAT, self.HOME_LON,
                                 radius_ft=5_000_000, altitude_limit_ft=50000)
        assert len(result) == 3
        assert result[0]["icao24"] == "close"
        assert result[1]["icao24"] == "mid"
        assert result[2]["icao24"] == "far"

    def test_excludes_null_altitude(self):
        """Aircraft with None altitude is excluded."""
        ac = [self._make_aircraft("a1")]
        ac[0]["altitude_ft"] = None
        result = filter_aircraft(ac, self.HOME_LAT, self.HOME_LON,
                                 radius_ft=500_000, altitude_limit_ft=50000)
        assert len(result) == 0

    def test_excludes_zero_altitude(self):
        """Aircraft with 0 altitude is excluded."""
        ac = [self._make_aircraft("a1", altitude_ft=0)]
        result = filter_aircraft(ac, self.HOME_LAT, self.HOME_LON,
                                 radius_ft=500_000, altitude_limit_ft=50000)
        assert len(result) == 0

    def test_adds_geo_fields(self):
        """Filtered aircraft gets distance_ft, bearing, compass fields."""
        ac = [self._make_aircraft("a1")]
        result = filter_aircraft(ac, self.HOME_LAT, self.HOME_LON,
                                 radius_ft=500_000, altitude_limit_ft=50000)
        assert len(result) == 1
        assert "distance_ft" in result[0]
        assert "bearing" in result[0]
        assert "compass" in result[0]
        assert isinstance(result[0]["distance_ft"], float)
        assert isinstance(result[0]["bearing"], float)
        assert isinstance(result[0]["compass"], str)
