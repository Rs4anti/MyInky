"""Interchangeable weather provider contract."""

from typing import Protocol

from inkdisplay.domain.weather import WeatherSnapshot
from inkdisplay.infrastructure.weather.request import WeatherRequest


class WeatherProvider(Protocol):
    name: str

    def fetch(self, request: WeatherRequest) -> WeatherSnapshot: ...
