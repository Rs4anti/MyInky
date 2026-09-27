"""OpenWeatherMap current conditions and 3-day forecast provider."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from inkdisplay.domain.weather import ForecastDay, WeatherSnapshot
from inkdisplay.infrastructure.weather.common import (
    WeatherProviderError,
    create_http_session,
    get_json,
    openweather_to_wmo,
)
from inkdisplay.infrastructure.weather.request import WeatherRequest


class OpenWeatherMapProvider:
    name = "openweathermap"
    current_endpoint = "https://api.openweathermap.org/data/2.5/weather"
    forecast_endpoint = "https://api.openweathermap.org/data/2.5/forecast"

    def fetch(self, request: WeatherRequest) -> WeatherSnapshot:
        if not request.api_key:
            raise WeatherProviderError("An OpenWeatherMap API key is required.")
        location_params = self._location_params(request)
        provider_units = (
            "imperial"
            if request.units == "imperial"
            else "standard" if request.units == "standard" else "metric"
        )
        common_params: dict[str, str | int | float] = {
            **location_params,
            "appid": request.api_key,
            "units": provider_units,
            "lang": request.language,
        }
        with create_http_session() as session:
            current = get_json(session, self.current_endpoint, params=common_params)
            forecast_payload = get_json(
                session, self.forecast_endpoint, params=common_params
            )
        return self._parse(current, forecast_payload, request)

    @staticmethod
    def _location_params(request: WeatherRequest) -> dict[str, str | int | float]:
        if request.latitude is not None and request.longitude is not None:
            return {"lat": request.latitude, "lon": request.longitude}
        if request.city:
            return {"q": request.city}
        raise WeatherProviderError("Configure coordinates or a city for weather data.")

    @staticmethod
    def _parse(
        current: dict[str, Any],
        forecast_payload: dict[str, Any],
        request: WeatherRequest,
    ) -> WeatherSnapshot:
        try:
            main = current["main"]
            weather = current["weather"][0]
            wind = current["wind"]
            timezone = ZoneInfo(request.timezone)
            observed_at = datetime.fromtimestamp(int(current["dt"]), tz=UTC).astimezone(
                timezone
            )
            days: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for item in forecast_payload["list"]:
                days[str(item["dt_txt"])[:10]].append(item)
            today = observed_at.date().isoformat()
            forecast = tuple(
                ForecastDay(
                    date=date,
                    weather_code=openweather_to_wmo(int(values[0]["weather"][0]["id"])),
                    temperature_min=min(
                        float(item["main"]["temp_min"]) for item in values
                    ),
                    temperature_max=max(
                        float(item["main"]["temp_max"]) for item in values
                    ),
                )
                for date, values in list(days.items())
                if date > today
            )
            if not forecast:
                raise KeyError("forecast")
            return WeatherSnapshot(
                location=str(current.get("name") or request.city or "Meteo"),
                observed_at=observed_at.isoformat(),
                weather_code=openweather_to_wmo(int(weather["id"])),
                description=str(weather["description"]).capitalize(),
                temperature=float(main["temp"]),
                humidity=int(main["humidity"]),
                wind_speed=float(wind["speed"]),
                pressure=float(main["pressure"]),
                forecast=forecast,
                temperature_unit=(
                    "°F"
                    if request.units == "imperial"
                    else "K" if request.units == "standard" else "°C"
                ),
                wind_unit="mph" if request.units == "imperial" else "m/s",
                language=request.language,
            )
        except (IndexError, KeyError, TypeError, ValueError) as error:
            raise WeatherProviderError(
                "OpenWeatherMap response has an invalid schema."
            ) from error
