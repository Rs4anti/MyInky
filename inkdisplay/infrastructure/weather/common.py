"""Shared HTTP and WMO-code helpers."""

from __future__ import annotations

from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class WeatherProviderError(RuntimeError):
    """Raised when a provider response is unavailable or invalid."""


def create_http_session() -> requests.Session:
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        backoff_factor=0.25,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": "MyInky/0.2 (Raspberry Pi local display)"})
    return session


def get_json(
    session: requests.Session,
    url: str,
    *,
    params: dict[str, str | int | float],
) -> dict[str, Any]:
    try:
        response = session.get(url, params=params, timeout=(3.05, 8.0))
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as error:
        raise WeatherProviderError("Weather provider request failed.") from error
    if not isinstance(payload, dict):
        raise WeatherProviderError("Weather provider returned invalid JSON data.")
    if "cod" in payload and str(payload["cod"]) not in {"200", "0"}:
        raise WeatherProviderError("Weather provider rejected the configured request.")
    return payload


def geocode_city(
    session: requests.Session, city: str, language: str = "it"
) -> tuple[float, float, str]:
    payload = get_json(
        session,
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1, "language": language, "format": "json"},
    )
    results = payload.get("results")
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        raise WeatherProviderError("The configured city could not be found.")
    result = results[0]
    try:
        return (
            float(result["latitude"]),
            float(result["longitude"]),
            str(result["name"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise WeatherProviderError("Geocoding response is incomplete.") from error


def weather_description(code: int, language: str = "it") -> str:
    language_key = language.lower().split("-", maxsplit=1)[0]
    labels = WEATHER_LABELS.get(language_key, WEATHER_LABELS["it"])
    if code == 0:
        return labels["clear"]
    if code in {1, 2}:
        return labels["partly_cloudy"]
    if code == 3:
        return labels["cloudy"]
    if code in {45, 48}:
        return labels["fog"]
    if code in {51, 53, 55, 56, 57}:
        return labels["drizzle"]
    if code in {61, 63, 65, 66, 67, 80, 81, 82}:
        return labels["rain"]
    if code in {71, 73, 75, 77, 85, 86}:
        return labels["snow"]
    if code in {95, 96, 99}:
        return labels["thunderstorm"]
    return labels["variable"]


WEATHER_LABELS = {
    "it": {
        "clear": "Sereno",
        "partly_cloudy": "Poco nuvoloso",
        "cloudy": "Coperto",
        "fog": "Nebbia",
        "drizzle": "Pioviggine",
        "rain": "Pioggia",
        "snow": "Neve",
        "thunderstorm": "Temporale",
        "variable": "Variabile",
    },
    "en": {
        "clear": "Clear",
        "partly_cloudy": "Partly cloudy",
        "cloudy": "Overcast",
        "fog": "Fog",
        "drizzle": "Drizzle",
        "rain": "Rain",
        "snow": "Snow",
        "thunderstorm": "Thunderstorm",
        "variable": "Variable",
    },
    "es": {
        "clear": "Despejado",
        "partly_cloudy": "Parcialmente nublado",
        "cloudy": "Nublado",
        "fog": "Niebla",
        "drizzle": "Llovizna",
        "rain": "Lluvia",
        "snow": "Nieve",
        "thunderstorm": "Tormenta",
        "variable": "Variable",
    },
    "fr": {
        "clear": "Dégagé",
        "partly_cloudy": "Partiellement nuageux",
        "cloudy": "Couvert",
        "fog": "Brouillard",
        "drizzle": "Bruine",
        "rain": "Pluie",
        "snow": "Neige",
        "thunderstorm": "Orage",
        "variable": "Variable",
    },
    "de": {
        "clear": "Klar",
        "partly_cloudy": "Teilweise bewölkt",
        "cloudy": "Bedeckt",
        "fog": "Nebel",
        "drizzle": "Nieselregen",
        "rain": "Regen",
        "snow": "Schnee",
        "thunderstorm": "Gewitter",
        "variable": "Wechselhaft",
    },
}


def openweather_to_wmo(code: int) -> int:
    if code == 800:
        return 0
    if code == 801:
        return 1
    if code == 802:
        return 2
    if code in {803, 804}:
        return 3
    if 200 <= code < 300:
        return 95
    if 300 <= code < 400:
        return 51
    if 500 <= code < 600:
        return 61
    if 600 <= code < 700:
        return 71
    if 700 <= code < 800:
        return 45
    return 3
