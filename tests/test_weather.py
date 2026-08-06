from __future__ import annotations

import json
import unittest
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from frame_one.providers.weather import NwsWeatherProvider, OpenMeteoWeatherProvider, WeatherLocation


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


class RoutingOpener:
    def __init__(self, routes: dict[str, object]) -> None:
        self.routes = routes
        self.requests = []

    def __call__(self, request, **kwargs: object) -> FakeResponse:
        self.requests.append(request)
        url = request.full_url
        for fragment, payload in self.routes.items():
            if fragment in url:
                return FakeResponse(payload)
        raise OSError(f"no fake route for {url}")


class OpenMeteoWeatherProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.location = WeatherLocation(40.0, -75.0, "America/New_York")
        self.payload = {
            "current": {"time": "2026-07-28T10:00", "temperature_2m": 72.4, "weather_code": 2, "is_day": 1},
            "daily": {
                "temperature_2m_max": [78.2, 80.1],
                "temperature_2m_min": [65.1, 66.0],
                "weather_code": [2, 61],
                "precipitation_probability_max": [10, 40],
            },
            "hourly": {
                "time": ["2026-07-28T09:00", "2026-07-28T18:00", "2026-07-28T19:00", "2026-07-29T06:00"],
                "temperature_2m": [71, 69, 64, 61],
                "weather_code": [2, 2, 61, 2],
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
                    "tonight_precipitation_type": "RAIN",
                    "tomorrow_high_f": 80,
                    "tomorrow_low_f": 66,
                    "tomorrow_rain_percent": 40,
                    "tomorrow_precipitation_type": "RAIN",
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


class NwsWeatherProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.location = WeatherLocation(40.0, -75.0, "America/New_York")
        self.now = datetime.fromisoformat("2026-08-05T16:55:00-04:00")
        self.fallback = {
            "state": "ok",
            "data": {
                "current_temperature_f": 76,
                "current_condition": "cloudy",
                "today_high_f": 82,
                "today_low_f": 65,
                "tonight_low_f": 72,
                "tonight_rain_percent": 18,
                "tomorrow_high_f": 90,
                "tomorrow_low_f": 72,
                "tomorrow_rain_percent": 14,
            },
        }
        self.routes = {
            "/points/40.0000,-75.0000": {
                "properties": {
                    "forecast": "https://api.weather.gov/gridpoints/PHI/1,2/forecast",
                    "observationStations": "https://api.weather.gov/gridpoints/PHI/1,2/stations",
                }
            },
            "/gridpoints/PHI/1,2/forecast": {
                "properties": {
                    "periods": [
                        {
                            "startTime": "2026-08-05T17:00:00-04:00",
                            "isDaytime": True,
                            "temperature": 84,
                            "probabilityOfPrecipitation": {"value": 61},
                            "shortForecast": "Showers And Thunderstorms Likely",
                        },
                        {
                            "startTime": "2026-08-05T18:00:00-04:00",
                            "isDaytime": False,
                            "temperature": 71,
                            "probabilityOfPrecipitation": {"value": 53},
                            "shortForecast": "Chance Showers And Thunderstorms",
                        },
                        {
                            "startTime": "2026-08-06T06:00:00-04:00",
                            "isDaytime": True,
                            "temperature": 91,
                            "probabilityOfPrecipitation": {"value": 19},
                            "shortForecast": "Mostly Sunny",
                        },
                        {
                            "startTime": "2026-08-06T18:00:00-04:00",
                            "isDaytime": False,
                            "temperature": 72,
                            "probabilityOfPrecipitation": {"value": 30},
                            "shortForecast": "Chance Showers And Thunderstorms",
                        },
                    ]
                }
            },
            "/gridpoints/PHI/1,2/stations": {"features": [{"id": "https://api.weather.gov/stations/KXYZ"}]},
            "/stations/KXYZ/observations/latest": {
                "properties": {
                    "timestamp": "2026-08-05T16:35:00-04:00",
                    "temperature": {"value": 25.0},
                }
            },
            "/alerts/active": {"features": []},
        }

    def provider(self, routes: dict[str, object] | None = None) -> tuple[NwsWeatherProvider, RoutingOpener]:
        opener = RoutingOpener(routes or self.routes)
        provider = NwsWeatherProvider(
            self.location,
            lambda: self.fallback,
            opener=opener,
            now=lambda: self.now,
        )
        return provider, opener

    def test_nws_forecast_is_primary_and_open_meteo_fills_the_missing_today_low(self) -> None:
        provider, opener = self.provider()

        state = provider.get()

        self.assertEqual(state["state"], "ok")
        self.assertEqual(
            state["data"],
            {
                "current_temperature_f": 77,
                "current_condition": "storm",
                "today_high_f": 84,
                "today_low_f": 65,
                "tonight_low_f": 71,
                "tonight_rain_percent": 53,
                "tonight_precipitation_type": "RAIN",
                "tomorrow_high_f": 91,
                "tomorrow_low_f": 72,
                "tomorrow_rain_percent": 30,
                "tomorrow_precipitation_type": "RAIN",
            },
        )
        self.assertTrue(
            all(request.get_header("User-agent") == "frame-one-dashboard/0.1" for request in opener.requests)
        )

    def test_highest_priority_active_alert_overrides_the_condition(self) -> None:
        routes = dict(self.routes)
        routes["/alerts/active"] = {
            "features": [
                {"properties": {"event": "Heat Advisory", "severity": "Moderate", "urgency": "Expected"}},
                {"properties": {"event": "Flash Flood Warning", "severity": "Severe", "urgency": "Immediate"}},
            ]
        }
        provider, _ = self.provider(routes)

        state = provider.get()

        self.assertEqual(state["data"]["active_alert"], "FLASH FLOOD WARNING")
        self.assertEqual(state["data"]["alert_severity"], "Severe")
        self.assertEqual(state["data"]["current_condition"], "storm")

    def test_non_storm_alert_uses_the_generic_alert_mark(self) -> None:
        routes = dict(self.routes)
        routes["/alerts/active"] = {
            "features": [
                {"properties": {"event": "Heat Advisory", "severity": "Moderate", "urgency": "Expected"}}
            ]
        }
        provider, _ = self.provider(routes)

        self.assertEqual(provider.get()["data"]["current_condition"], "alert")

    def test_winter_forecast_uses_specific_precipitation_types(self) -> None:
        routes = dict(self.routes)
        periods = routes["/gridpoints/PHI/1,2/forecast"]["properties"]["periods"]
        winter_periods = [dict(period) for period in periods]
        winter_periods[0]["shortForecast"] = "Snow Showers"
        winter_periods[1]["shortForecast"] = "Snow Likely"
        winter_periods[1]["probabilityOfPrecipitation"] = {"value": 70}
        winter_periods[2]["shortForecast"] = "Sleet And Freezing Rain"
        winter_periods[2]["probabilityOfPrecipitation"] = {"value": 60}
        winter_periods[3]["shortForecast"] = "Mostly Cloudy"
        winter_periods[3]["probabilityOfPrecipitation"] = {"value": 20}
        routes["/gridpoints/PHI/1,2/forecast"] = {"properties": {"periods": winter_periods}}
        provider, _ = self.provider(routes)

        data = provider.get()["data"]

        self.assertEqual(data["tonight_precipitation_type"], "SNOW")
        self.assertEqual(data["tomorrow_precipitation_type"], "MIXED")
        self.assertEqual(data["current_condition"], "snow")

    def test_winter_storm_alert_uses_the_storm_mark(self) -> None:
        routes = dict(self.routes)
        routes["/alerts/active"] = {
            "features": [
                {"properties": {"event": "Winter Storm Warning", "severity": "Severe", "urgency": "Expected"}}
            ]
        }
        provider, _ = self.provider(routes)

        self.assertEqual(provider.get()["data"]["current_condition"], "storm")

    def test_total_nws_failure_returns_the_open_meteo_fallback(self) -> None:
        provider = NwsWeatherProvider(
            self.location,
            lambda: self.fallback,
            opener=lambda *args, **kwargs: (_ for _ in ()).throw(OSError()),
            now=lambda: self.now,
        )

        self.assertEqual(provider.get(), self.fallback)
