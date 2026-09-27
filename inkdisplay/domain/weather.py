"""Provider-independent weather value objects."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ForecastDay:
    date: str
    weather_code: int
    temperature_min: float
    temperature_max: float


@dataclass(frozen=True)
class WeatherSnapshot:
    location: str
    observed_at: str
    weather_code: int
    description: str
    temperature: float
    humidity: int
    wind_speed: float
    pressure: float
    forecast: tuple[ForecastDay, ...]
    stale: bool = False
    temperature_unit: str = "°C"
    wind_unit: str = "km/h"
    language: str = "it"
    feels_like: float | None = None
    is_day: bool | None = None
    refreshed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(
        cls, values: dict[str, Any], *, stale: bool = False
    ) -> WeatherSnapshot:
        forecast = tuple(ForecastDay(**item) for item in values.get("forecast", []))
        return cls(
            location=str(values["location"]),
            observed_at=str(values["observed_at"]),
            weather_code=int(values["weather_code"]),
            description=str(values["description"]),
            temperature=float(values["temperature"]),
            humidity=int(values["humidity"]),
            wind_speed=float(values["wind_speed"]),
            pressure=float(values["pressure"]),
            forecast=forecast,
            stale=stale,
            temperature_unit=str(values.get("temperature_unit", "°C")),
            wind_unit=str(values.get("wind_unit", "km/h")),
            language=str(values.get("language", "it")),
            feels_like=(
                float(values["feels_like"])
                if values.get("feels_like") is not None
                else None
            ),
            is_day=bool(values["is_day"]) if values.get("is_day") is not None else None,
            refreshed_at=(
                str(values["refreshed_at"])
                if values.get("refreshed_at") is not None
                else None
            ),
        )
