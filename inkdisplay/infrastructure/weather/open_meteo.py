"""Open-Meteo forecast provider, requiring no API key."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests

from inkdisplay.domain.weather import ForecastDay, WeatherSnapshot
from inkdisplay.infrastructure.weather.common import (
    WeatherProviderError,
    create_http_session,
    geocode_city,
    get_json,
    weather_description,
)
from inkdisplay.infrastructure.weather.request import WeatherRequest


class OpenMeteoProvider:
    name = "open-meteo"
    endpoint = "https://api.open-meteo.com/v1/forecast"

    def fetch(self, request: WeatherRequest) -> WeatherSnapshot:
        with create_http_session() as session:
            latitude, longitude, location = self._coordinates(session, request)
            temperature_unit = (
                "fahrenheit" if request.units == "imperial" else "celsius"
            )
            wind_unit = "mph" if request.units == "imperial" else "kmh"
            payload = get_json(
                session,
                self.endpoint,
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "timezone": request.timezone,
                    "forecast_days": 4,
                    "temperature_unit": temperature_unit,
                    "wind_speed_unit": wind_unit,
                    "current": (
                        "temperature_2m,relative_humidity_2m,apparent_temperature,"
                        "is_day,weather_code,pressure_msl,wind_speed_10m"
                    ),
                    "daily": (
                        "weather_code,temperature_2m_min,temperature_2m_max,"
                        "precipitation_probability_max"
                    ),
                },
            )
        return self._parse(payload, request, location)

    @staticmethod
    def _coordinates(
        session: requests.Session, request: WeatherRequest
    ) -> tuple[float, float, str]:
        if request.latitude is not None and request.longitude is not None:
            return (
                request.latitude,
                request.longitude,
                request.city or f"{request.latitude:.2f}, {request.longitude:.2f}",
            )
        if request.city:
            return geocode_city(session, request.city, request.language)
        raise WeatherProviderError("Configure coordinates or a city for weather data.")

    @staticmethod
    def _parse(
        payload: dict[str, Any], request: WeatherRequest, location: str
    ) -> WeatherSnapshot:
        current = payload.get("current")
        daily = payload.get("daily")
        if not isinstance(current, dict) or not isinstance(daily, dict):
            raise WeatherProviderError(
                "Open-Meteo response is missing current or daily data."
            )
        try:
            code = int(current["weather_code"])
            observed_at = datetime.fromisoformat(str(current["time"])).replace(
                tzinfo=ZoneInfo(request.timezone)
            )
            dates = daily["time"]
            codes = daily["weather_code"]
            minimums = daily["temperature_2m_min"]
            maximums = daily["temperature_2m_max"]
            forecast = tuple(
                ForecastDay(
                    date=str(dates[index]),
                    weather_code=int(codes[index]),
                    temperature_min=float(minimums[index]),
                    temperature_max=float(maximums[index]),
                )
                for index in range(1, min(4, len(dates)))
            )
            return WeatherSnapshot(
                location=location,
                observed_at=observed_at.isoformat(),
                weather_code=code,
                description=weather_description(code, request.language),
                temperature=float(current["temperature_2m"]),
                humidity=int(current["relative_humidity_2m"]),
                wind_speed=float(current["wind_speed_10m"]),
                pressure=float(current["pressure_msl"]),
                forecast=forecast,
                feels_like=(
                    float(current["apparent_temperature"])
                    if current.get("apparent_temperature") is not None
                    else None
                ),
                temperature_unit="°F" if request.units == "imperial" else "°C",
                wind_unit="mph" if request.units == "imperial" else "km/h",
                language=request.language,
            )
        except (IndexError, KeyError, TypeError, ValueError) as error:
            raise WeatherProviderError(
                "Open-Meteo response has an invalid schema."
            ) from error
