"""Refresh and persistent cache policy for weather data."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.exc import SQLAlchemyError

from inkdisplay.domain.weather import WeatherSnapshot
from inkdisplay.extensions import db
from inkdisplay.infrastructure.persistence.models import (
    PluginSettings,
    Settings,
    WeatherCache,
)
from inkdisplay.infrastructure.security.secret_store import SecretStore
from inkdisplay.infrastructure.weather.common import WeatherProviderError
from inkdisplay.infrastructure.weather.port import WeatherProvider
from inkdisplay.infrastructure.weather.request import WeatherRequest

logger = logging.getLogger(__name__)


class WeatherUnavailable(RuntimeError):
    """Raised if the provider failed and no persisted snapshot exists."""


class WeatherService:
    def __init__(
        self,
        providers: dict[str, WeatherProvider],
        secret_store: SecretStore,
    ) -> None:
        self._providers = providers
        self._secret_store = secret_store

    def refresh(self, *, force: bool = False) -> WeatherSnapshot:
        settings = db.session.get(Settings, 1)
        if settings is None:
            raise WeatherUnavailable("Weather settings are not initialized.")
        cache = db.session.get(WeatherCache, 1)
        interval = db.session.get(PluginSettings, "weather")
        max_age = interval.refresh_interval_minutes if interval else 30
        if cache is not None and not force and not self._is_expired(cache, max_age):
            return WeatherSnapshot.from_dict(cache.payload)

        try:
            provider = self._providers[settings.weather_provider]
            api_key = (
                self._secret_store.decrypt(settings.openweather_api_key_encrypted)
                if settings.openweather_api_key_encrypted
                else None
            )
            snapshot = provider.fetch(
                WeatherRequest(
                    latitude=settings.latitude,
                    longitude=settings.longitude,
                    city=settings.city,
                    timezone=settings.weather_timezone,
                    units=settings.units,
                    language=settings.language,
                    api_key=api_key,
                )
            )
        except (WeatherProviderError, KeyError, ValueError) as error:
            logger.warning("Weather refresh failed; trying persisted cache: %s", error)
            return self._cached_or_raise(cache)

        self._save_snapshot(snapshot)
        return snapshot

    def cached(self) -> WeatherSnapshot | None:
        cache = db.session.get(WeatherCache, 1)
        if cache is None:
            return None
        interval = db.session.get(PluginSettings, "weather")
        max_age = interval.refresh_interval_minutes if interval else 30
        stale = self._is_expired(cache, max_age)
        return WeatherSnapshot.from_dict(cache.payload, stale=stale)

    @staticmethod
    def has_api_key() -> bool:
        settings = db.session.get(Settings, 1)
        return bool(settings and settings.openweather_api_key_encrypted)

    @staticmethod
    def _is_expired(cache: WeatherCache, max_age_minutes: int) -> bool:
        fetched_at = cache.fetched_at
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=UTC)
        return (datetime.now(UTC) - fetched_at).total_seconds() >= max_age_minutes * 60

    def _cached_or_raise(self, cache: WeatherCache | None) -> WeatherSnapshot:
        if cache is None:
            raise WeatherUnavailable(
                "Weather provider failed and no cached data exists."
            )
        return WeatherSnapshot.from_dict(cache.payload, stale=True)

    @staticmethod
    def _save_snapshot(snapshot: WeatherSnapshot) -> None:
        cache = db.session.get(WeatherCache, 1)
        if cache is None:
            cache = WeatherCache(id=1, payload=snapshot.to_dict())
            db.session.add(cache)
        else:
            cache.payload = snapshot.to_dict()
            cache.fetched_at = datetime.now(UTC)
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            logger.exception("Could not persist weather cache")
