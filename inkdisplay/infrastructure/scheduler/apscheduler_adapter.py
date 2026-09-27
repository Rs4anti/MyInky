"""APScheduler adapter with a process-wide file lock."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from filelock import FileLock, Timeout
from flask import Flask

from inkdisplay.application.services.plugin_service import PluginService
from inkdisplay.extensions import db
from inkdisplay.infrastructure.persistence.models import PluginSettings, Settings

logger = logging.getLogger(__name__)


class APSchedulerAdapter:
    def __init__(
        self,
        app: Flask,
        plugin_service: PluginService,
        lock_path: Path,
    ) -> None:
        self._app = app
        self._plugin_service = plugin_service
        self._scheduler = BackgroundScheduler(timezone="UTC")
        self._file_lock = FileLock(str(lock_path))
        self._lock_acquired = False
        self._configuration_signature: tuple[object, ...] | None = None

    @property
    def running(self) -> bool:
        return bool(self._scheduler.running)

    def start(self) -> bool:
        if self._scheduler.running:
            return True
        try:
            self._file_lock.acquire(timeout=0)
            self._lock_acquired = True
        except Timeout:
            logger.warning("Another MyInky scheduler process holds the scheduler lock")
            return False
        try:
            self.reconfigure()
            self._scheduler.start()
        except Exception:
            if self._lock_acquired:
                self._file_lock.release()
                self._lock_acquired = False
            raise
        logger.info("Plugin scheduler started")
        return True

    def reconfigure(self) -> None:
        if self._scheduler.running:
            self._scheduler.remove_all_jobs()
        with self._app.app_context():
            plugin_settings = (
                db.session.query(PluginSettings).filter_by(enabled=True).all()
            )
            all_plugins = (
                db.session.query(PluginSettings)
                .order_by(PluginSettings.plugin_key)
                .all()
            )
            for setting in plugin_settings:
                self._scheduler.add_job(
                    self._refresh_in_context,
                    trigger=IntervalTrigger(
                        minutes=setting.refresh_interval_minutes, timezone="UTC"
                    ),
                    args=[setting.plugin_key],
                    id=f"plugin-refresh-{setting.plugin_key}",
                    replace_existing=True,
                    max_instances=1,
                    coalesce=True,
                    next_run_time=datetime.now(UTC),
                )
            settings = db.session.get(Settings, 1)
            rotation_interval = settings.rotation_interval_minutes if settings else 10
            self._configuration_signature = (
                rotation_interval,
                settings.updated_at.isoformat() if settings else "",
                tuple(
                    (
                        plugin.plugin_key,
                        plugin.enabled,
                        plugin.sort_order,
                        plugin.refresh_interval_minutes,
                    )
                    for plugin in all_plugins
                ),
            )
            self._scheduler.add_job(
                self._rotate_in_context,
                trigger=IntervalTrigger(minutes=rotation_interval, timezone="UTC"),
                id="display-plugin-rotation",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            self._scheduler.add_job(
                self._check_configuration_in_context,
                trigger=IntervalTrigger(seconds=20, timezone="UTC"),
                id="scheduler-configuration-watch",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=True)
        if self._lock_acquired:
            self._file_lock.release()
            self._lock_acquired = False
        logger.info("Plugin scheduler stopped")

    def _refresh_in_context(self, plugin_key: str) -> None:
        self._run_in_context(lambda: self._plugin_service.refresh_plugin(plugin_key))

    def _rotate_in_context(self) -> None:
        self._run_in_context(self._plugin_service.rotate_next)

    def _check_configuration_in_context(self) -> None:
        self._run_in_context(self._reload_if_changed)

    def _reload_if_changed(self) -> None:
        plugin_settings = (
            db.session.query(PluginSettings).order_by(PluginSettings.plugin_key).all()
        )
        settings = db.session.get(Settings, 1)
        signature = (
            settings.rotation_interval_minutes if settings else 10,
            settings.updated_at.isoformat() if settings else "",
            tuple(
                (
                    plugin.plugin_key,
                    plugin.enabled,
                    plugin.sort_order,
                    plugin.refresh_interval_minutes,
                )
                for plugin in plugin_settings
            ),
        )
        if signature != self._configuration_signature:
            self.reconfigure()

    def _run_in_context(self, callback: Callable[[], object]) -> None:
        try:
            with self._app.app_context():
                callback()
        except Exception:
            logger.exception("Scheduled plugin operation failed")
        finally:
            with self._app.app_context():
                db.session.remove()
