"""Display status and manual operations, separate from Flask routes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from inkdisplay.application.services.plugin_service import PluginService
from inkdisplay.extensions import db
from inkdisplay.infrastructure.display.managed_display import ManagedDisplay
from inkdisplay.infrastructure.persistence.models import (
    PluginSettings,
    WeatherCache,
)
from inkdisplay.infrastructure.persistence.photo_models import Photo
from inkdisplay.infrastructure.scheduler.apscheduler_adapter import APSchedulerAdapter


class DisplayControlService:
    def __init__(
        self,
        display: ManagedDisplay,
        plugin_service: PluginService,
        scheduler: APSchedulerAdapter,
        timezone_name: str = "Europe/Rome",
    ) -> None:
        self._display = display
        self._plugin_service = plugin_service
        self._scheduler = scheduler
        self._timezone = ZoneInfo(timezone_name)

    def status(self) -> dict[str, Any]:
        plugin_state = self._plugin_service.status()
        current_plugin = plugin_state["current_plugin"]
        next_plugin = plugin_state["next_plugin"]

        photo_plugin = db.session.get(PluginSettings, "photo")
        photo_settings = photo_plugin.parameters if photo_plugin else {}
        total_photos = db.session.query(Photo).count()
        active_photos = db.session.query(Photo).filter_by(enabled=True).count()
        last_photo_id = photo_settings.get("last_photo_id")
        last_photo = (
            db.session.get(Photo, last_photo_id)
            if isinstance(last_photo_id, int)
            else None
        )
        cache = db.session.get(WeatherCache, 1)
        refreshes = plugin_state["last_content_refresh_at"]
        expires_at = plugin_state["current_plugin_expires_at"]
        remaining_minutes = None
        if isinstance(expires_at, datetime):
            remaining_seconds = max(
                0,
                (self._as_utc(expires_at) - datetime.now(UTC)).total_seconds(),
            )
            remaining_minutes = int((remaining_seconds + 59) // 60)

        return {
            "application_status": "ok",
            "display_mode": self._display.mode,
            "display_label": (
                "HARDWARE" if self._display.mode == "waveshare" else "MOCK"
            ),
            "driver_name": self._display.driver_name,
            "fallback_reason": self._display.fallback_reason,
            "supports_partial_refresh": self._display.supports_partial_refresh,
            "supports_fast_refresh": self._display.supports_fast_refresh,
            "last_update_at": self._format_local(
                plugin_state["last_display_success_at"] or self._display.last_update_at
            ),
            "last_hash": self._display.last_hash,
            "previous_hash": self._display.previous_hash,
            "new_hash": self._display.new_hash,
            "last_result": plugin_state["last_display_result"]
            or self._display.last_result,
            "last_refresh_mode": plugin_state["refresh_mode"]
            or self._display.last_refresh_mode,
            "last_error": plugin_state["last_display_error"]
            or self._display.last_error,
            "current_plugin": current_plugin,
            "next_plugin": next_plugin,
            "last_displayed_plugin": plugin_state["last_displayed_plugin"],
            "last_displayed_hash": plugin_state["last_displayed_hash"],
            "state_consistent": plugin_state["state_consistent"],
            "single_plugin": plugin_state["single_plugin"],
            "only_plugin_message": (
                "È l'unico plugin attivo." if plugin_state["single_plugin"] else None
            ),
            "current_plugin_started_at": self._format_local(
                plugin_state["current_plugin_started_at"]
            ),
            "current_plugin_expires_at": self._format_local(expires_at),
            "next_rotation_in_minutes": remaining_minutes,
            "last_rotation_at": self._format_local(plugin_state["last_rotation_at"]),
            "last_display_attempt_at": self._format_local(
                plugin_state["last_display_attempt_at"]
            ),
            "last_display_attempt_plugin": plugin_state["last_display_attempt_plugin"],
            "last_display_success_at": self._format_local(
                plugin_state["last_display_success_at"]
            ),
            "clock_content_refresh_at": self._format_local(refreshes.get("clock")),
            "weather_content_refresh_at": self._format_local(refreshes.get("weather")),
            "scheduler_running": self._scheduler.running,
            "weather_available": cache is not None,
            "weather_updated_at": cache.fetched_at.isoformat() if cache else None,
            "photo_count": total_photos,
            "active_photo_count": active_photos,
            "photo_plugin_enabled": bool(photo_plugin and photo_plugin.enabled),
            "photo_sequence_mode": photo_settings.get("sequence_mode", "sequential"),
            "last_photo_shown": (
                last_photo.caption or last_photo.original_name if last_photo else None
            ),
            "checked_at": datetime.now(UTC).isoformat(),
        }

    def refresh_current(self) -> str:
        plugin_key = self._plugin_service.redraw_current()
        return plugin_key or ""

    def next_plugin(self) -> str | None:
        plugin_key = self._plugin_service.next_plugin()
        if plugin_key is not None:
            self._scheduler.reschedule_rotation()
        return plugin_key

    def clear(self) -> None:
        self._plugin_service.clear_display()

    def sleep(self) -> None:
        self._display.sleep()

    def _format_local(self, value: datetime | str | None) -> str | None:
        if value is None:
            return None
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
        local = self._as_utc(parsed).astimezone(self._timezone)
        return local.strftime("%d/%m/%Y %H:%M:%S")

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
