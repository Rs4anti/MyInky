"""Persistent application settings and display/weather state."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from inkdisplay.extensions import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class Settings(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    rotation_interval_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10
    )
    weather_provider: Mapped[str] = mapped_column(
        String(32), nullable=False, default="open-meteo"
    )
    latitude: Mapped[float | None] = mapped_column(nullable=True)
    longitude: Mapped[float | None] = mapped_column(nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    weather_timezone: Mapped[str] = mapped_column(
        String(80), nullable=False, default="Europe/Rome"
    )
    units: Mapped[str] = mapped_column(String(16), nullable=False, default="metric")
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="it")
    openweather_api_key_encrypted: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="singleton_settings"),
        CheckConstraint("rotation_interval_minutes >= 1", name="rotation_interval"),
        CheckConstraint("units IN ('metric', 'imperial', 'standard')", name="units"),
    )


class PluginSettings(Base):
    __tablename__ = "plugin_settings"

    plugin_key: Mapped[str] = mapped_column(String(32), primary_key=True)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    refresh_interval_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )
    parameters: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        CheckConstraint(
            "refresh_interval_minutes >= 1", name="plugin_refresh_interval"
        ),
        CheckConstraint("sort_order >= 0", name="plugin_sort_order"),
    )


class DisplayState(Base):
    __tablename__ = "display_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    last_plugin_shown: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_shown_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_rotation_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    __table_args__ = (CheckConstraint("id = 1", name="singleton_display_state"),)


class WeatherCache(Base):
    __tablename__ = "weather_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    __table_args__ = (CheckConstraint("id = 1", name="singleton_weather_cache"),)
