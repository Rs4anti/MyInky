"""Plugin refresh and sequential display rotation use cases."""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime

from PIL import Image

from inkdisplay.application.plugins.contracts import VisualPlugin
from inkdisplay.extensions import db
from inkdisplay.infrastructure.display.port import DisplayPort
from inkdisplay.infrastructure.persistence.models import (
    DisplayState,
    PluginSettings,
)

logger = logging.getLogger(__name__)


class PluginService:
    def __init__(
        self,
        plugins: dict[str, VisualPlugin],
        display: DisplayPort,
    ) -> None:
        self._plugins = plugins
        self._display = display
        self._rotation_lock = threading.Lock()

    def refresh_plugin(self, plugin_key: str) -> None:
        plugin = self._plugins.get(plugin_key)
        if plugin is None:
            raise ValueError(f"Unknown visual plugin: {plugin_key}")
        plugin.refresh_content()
        logger.info("Plugin content refreshed: %s", plugin_key)

    def render_plugin(self, plugin_key: str) -> Image.Image:
        plugin = self._plugins.get(plugin_key)
        if plugin is None:
            raise ValueError(f"Unknown visual plugin: {plugin_key}")
        return plugin.render()

    def rotate_next(self) -> str | None:
        if not self._rotation_lock.acquire(blocking=False):
            logger.warning("Skipping plugin rotation; another update is in progress")
            return None
        try:
            enabled = (
                db.session.query(PluginSettings)
                .filter_by(enabled=True)
                .order_by(PluginSettings.sort_order, PluginSettings.plugin_key)
                .all()
            )
            candidates = [
                item.plugin_key for item in enabled if item.plugin_key in self._plugins
            ]
            if not candidates:
                return None

            state = db.session.get(DisplayState, 1)
            previous = state.last_plugin_shown if state else None
            if previous is None or previous not in candidates:
                next_index = 0
            else:
                next_index = (candidates.index(previous) + 1) % len(candidates)
            plugin_key = candidates[next_index]
            image = self._plugins[plugin_key].render()
            self._display.display(image)

            if state is None:
                state = DisplayState(id=1)
                db.session.add(state)
            now = datetime.now(UTC)
            state.last_plugin_shown = plugin_key
            state.last_shown_at = now
            state.last_rotation_at = now
            db.session.commit()
            logger.info("Display rotated to plugin %s", plugin_key)
            return plugin_key
        except Exception:
            db.session.rollback()
            logger.exception("Display plugin rotation failed")
            return None
        finally:
            self._rotation_lock.release()
