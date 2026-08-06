"""Open-Meteo forecast adapter for Frame One's compact weather contract."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
NWS_API_URL = "https://api.weather.gov"
NWS_USER_AGENT = "frame-one-dashboard/0.1"
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


def _precipitation_type_for_code(code: int) -> str | None:
    """Map WMO weather codes to the short precipitation labels on the panel."""
    if code in {56, 57, 66, 67}:
        return "ICE"
    if code in {71, 73, 75, 77, 85, 86}:
        return "SNOW"
    if code in {51, 53, 55, 61, 63, 65, 80, 81, 82, 95, 96, 99}:
        return "RAIN"
    return None


def _condition_for_code(code: int) -> str:
    """Collapse WMO weather codes into the marks supported by the panel."""
    if code == 0:
        return "clear"
    if code in {1, 2}:
        return "partly_cloudy"
    if code in {3, 45, 48}:
        return "cloudy"
    precipitation_type = _precipitation_type_for_code(code)
    if precipitation_type == "SNOW":
        return "snow"
    if precipitation_type == "ICE":
        return "ice"
    if code in {95, 96, 99}:
        return "storm"
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


def _tonight_values(payload: dict[str, Any], now: datetime) -> tuple[int, int, str]:
    """Return the next night period's low, peak precipitation chance, and type."""
    times = _require_series(payload, "hourly", "time")
    temperatures = _require_series(payload, "hourly", "temperature_2m")
    rain = _require_series(payload, "hourly", "precipitation_probability")
    is_day = _require_series(payload, "hourly", "is_day")
    weather_codes = payload.get("hourly", {}).get("weather_code")
    if not isinstance(weather_codes, list) or len(weather_codes) != len(times):
        weather_codes = [None] * len(times)
    if not (len(times) == len(temperatures) == len(rain) == len(is_day)):
        raise ValueError("hourly weather series lengths differ")

    night: list[tuple[int, int, int | None]] = []
    found_night = False
    for time_text, temperature, probability, day, weather_code in zip(
        times, temperatures, rain, is_day, weather_codes
    ):
        hour = datetime.fromisoformat(str(time_text))
        if hour < now:
            continue
        if int(day) == 0:
            found_night = True
            normalized_code = _whole_number(weather_code) if weather_code is not None else None
            night.append((_whole_number(temperature), _whole_number(probability), normalized_code))
        elif found_night:
            break
    if not night:
        raise ValueError("no upcoming night hours")
    peak_probability = max(item[1] for item in night)
    peak_types = {
        precipitation_type
        for _, probability, code in night
        if probability == peak_probability and code is not None
        for precipitation_type in [_precipitation_type_for_code(code)]
        if precipitation_type is not None
    }
    precipitation_type = next(iter(peak_types)) if len(peak_types) == 1 else "MIXED" if peak_types else "RAIN"
    return min(item[0] for item in night), peak_probability, precipitation_type


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
        tonight_low, tonight_rain, tonight_precipitation_type = _tonight_values(payload, now)
        daily_codes = payload.get("daily", {}).get("weather_code")
        tomorrow_precipitation_type = "RAIN"
        if isinstance(daily_codes, list) and len(daily_codes) >= 2:
            tomorrow_precipitation_type = _precipitation_type_for_code(_whole_number(daily_codes[1])) or "RAIN"
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
                "tonight_precipitation_type": tonight_precipitation_type,
                "tomorrow_high_f": _whole_number(highs[1]),
                "tomorrow_low_f": _whole_number(lows[1]),
                "tomorrow_rain_percent": _whole_number(rain[1]),
                "tomorrow_precipitation_type": tomorrow_precipitation_type,
            },
        }


def _precipitation_type_for_text(value: Any) -> str | None:
    text = str(value).casefold()
    if "wintry mix" in text or "mixed precipitation" in text:
        return "MIXED"
    freezing_rain = "freezing rain" in text or "freezing drizzle" in text or "ice pellets" in text
    sleet = "sleet" in text
    snow = "snow" in text or "flurr" in text
    rain_text = text.replace("freezing rain", "").replace("freezing drizzle", "")
    rain = "rain" in rain_text or "drizzle" in rain_text or (
        "shower" in rain_text and not any((freezing_rain, sleet, snow))
    )
    types = [name for name, present in (("ICE", freezing_rain), ("SLEET", sleet), ("SNOW", snow), ("RAIN", rain)) if present]
    if len(types) > 1:
        return "MIXED"
    return types[0] if types else None


def _condition_for_text(value: Any) -> str | None:
    text = str(value).casefold()
    if any(word in text for word in ("tornado", "thunderstorm")):
        return "storm"
    precipitation_type = _precipitation_type_for_text(text)
    if precipitation_type is not None:
        return {
            "SNOW": "snow",
            "SLEET": "sleet",
            "ICE": "ice",
            "MIXED": "mixed",
        }.get(precipitation_type, "rain")
    if any(word in text for word in ("partly", "mostly sunny", "mostly clear")):
        return "partly_cloudy"
    if any(word in text for word in ("cloudy", "overcast", "fog")):
        return "cloudy"
    if any(word in text for word in ("sunny", "clear")):
        return "clear"
    return None


def _period_probability(period: dict[str, Any]) -> int | None:
    probability = period.get("probabilityOfPrecipitation")
    if not isinstance(probability, dict) or probability.get("value") is None:
        return None
    return _whole_number(probability["value"])


def _periods_precipitation_type(periods: list[dict[str, Any] | None]) -> str | None:
    """Use the precipitation type from the period with the highest probability."""
    candidates: list[tuple[int, str]] = []
    for period in periods:
        if period is None:
            continue
        precipitation_type = _precipitation_type_for_text(period.get("shortForecast"))
        probability = _period_probability(period)
        if precipitation_type is not None:
            candidates.append((probability if probability is not None else -1, precipitation_type))
    if not candidates:
        return None
    peak = max(probability for probability, _ in candidates)
    types = {precipitation_type for probability, precipitation_type in candidates if probability == peak}
    return next(iter(types)) if len(types) == 1 else "MIXED"


def _period_for(
    periods: list[dict[str, Any]],
    *,
    date: date,
    daytime: bool,
) -> dict[str, Any] | None:
    for period in periods:
        try:
            starts = datetime.fromisoformat(str(period["startTime"]))
        except (KeyError, ValueError):
            continue
        if starts.date() == date and period.get("isDaytime") is daytime:
            return period
    return None


def _alert_priority(alert: dict[str, Any]) -> tuple[int, int]:
    severity = {"Extreme": 4, "Severe": 3, "Moderate": 2, "Minor": 1}.get(str(alert.get("severity")), 0)
    urgency = {"Immediate": 4, "Expected": 3, "Future": 2, "Past": 1}.get(str(alert.get("urgency")), 0)
    return severity, urgency


def _alert_condition(event: str) -> str:
    storm_terms = (
        "flood",
        "thunderstorm",
        "tornado",
        "hurricane",
        "tropical storm",
        "squall",
        "winter storm",
        "blizzard",
        "ice storm",
    )
    return "storm" if any(term in event.casefold() for term in storm_terms) else "alert"


class NwsWeatherProvider:
    """Use NWS forecasts and alerts, retaining Open-Meteo as a fallback/fill."""

    def __init__(
        self,
        location: WeatherLocation,
        fallback: Callable[[], dict[str, object]],
        opener: Callable[..., Any] = urlopen,
        *,
        now: Callable[[], datetime] = lambda: datetime.now().astimezone(),
        api_url: str = NWS_API_URL,
    ) -> None:
        self._location = location
        self._fallback = fallback
        self._opener = opener
        self._now = now
        self._api_url = api_url.rstrip("/")

    def _get_json(self, url: str) -> dict[str, Any]:
        request = Request(url, headers={"User-Agent": NWS_USER_AGENT, "Accept": "application/geo+json"})
        with self._opener(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("NWS response must be an object")
        return payload

    def _alerts(self) -> list[dict[str, Any]]:
        point = f"{self._location.latitude:.4f},{self._location.longitude:.4f}"
        payload = self._get_json(f"{self._api_url}/alerts/active?{urlencode({'point': point})}")
        features = payload.get("features")
        if not isinstance(features, list):
            raise ValueError("NWS alert response has no features")
        return [
            feature["properties"]
            for feature in features
            if isinstance(feature, dict) and isinstance(feature.get("properties"), dict)
        ]

    def _forecast_data(self) -> dict[str, object]:
        point = f"{self._location.latitude:.4f},{self._location.longitude:.4f}"
        point_payload = self._get_json(f"{self._api_url}/points/{point}")
        point_properties = point_payload.get("properties")
        if not isinstance(point_properties, dict):
            raise ValueError("NWS point response has no properties")

        forecast_url = point_properties.get("forecast")
        stations_url = point_properties.get("observationStations")
        if not isinstance(forecast_url, str) or not isinstance(stations_url, str):
            raise ValueError("NWS point response has no linked forecast")

        forecast = self._get_json(forecast_url).get("properties")
        if not isinstance(forecast, dict) or not isinstance(forecast.get("periods"), list):
            raise ValueError("NWS forecast response has no periods")
        periods = [period for period in forecast["periods"] if isinstance(period, dict)]
        if not periods:
            raise ValueError("NWS forecast response has no usable periods")

        now = self._now().astimezone(ZoneInfo(self._location.timezone))
        today = now.date()
        tomorrow = today + timedelta(days=1)
        today_day = _period_for(periods, date=today, daytime=True)
        tonight = _period_for(periods, date=today, daytime=False)
        tomorrow_day = _period_for(periods, date=tomorrow, daytime=True)
        tomorrow_night = _period_for(periods, date=tomorrow, daytime=False)

        data: dict[str, object] = {}
        current_condition = _condition_for_text(periods[0].get("shortForecast"))
        if current_condition is not None:
            data["current_condition"] = current_condition
        if today_day is not None:
            data["today_high_f"] = _whole_number(today_day["temperature"])
        if tonight is not None:
            data["tonight_low_f"] = _whole_number(tonight["temperature"])
            tonight_probability = _period_probability(tonight)
            if tonight_probability is not None:
                data["tonight_rain_percent"] = tonight_probability
            tonight_precipitation_type = _periods_precipitation_type([tonight])
            if tonight_precipitation_type is not None:
                data["tonight_precipitation_type"] = tonight_precipitation_type
        if tomorrow_day is not None:
            data["tomorrow_high_f"] = _whole_number(tomorrow_day["temperature"])
        if tomorrow_night is not None:
            data["tomorrow_low_f"] = _whole_number(tomorrow_night["temperature"])
        tomorrow_probabilities = [
            probability
            for probability in (
                _period_probability(tomorrow_day) if tomorrow_day else None,
                _period_probability(tomorrow_night) if tomorrow_night else None,
            )
            if probability is not None
        ]
        if tomorrow_probabilities:
            data["tomorrow_rain_percent"] = max(tomorrow_probabilities)
        tomorrow_precipitation_type = _periods_precipitation_type([tomorrow_day, tomorrow_night])
        if tomorrow_precipitation_type is not None:
            data["tomorrow_precipitation_type"] = tomorrow_precipitation_type

        stations = self._get_json(stations_url).get("features")
        if isinstance(stations, list) and stations:
            station = stations[0]
            if isinstance(station, dict) and isinstance(station.get("id"), str):
                observation = self._get_json(station["id"] + "/observations/latest").get("properties")
                if isinstance(observation, dict):
                    self._add_fresh_observation(data, observation, now)
        return data

    @staticmethod
    def _add_fresh_observation(data: dict[str, object], observation: dict[str, Any], now: datetime) -> None:
        try:
            observed_at = datetime.fromisoformat(str(observation["timestamp"]))
            temperature = observation["temperature"]["value"]
            age = now.astimezone(observed_at.tzinfo) - observed_at
            if temperature is not None and timedelta(0) <= age <= timedelta(minutes=45):
                data["current_temperature_f"] = round(float(temperature) * 9 / 5 + 32)
        except (KeyError, TypeError, ValueError):
            return

    def get(self) -> dict[str, object]:
        try:
            fallback_state = self._fallback()
        except Exception:
            fallback_state = {"state": "unavailable", "data": {}}
        if not isinstance(fallback_state, dict):
            fallback_state = {"state": "unavailable", "data": {}}
        fallback_data = fallback_state.get("data")
        data = dict(fallback_data) if fallback_state.get("state") == "ok" and isinstance(fallback_data, dict) else {}

        nws_succeeded = False
        try:
            data.update(self._forecast_data())
            nws_succeeded = True
        except (OSError, TimeoutError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            pass

        try:
            alerts = self._alerts()
            nws_succeeded = True
            if alerts:
                alert = max(alerts, key=_alert_priority)
                event = str(alert.get("event") or "WEATHER ALERT")
                data["active_alert"] = event.upper()
                data["alert_severity"] = str(alert.get("severity") or "Unknown")
                data["current_condition"] = _alert_condition(event)
        except (OSError, TimeoutError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            pass

        if not nws_succeeded:
            return fallback_state
        return {
            "state": "ok",
            "updated_at": self._now().isoformat(),
            "stale_after_seconds": 5400,
            "data": data,
        }
