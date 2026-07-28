from __future__ import annotations

import json
import unittest
from urllib.parse import parse_qs, urlparse

from frame_one.providers.weather import OpenMeteoWeatherProvider, WeatherLocation


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


class OpenMeteoWeatherProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.location = WeatherLocation(40.0, -75.0, "America/New_York")
        self.payload = {
            "current": {"time": "2026-07-28T10:00", "temperature_2m": 72.4, "weather_code": 2, "is_day": 1},
            "daily": {
                "temperature_2m_max": [78.2, 80.1],
                "temperature_2m_min": [65.1, 66.0],
                "precipitation_probability_max": [10, 40],
            },
            "hourly": {
                "time": ["2026-07-28T09:00", "2026-07-28T18:00", "2026-07-28T19:00", "2026-07-29T06:00"],
                "temperature_2m": [71, 69, 64, 61],
                "precipitation_probability": [0, 10, 30, 20],
                "is_day": [1, 0, 0, 1],
            },
        }

    def test_normalizes_weather_and_uses_next_night_period(self) -> None:
        provider = OpenMeteoWeatherProvider(self.location, opener=lambda *args, **kwargs: FakeResponse(self.payload))

        self.assertEqual(
            provider.get(),
            {
                "state": "ok",
                "updated_at": "2026-07-28T10:00:00",
                "stale_after_seconds": 5400,
                "data": {
                    "current_temperature_f": 72,
                    "current_condition": "partly_cloudy",
                    "today_high_f": 78,
                    "today_low_f": 65,
                    "tonight_low_f": 64,
                    "tonight_rain_percent": 30,
                    "tomorrow_high_f": 80,
                    "tomorrow_low_f": 66,
                    "tomorrow_rain_percent": 40,
                },
            },
        )

    def test_request_is_explicit_and_uses_no_api_key(self) -> None:
        provider = OpenMeteoWeatherProvider(self.location)
        query = parse_qs(urlparse(provider.request_url()).query)

        self.assertEqual(query["latitude"], ["40.0"])
        self.assertEqual(query["longitude"], ["-75.0"])
        self.assertEqual(query["timezone"], ["America/New_York"])
        self.assertEqual(query["temperature_unit"], ["fahrenheit"])
        self.assertNotIn("apikey", query)

    def test_network_or_invalid_response_is_unavailable(self) -> None:
        provider = OpenMeteoWeatherProvider(self.location, opener=lambda *args, **kwargs: (_ for _ in ()).throw(OSError()))
        self.assertEqual(provider.get(), {"state": "unavailable", "data": {}})

        invalid = OpenMeteoWeatherProvider(self.location, opener=lambda *args, **kwargs: FakeResponse({}))
        self.assertEqual(invalid.get(), {"state": "unavailable", "data": {}})
