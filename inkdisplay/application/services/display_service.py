"""Display status and manual operations, separate from Flask routes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from inkdisplay.application.services.plugin_service import PluginService
from inkdisplay.extensions import db
from inkdisplay.infrastructure.display.managed_display import ManagedDisplay
from inkdisplay.infrastructure.persistence.models import (
    DisplayState,
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
    ) -> None:
        self._display = display
        self._plugin_service = plugin_service
        self._scheduler = scheduler

    def status(self) -> dict[str, Any]:
        enabled_plugins = (
            db.session.query(PluginSettings)
            .filter_by(enabled=True)
            .order_by(PluginSettings.sort_order, PluginSettings.plugin_key)
            .all()
        )
        state = db.session.get(DisplayState, 1)
        keys = [plugin.plugin_key for plugin in enabled_plugins]
        current_plugin: str | None = state.last_plugin_shown if state else None
        if current_plugin is None and keys:
            current_plugin = keys[0]
        next_plugin: str | None
        if current_plugin is not None and current_plugin in keys:
            next_plugin = keys[(keys.index(current_plugin) + 1) % len(keys)]
        else:
            next_plugin = keys[0] if keys else None

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
            "last_update_at": self._display.last_update_at,
            "last_hash": self._display.last_hash,
            "previous_hash": self._display.previous_hash,
            "new_hash": self._display.new_hash,
            "last_result": self._display.last_result,
            "last_refresh_mode": self._display.last_refresh_mode,
            "last_error": self._display.last_error,
            "current_plugin": current_plugin,
            "next_plugin": next_plugin,
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
        status = self.status()
        plugin_key = status["current_plugin"] or "clock"
        image = self._plugin_service.render_plugin(str(plugin_key))
        self._display.display(image)
        return str(plugin_key)

    def clear(self) -> None:
        self._display.clear()

    def sleep(self) -> None:
        self._display.sleep()
