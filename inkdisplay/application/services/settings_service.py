"""Validation and persistence for plugin and weather settings forms."""

from __future__ import annotations

from collections.abc import Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.exc import SQLAlchemyError

from inkdisplay.extensions import db
from inkdisplay.infrastructure.persistence.models import PluginSettings, Settings
from inkdisplay.infrastructure.security.secret_store import SecretStore


class SettingsValidationError(ValueError):
    """Raised when settings from a web form are invalid."""


class SettingsService:
    def __init__(self, secret_store: SecretStore) -> None:
        self._secret_store = secret_store

    def plugin_values(self) -> dict[str, object]:
        settings = self._settings()
        plugins = {
            item.plugin_key: item for item in db.session.query(PluginSettings).all()
        }
        clock_parameters = plugins["clock"].parameters
        return {
            "rotation_interval_minutes": settings.rotation_interval_minutes,
            "clock_enabled": plugins["clock"].enabled,
            "clock_refresh_interval": plugins["clock"].refresh_interval_minutes,
            "clock_time_format": clock_parameters.get("time_format", "24h"),
            "clock_show_seconds": clock_parameters.get("show_seconds", False),
            "clock_show_timezone": clock_parameters.get("show_timezone", True),
            "clock_show_weather_summary": clock_parameters.get(
                "show_weather_summary", False
            ),
            "weather_enabled": plugins["weather"].enabled,
            "weather_refresh_interval": plugins["weather"].refresh_interval_minutes,
        }

    def update_plugins(self, form: Mapping[str, str]) -> None:
        settings = self._settings()
        rotation = self._parse_interval(
            form.get("rotation_interval_minutes"), "Rotation"
        )
        clock_interval = self._parse_interval(
            form.get("clock_refresh_interval"), "Clock"
        )
        weather_interval = self._parse_interval(
            form.get("weather_refresh_interval"), "Weather"
        )
        settings.rotation_interval_minutes = rotation
        self._update_plugin("clock", "clock_enabled" in form, clock_interval, 0)
        self._update_plugin("weather", "weather_enabled" in form, weather_interval, 1)
        clock = db.session.get(PluginSettings, "clock")
        if clock is not None:
            time_format = form.get("clock_time_format", "24h").strip().lower()
            if time_format not in {"12h", "24h"}:
                raise SettingsValidationError("Seleziona un formato orario valido.")
            clock.parameters = {
                **clock.parameters,
                "time_format": time_format,
                "show_seconds": "clock_show_seconds" in form,
                "show_timezone": "clock_show_timezone" in form,
                "show_weather_summary": "clock_show_weather_summary" in form,
            }
        self._commit()

    def weather_values(self) -> dict[str, object]:
        settings = self._settings()
        plugin = db.session.get(PluginSettings, "weather")
        parameters = plugin.parameters if plugin is not None else {}
        return {
            "provider": settings.weather_provider,
            "latitude": settings.latitude,
            "longitude": settings.longitude,
            "city": settings.city or "",
            "timezone": settings.weather_timezone,
            "units": settings.units,
            "language": settings.language,
            "api_key_configured": bool(settings.openweather_api_key_encrypted),
            "show_humidity": parameters.get("show_humidity", True),
            "show_wind": parameters.get("show_wind", True),
            "show_pressure": parameters.get("show_pressure", True),
            "show_feels_like": parameters.get("show_feels_like", False),
            "show_forecast": parameters.get("show_forecast", True),
        }

    def update_weather(self, form: Mapping[str, str]) -> None:
        settings = self._settings()
        provider = form.get("provider", "open-meteo").strip().lower()
        if provider not in {"open-meteo", "openweathermap"}:
            raise SettingsValidationError("Seleziona un provider meteo valido.")

        latitude = self._parse_optional_float(form.get("latitude"), "Latitudine")
        longitude = self._parse_optional_float(form.get("longitude"), "Longitudine")
        if (latitude is None) != (longitude is None):
            raise SettingsValidationError(
                "Inserisci entrambe le coordinate oppure usa il nome della località."
            )
        if latitude is not None and not -90 <= latitude <= 90:
            raise SettingsValidationError("La latitudine deve essere tra -90 e 90.")
        if longitude is not None and not -180 <= longitude <= 180:
            raise SettingsValidationError("La longitudine deve essere tra -180 e 180.")

        timezone_name = form.get("timezone", "Europe/Rome").strip()
        try:
            ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise SettingsValidationError("La timezone IANA non è valida.") from error

        units = form.get("units", "metric").strip().lower()
        if units not in {"metric", "imperial", "standard"}:
            raise SettingsValidationError("Seleziona un'unità di misura valida.")
        language = form.get("language", "it").strip().lower()
        if not 2 <= len(language) <= 10 or not language.replace("-", "").isalpha():
            raise SettingsValidationError("Il codice lingua non è valido.")

        city = form.get("city", "").strip() or None
        if latitude is None and city is None:
            raise SettingsValidationError(
                "Inserisci le coordinate oppure il nome della località."
            )

        settings.weather_provider = provider
        settings.latitude = latitude
        settings.longitude = longitude
        settings.city = city
        settings.weather_timezone = timezone_name
        settings.units = units
        settings.language = language
        api_key = form.get("openweather_api_key", "").strip()
        if "clear_api_key" in form:
            settings.openweather_api_key_encrypted = None
        elif api_key:
            settings.openweather_api_key_encrypted = self._secret_store.encrypt(api_key)
        weather_plugin = db.session.get(PluginSettings, "weather")
        if weather_plugin is None:
            weather_plugin = PluginSettings(plugin_key="weather")
            db.session.add(weather_plugin)
        parameters = dict(weather_plugin.parameters or {})
        for option in (
            "show_humidity",
            "show_wind",
            "show_pressure",
            "show_feels_like",
            "show_forecast",
        ):
            parameters[option] = option in form
        weather_plugin.parameters = parameters
        self._commit()

    @staticmethod
    def _settings() -> Settings:
        settings = db.session.get(Settings, 1)
        if settings is None:
            raise SettingsValidationError("Impostazioni non inizializzate.")
        return settings

    @staticmethod
    def _parse_interval(value: str | None, label: str) -> int:
        try:
            interval = int(value or "")
        except ValueError as error:
            raise SettingsValidationError(
                f"{label}: inserisci un intervallo in minuti valido."
            ) from error
        if interval < 1:
            raise SettingsValidationError(f"{label}: l'intervallo minimo è 1 minuto.")
        return interval

    @staticmethod
    def _parse_optional_float(value: str | None, label: str) -> float | None:
        if value is None or not value.strip():
            return None
        try:
            return float(value)
        except ValueError as error:
            raise SettingsValidationError(
                f"{label}: valore numerico non valido."
            ) from error

    @staticmethod
    def _update_plugin(
        plugin_key: str, enabled: bool, interval: int, sort_order: int
    ) -> None:
        plugin = db.session.get(PluginSettings, plugin_key)
        if plugin is None:
            plugin = PluginSettings(plugin_key=plugin_key)
            db.session.add(plugin)
        plugin.enabled = enabled
        plugin.refresh_interval_minutes = interval
        plugin.sort_order = sort_order

    @staticmethod
    def _commit() -> None:
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            raise
