"""Validated provider input data."""

from dataclasses import dataclass


@dataclass(frozen=True)
class WeatherRequest:
    latitude: float | None
    longitude: float | None
    city: str | None
    timezone: str
    units: str
    language: str
    api_key: str | None = None
