"""Plugin refresh and sequential display rotation use cases."""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from PIL import Image

from inkdisplay.application.plugins.contracts import VisualPlugin
from inkdisplay.extensions import db
from inkdisplay.infrastructure.display.port import DisplayPort
from inkdisplay.infrastructure.persistence.models import (
    DisplayState,
    PluginSettings,
    Settings,
)
from inkdisplay.infrastructure.persistence.photo_models import Photo
from inkdisplay.presentation.rendering.photo_renderer import PhotoRenderer

logger = logging.getLogger(__name__)


class PluginService:
    def __init__(
        self,
        plugins: dict[str, VisualPlugin],
        display: DisplayPort,
        preview_path: Path | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._plugins = plugins
        self._display = display
        self._preview_path = preview_path
        self._clock = clock or (lambda: datetime.now(UTC))
        self._rotation_lock = threading.Lock()

    def refresh_plugin(self, plugin_key: str) -> None:
        plugin = self._plugins.get(plugin_key)
        if plugin is None:
            raise ValueError(f"Unknown visual plugin: {plugin_key}")
        plugin.refresh_content()
        now = self._now()
        state = self._state()
        refreshes = dict(state.last_content_refresh_at)
        refreshes[plugin_key] = now.isoformat()
        state.last_content_refresh_at = refreshes
        db.session.commit()
        logger.info("content_refresh plugin=%s", plugin_key)

        current_plugin = self._current_plugin(state)
        if plugin_key == "photo" and plugin_key != current_plugin:
            logger.info("display_skip plugin=%s reason=not-current", plugin_key)
            return
        image = plugin.render()
        self._save_plugin_preview(plugin_key, image)
        if plugin_key == current_plugin:
            self._apply(plugin_key, image, rotation=False)
            logger.info("display_redraw plugin=%s", plugin_key)
        else:
            logger.info("display_skip plugin=%s reason=not-current", plugin_key)

    def render_plugin(self, plugin_key: str) -> Image.Image:
        plugin = self._plugins.get(plugin_key)
        if plugin is None:
            raise ValueError(f"Unknown visual plugin: {plugin_key}")
        return plugin.render()

    def rotate_next(self) -> str | None:
        return self._rotate_next(manual=False)

    def next_plugin(self) -> str | None:
        return self._rotate_next(manual=True)

    def redraw_current(self) -> str | None:
        state = self._state()
        candidates = self._active_plugins()
        current = self._current_plugin(state)
        if current not in candidates:
            current = candidates[0] if candidates else None
        if current is None:
            return None
        if state.current_plugin is None and self._current_plugin(state) is not None:
            started_at = self._utc(state.last_rotation_at or state.last_shown_at)
            state.current_plugin = current
            state.current_plugin_started_at = started_at or self._now()
            state.current_plugin_expires_at = (
                state.current_plugin_started_at
                + timedelta(minutes=self._rotation_interval())
            )
            db.session.commit()
        image = self.render_plugin(current)
        if self._apply(
            current, image, rotation=state.current_plugin_started_at is None
        ):
            logger.info("display_redraw plugin=%s", current)
            return current
        return None

    def ensure_current(self) -> str | None:
        state = self._state()
        candidates = self._active_plugins()
        if not candidates:
            return None
        current = self._current_plugin(state)
        if current not in candidates:
            current = candidates[0]
            image = self.render_plugin(current)
            if self._apply(current, image, rotation=True):
                return current
            return None

        started_at = self._utc(
            state.current_plugin_started_at
            or state.last_rotation_at
            or state.last_shown_at
        )
        if state.current_plugin_started_at is None and started_at is not None:
            state.current_plugin = current
            state.current_plugin_started_at = started_at
            state.current_plugin_expires_at = started_at + timedelta(
                minutes=self._rotation_interval()
            )
            db.session.commit()
        expires_at = self._utc(state.current_plugin_expires_at)
        if expires_at is not None and expires_at <= self._now():
            return self.rotate_next()
        image = self.render_plugin(current)
        if self._apply(current, image, rotation=started_at is None):
            return current
        return None

    def status(self) -> dict[str, Any]:
        state = db.session.get(DisplayState, 1) or DisplayState(id=1)
        candidates = self._active_plugins()
        current = self._current_plugin(state)
        if current not in candidates:
            current = candidates[0] if candidates else None
        next_plugin = self._next_plugin(current, candidates)
        return {
            "current_plugin": current,
            "next_plugin": next_plugin,
            "current_plugin_started_at": state.current_plugin_started_at,
            "current_plugin_expires_at": state.current_plugin_expires_at,
            "last_rotation_at": state.last_rotation_at,
            "last_content_refresh_at": dict(state.last_content_refresh_at),
            "last_display_attempt_at": state.last_display_attempt_at,
            "last_display_attempt_plugin": state.last_display_attempt_plugin,
            "last_display_success_at": state.last_display_success_at,
            "last_displayed_plugin": state.last_displayed_plugin,
            "last_displayed_hash": state.last_displayed_hash,
            "last_display_result": state.last_display_result,
            "last_display_error": state.last_display_error,
            "display_mode": state.display_mode,
            "refresh_mode": state.refresh_mode,
            "state_consistent": state.last_displayed_plugin in (None, current),
            "single_plugin": len(candidates) == 1,
        }

    def preview_current(self) -> Image.Image:
        state = self._state()
        plugin_key = (
            state.last_displayed_plugin
            or self._current_plugin(state)
            or (self._active_plugins() or ["clock"])[0]
        )
        if plugin_key not in self._plugins:
            plugin_key = (self._active_plugins() or ["clock"])[0]
        if plugin_key == "photo":
            return PhotoRenderer.render_unavailable()
        image = self.render_plugin(plugin_key)
        self._save_plugin_preview(plugin_key, image)
        return image

    def clear_display(self) -> None:
        state = self._state()
        now = self._now()
        state.last_display_attempt_at = now
        state.last_display_attempt_plugin = self._current_plugin(state)
        db.session.commit()
        try:
            self._display.clear()
        except Exception as error:
            state = self._state()
            state.last_display_result = "error"
            state.last_display_error = str(error)
            db.session.commit()
            raise

        state = self._state()
        white_frame = Image.new("1", (400, 300), color=255)
        state.last_display_success_at = self._now()
        state.last_displayed_plugin = None
        state.last_displayed_hash = (
            getattr(self._display, "last_hash", None)
            or hashlib.sha256(white_frame.tobytes()).hexdigest()
        )
        state.last_display_result = "cleared"
        state.last_display_error = None
        state.display_mode = getattr(self._display, "mode", "unknown")
        state.refresh_mode = "full"
        self._save_current_preview(white_frame)
        db.session.commit()

    def _rotate_next(self, *, manual: bool) -> str | None:
        if not self._rotation_lock.acquire(blocking=False):
            logger.warning("Skipping plugin rotation; another update is in progress")
            return None
        try:
            candidates = self._active_plugins()
            if not candidates:
                return None

            state = self._state()
            previous = self._current_plugin(state)
            plugin_key = self._next_plugin(previous, candidates)
            if plugin_key is None:
                return None
            image = self.render_plugin(plugin_key)
            if not self._apply(plugin_key, image, rotation=True):
                return None
            if manual:
                logger.info("Manual next plugin selected: %s", plugin_key)
            else:
                logger.info("rotation from=%s to=%s", previous, plugin_key)
            return plugin_key
        except Exception:
            db.session.rollback()
            logger.exception("Display plugin rotation failed")
            return None
        finally:
            self._rotation_lock.release()

    def _apply(self, plugin_key: str, image: Image.Image, *, rotation: bool) -> bool:
        state = self._state()
        now = self._now()
        frame = image.convert("1", dither=Image.Dither.NONE)
        frame.info.update(image.info)
        image_hash = hashlib.sha256(frame.tobytes()).hexdigest()
        state.last_display_attempt_at = now
        state.last_display_attempt_plugin = plugin_key
        state.display_mode = getattr(self._display, "mode", "unknown")
        db.session.commit()

        if plugin_key == "clock":
            self._save_plugin_preview(plugin_key, frame)

        try:
            clock_render = frame.info.get("clock_render")
            if isinstance(clock_render, dict):
                display_target = getattr(
                    self._display,
                    "driver_name",
                    type(self._display).__name__,
                )
                display_mode = getattr(self._display, "mode", "unknown")
                logger.info(
                    "CLOCK_RENDER font_size=%s width=%s height=%s preview=%s "
                    "display=%s:%s frame=%sx%s hash=%s",
                    clock_render.get("font_size"),
                    clock_render.get("width"),
                    clock_render.get("height"),
                    self._preview_path,
                    display_mode,
                    display_target,
                    frame.width,
                    frame.height,
                    image_hash,
                )
            self._display.display(frame)
        except Exception as error:
            state = self._state()
            state.last_display_result = "error"
            state.last_display_error = str(error)
            db.session.commit()
            logger.exception("Display update failed plugin=%s", plugin_key)
            return False

        state = self._state()
        succeeded_at = self._now()
        display_result = getattr(self._display, "last_result", "updated")
        if display_result != "skipped-unchanged":
            state.last_display_success_at = succeeded_at
        state.last_displayed_plugin = plugin_key
        state.last_displayed_hash = (
            getattr(self._display, "last_hash", None) or image_hash
        )
        state.last_display_result = display_result
        state.last_display_error = None
        state.display_mode = getattr(self._display, "mode", "unknown")
        state.refresh_mode = getattr(self._display, "last_refresh_mode", "full")
        state.last_plugin_shown = plugin_key
        state.last_shown_at = succeeded_at
        if rotation:
            state.current_plugin = plugin_key
            state.current_plugin_started_at = succeeded_at
            state.current_plugin_expires_at = succeeded_at + timedelta(
                minutes=self._rotation_interval()
            )
            state.last_rotation_at = succeeded_at
        state.next_plugin = self._next_plugin(plugin_key, self._active_plugins())
        self._save_current_preview(frame)
        db.session.commit()
        logger.info(
            "display_success plugin=%s hash=%s result=%s",
            plugin_key,
            state.last_displayed_hash,
            state.last_display_result,
        )
        logger.info("next_rotation_at=%s", state.current_plugin_expires_at)
        return True

    def _active_plugins(self) -> list[str]:
        enabled = (
            db.session.query(PluginSettings)
            .filter_by(enabled=True)
            .order_by(PluginSettings.sort_order, PluginSettings.plugin_key)
            .all()
        )
        active = [
            item.plugin_key for item in enabled if item.plugin_key in self._plugins
        ]
        if "photo" in active:
            active_photo_count = db.session.query(Photo).filter_by(enabled=True).count()
            if active_photo_count == 0:
                active.remove("photo")
        return active

    @staticmethod
    def _next_plugin(current: str | None, candidates: list[str]) -> str | None:
        if not candidates:
            return None
        if current not in candidates:
            return candidates[0]
        return candidates[(candidates.index(current) + 1) % len(candidates)]

    @staticmethod
    def _current_plugin(state: DisplayState) -> str | None:
        return state.current_plugin or state.last_plugin_shown

    def _state(self) -> DisplayState:
        state = db.session.get(DisplayState, 1)
        if state is None:
            state = DisplayState(id=1)
            db.session.add(state)
            db.session.flush()
        return state

    def _now(self) -> datetime:
        now = self._clock()
        return now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)

    @staticmethod
    def _rotation_interval() -> int:
        settings = db.session.get(Settings, 1)
        return settings.rotation_interval_minutes if settings else 10

    @staticmethod
    def _utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return (
            value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        )

    def _save_current_preview(self, image: Image.Image) -> None:
        if self._preview_path is None:
            return
        self._save_image(self._preview_path, image)
        if isinstance(image.info.get("clock_render"), dict):
            preview_path = self._preview_path.resolve()
            generated_at = datetime.now(UTC).isoformat()
            logger.info(
                "CLOCK_RENDER current_preview=%s generated_at=%s frame=%sx%s "
                "frame_sha256=%s png_sha256=%s",
                preview_path,
                generated_at,
                image.width,
                image.height,
                hashlib.sha256(image.tobytes()).hexdigest(),
                hashlib.sha256(preview_path.read_bytes()).hexdigest(),
            )

    def _save_plugin_preview(self, plugin_key: str, image: Image.Image) -> None:
        if self._preview_path is None:
            return
        path = self._preview_path.with_name(f"{plugin_key}-preview.png")
        self._save_image(path, image)
        if plugin_key == "clock" and isinstance(
            image.info.get("clock_render"), dict
        ):
            preview_path = path.resolve()
            logger.debug(
                "CLOCK_RENDER preview=%s generated_at=%s frame_sha256=%s "
                "png_sha256=%s",
                preview_path,
                datetime.now(UTC).isoformat(),
                hashlib.sha256(image.convert("1").tobytes()).hexdigest(),
                hashlib.sha256(preview_path.read_bytes()).hexdigest(),
            )

    @staticmethod
    def _save_image(path: Path, image: Image.Image) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                suffix=".png", dir=path.parent, delete=False
            ) as file:
                temporary_path = Path(file.name)
            image.save(temporary_path, format="PNG")
            os.replace(temporary_path, path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
