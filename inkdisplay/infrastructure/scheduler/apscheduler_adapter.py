"""APScheduler adapter with a process-wide file lock."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from filelock import FileLock, Timeout
from flask import Flask

from inkdisplay.application.services.plugin_service import PluginService
from inkdisplay.extensions import db
from inkdisplay.infrastructure.persistence.models import (
    DisplayState,
    PluginSettings,
    Settings,
)

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
        with self._app.app_context():
            self._plugin_service.ensure_current()
            plugin_settings = (
                db.session.query(PluginSettings).filter_by(enabled=True).all()
            )
            all_plugins = (
                db.session.query(PluginSettings)
                .order_by(PluginSettings.plugin_key)
                .all()
            )
            desired_refresh_jobs: set[str] = set()
            for setting in plugin_settings:
                job_id = f"plugin-refresh-{setting.plugin_key}"
                desired_refresh_jobs.add(job_id)
                previous_job = self._scheduler.get_job(job_id)
                preserve_next_run = bool(
                    previous_job
                    and previous_job.trigger.interval.total_seconds()
                    == setting.refresh_interval_minutes * 60
                )
                next_run_time = (
                    previous_job.next_run_time
                    if preserve_next_run
                    else datetime.now(UTC)
                )
                logger.info(
                    "scheduler_job action=%s id=%s",
                    "replace" if previous_job else "create",
                    job_id,
                )
                self._scheduler.add_job(
                    self._refresh_in_context,
                    trigger=IntervalTrigger(
                        minutes=setting.refresh_interval_minutes, timezone="UTC"
                    ),
                    args=[setting.plugin_key],
                    id=job_id,
                    replace_existing=True,
                    max_instances=1,
                    coalesce=True,
                    next_run_time=next_run_time,
                )
            for job in self._scheduler.get_jobs():
                if (
                    job.id.startswith("plugin-refresh-")
                    and job.id not in desired_refresh_jobs
                ):
                    self._scheduler.remove_job(job.id)
                    logger.info("scheduler_job action=remove id=%s", job.id)
            settings = db.session.get(Settings, 1)
            rotation_interval = settings.rotation_interval_minutes if settings else 10
            rotation_interval_changed = bool(
                self._configuration_signature
                and self._configuration_signature[0] != rotation_interval
            )
            if rotation_interval_changed:
                state = db.session.get(DisplayState, 1)
                if state is not None and state.current_plugin is not None:
                    state.current_plugin_expires_at = datetime.now(UTC) + timedelta(
                        minutes=rotation_interval
                    )
                    db.session.commit()
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
            previous_rotation = self._scheduler.get_job("display-plugin-rotation")
            if (
                previous_rotation is not None
                and previous_rotation.trigger.interval.total_seconds()
                == rotation_interval * 60
            ):
                next_rotation = previous_rotation.next_run_time
            else:
                state = db.session.get(DisplayState, 1)
                next_rotation = self._as_utc(
                    state.current_plugin_expires_at if state else None
                )
                if next_rotation is None:
                    next_rotation = datetime.now(UTC) + timedelta(
                        minutes=rotation_interval
                    )
            logger.info(
                "scheduler_job action=%s id=display-plugin-rotation next_run=%s",
                "replace" if previous_rotation else "create",
                next_rotation,
            )
            self._scheduler.add_job(
                self._rotate_in_context,
                trigger=IntervalTrigger(minutes=rotation_interval, timezone="UTC"),
                id="display-plugin-rotation",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                next_run_time=next_rotation,
            )
            existing_watch = self._scheduler.get_job("scheduler-configuration-watch")
            self._scheduler.add_job(
                self._check_configuration_in_context,
                trigger=IntervalTrigger(seconds=20, timezone="UTC"),
                id="scheduler-configuration-watch",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            logger.info(
                "scheduler_job action=%s id=scheduler-configuration-watch",
                "replace" if existing_watch else "create",
            )

    def reschedule_rotation(self) -> None:
        if not self._scheduler.running:
            return
        with self._app.app_context():
            state = db.session.get(DisplayState, 1)
            next_run = self._as_utc(state.current_plugin_expires_at if state else None)
            job = self._scheduler.get_job("display-plugin-rotation")
            if next_run is not None and job is not None:
                job.modify(next_run_time=next_run)
                logger.info(
                    "scheduler_job action=reschedule id=%s next_run=%s",
                    job.id,
                    next_run,
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
        rotated_plugin = self._run_in_context(self._plugin_service.rotate_next)
        if rotated_plugin is not None:
            self.reschedule_rotation()

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

    def _run_in_context(self, callback: Callable[[], object]) -> object | None:
        try:
            with self._app.app_context():
                return callback()
        except Exception:
            logger.exception("Scheduled plugin operation failed")
            return None
        finally:
            with self._app.app_context():
                db.session.remove()

    @staticmethod
    def _as_utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return (
            value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        )
