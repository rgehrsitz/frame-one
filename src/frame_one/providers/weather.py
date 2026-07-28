"""Open-Meteo forecast adapter for Frame One's compact weather contract."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import urlopen


OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
CURRENT_FIELDS = "temperature_2m,weather_code,is_day"
HOURLY_FIELDS = "temperature_2m,weather_code,precipitation_probability,is_day"
DAILY_FIELDS = "temperature_2m_max,temperature_2m_min,weather_code,precipitation_probability_max"


@dataclass(frozen=True)
class WeatherLocation:
    """An explicit location; Frame One never attempts to infer one."""

    latitude: float
    longitude: float
    timezone: str
    temperature_unit: str = "fahrenheit"


def _condition_for_code(code: int) -> str:
    """Collapse WMO weather codes into the four marks supported by the panel."""
    if code == 0:
        return "clear"
    if code in {1, 2}:
        return "partly_cloudy"
    if code in {3, 45, 48}:
        return "cloudy"
    return "rain"


def _whole_number(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("boolean is not a weather measurement")
    return round(float(value))


def _require_series(payload: dict[str, Any], section: str, field: str) -> list[Any]:
    values = payload.get(section, {}).get(field)
    if not isinstance(values, list) or not values:
        raise ValueError(f"missing {section}.{field}")
    return values


def _tonight_values(payload: dict[str, Any], now: datetime) -> tuple[int, int]:
    """Return the next night period's low temperature and peak rain chance."""
    times = _require_series(payload, "hourly", "time")
    temperatures = _require_series(payload, "hourly", "temperature_2m")
    rain = _require_series(payload, "hourly", "precipitation_probability")
    is_day = _require_series(payload, "hourly", "is_day")
    if not (len(times) == len(temperatures) == len(rain) == len(is_day)):
        raise ValueError("hourly weather series lengths differ")

    night: list[tuple[int, int]] = []
    found_night = False
    for time_text, temperature, probability, day in zip(times, temperatures, rain, is_day):
        hour = datetime.fromisoformat(str(time_text))
        if hour < now:
            continue
        if int(day) == 0:
            found_night = True
            night.append((_whole_number(temperature), _whole_number(probability)))
        elif found_night:
            break
    if not night:
        raise ValueError("no upcoming night hours")
    return min(item[0] for item in night), max(item[1] for item in night)


class OpenMeteoWeatherProvider:
    """Fetch a small, explicit Open-Meteo forecast without credentials."""

    def __init__(
        self,
        location: WeatherLocation,
        opener: Callable[..., Any] = urlopen,
        *,
        url: str = OPEN_METEO_FORECAST_URL,
    ) -> None:
        self._location = location
        self._opener = opener
        self._url = url

    def request_url(self) -> str:
        query = urlencode(
            {
                "latitude": self._location.latitude,
                "longitude": self._location.longitude,
                "timezone": self._location.timezone,
                "temperature_unit": self._location.temperature_unit,
                "forecast_days": 2,
                "current": CURRENT_FIELDS,
                "hourly": HOURLY_FIELDS,
                "daily": DAILY_FIELDS,
            }
        )
        return f"{self._url}?{query}"

    def get(self) -> dict[str, object]:
        """Return an unavailable envelope for any network or schema failure."""
        try:
            with self._opener(self.request_url(), timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return self._parse(payload)
        except (OSError, TimeoutError, ValueError, TypeError, json.JSONDecodeError):
            return {"state": "unavailable", "data": {}}

    @staticmethod
    def _parse(payload: Any) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("weather response must be an object")
        current = payload.get("current")
        if not isinstance(current, dict):
            raise ValueError("missing current conditions")
        now = datetime.fromisoformat(str(current["time"]))
        highs = _require_series(payload, "daily", "temperature_2m_max")
        lows = _require_series(payload, "daily", "temperature_2m_min")
        rain = _require_series(payload, "daily", "precipitation_probability_max")
        if min(len(highs), len(lows), len(rain)) < 2:
            raise ValueError("two daily forecast periods are required")
        tonight_low, tonight_rain = _tonight_values(payload, now)
        return {
            "state": "ok",
            "updated_at": now.isoformat(),
            "stale_after_seconds": 5400,
            "data": {
                "current_temperature_f": _whole_number(current["temperature_2m"]),
                "current_condition": _condition_for_code(_whole_number(current["weather_code"])),
                "today_high_f": _whole_number(highs[0]),
                "today_low_f": _whole_number(lows[0]),
                "tonight_low_f": tonight_low,
                "tonight_rain_percent": tonight_rain,
                "tomorrow_high_f": _whole_number(highs[1]),
                "tomorrow_low_f": _whole_number(lows[1]),
                "tomorrow_rain_percent": _whole_number(rain[1]),
            },
        }
