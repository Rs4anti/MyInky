from pathlib import Path

from inkdisplay.app import create_app
from inkdisplay.extensions import db
from inkdisplay.infrastructure.persistence.models import (
    DisplayState,
    PluginSettings,
    Settings,
)
from inkdisplay.infrastructure.scheduler.apscheduler_adapter import APSchedulerAdapter


def test_plugin_rotation_persists_last_plugin(tmp_path: Path) -> None:
    app = create_app({"TESTING": True, "DATA_DIR": tmp_path, "SECRET_KEY": "test"})

    with app.app_context():
        photo = db.session.get(PluginSettings, "photo")
        photo.enabled = True
        db.session.commit()
        service = app.extensions["inkdisplay.plugin_service"]

        assert service.rotate_next() == "clock"
        assert service.rotate_next() == "photo"
        assert db.session.get(DisplayState, 1).last_plugin_shown == "photo"


def test_scheduler_keeps_refresh_and_rotation_intervals_separate(
    tmp_path: Path,
) -> None:
    app = create_app({"TESTING": True, "DATA_DIR": tmp_path, "SECRET_KEY": "test"})
    with app.app_context():
        db.session.get(PluginSettings, "weather").enabled = True
        db.session.get(PluginSettings, "weather").refresh_interval_minutes = 30
        db.session.get(PluginSettings, "clock").refresh_interval_minutes = 1
        db.session.get(Settings, 1).rotation_interval_minutes = 10
        db.session.commit()
    scheduler: APSchedulerAdapter = app.extensions["inkdisplay.scheduler"]

    assert scheduler.start() is True
    try:
        jobs = scheduler._scheduler.get_jobs()
        intervals = {job.id: job.trigger.interval.total_seconds() for job in jobs}
        assert intervals["plugin-refresh-clock"] == 60
        assert intervals["plugin-refresh-weather"] == 1800
        assert intervals["display-plugin-rotation"] == 600

        with app.app_context():
            db.session.get(PluginSettings, "clock").refresh_interval_minutes = 2
            db.session.get(Settings, 1).rotation_interval_minutes = 3
            db.session.commit()
            scheduler._reload_if_changed()
        refreshed = {
            job.id: job.trigger.interval.total_seconds()
            for job in scheduler._scheduler.get_jobs()
        }
        assert refreshed["plugin-refresh-clock"] == 120
        assert refreshed["display-plugin-rotation"] == 180
        assert "scheduler-configuration-watch" in refreshed

        duplicate = APSchedulerAdapter(
            app,
            app.extensions["inkdisplay.plugin_service"],
            tmp_path / "scheduler.lock",
        )
        assert duplicate.start() is False
    finally:
        scheduler.shutdown()
