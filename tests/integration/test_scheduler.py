import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from PIL import Image

from inkdisplay.app import create_app
from inkdisplay.domain.weather import ForecastDay, WeatherSnapshot
from inkdisplay.extensions import db
from inkdisplay.infrastructure.persistence.models import (
    DisplayState,
    PluginSettings,
    Settings,
    WeatherCache,
)
from inkdisplay.infrastructure.persistence.photo_models import Photo
from inkdisplay.infrastructure.scheduler.apscheduler_adapter import APSchedulerAdapter


def test_plugin_rotation_persists_last_plugin(tmp_path: Path) -> None:
    app = create_app({"TESTING": True, "DATA_DIR": tmp_path, "SECRET_KEY": "test"})

    with app.app_context():
        photo = db.session.get(PluginSettings, "photo")
        photo.enabled = True
        db.session.add(
            Photo(
                filename="available-photo.jpg",
                original_name="available-photo.jpg",
                width=32,
                height=24,
            )
        )
        db.session.commit()
        service = app.extensions["inkdisplay.plugin_service"]

        assert service.rotate_next() == "clock"
        assert service.rotate_next() == "photo"
        assert db.session.get(DisplayState, 1).last_plugin_shown == "photo"


def test_weather_remains_current_until_rotation_expiry_with_fake_clock(
    tmp_path: Path,
) -> None:
    app = create_app({"TESTING": True, "DATA_DIR": tmp_path, "SECRET_KEY": "test"})
    start = datetime(2026, 10, 1, 18, tzinfo=UTC)
    clock = [start]
    with app.app_context():
        db.session.get(PluginSettings, "weather").enabled = True
        state = db.session.get(DisplayState, 1)
        state.current_plugin = "weather"
        state.last_plugin_shown = "weather"
        state.current_plugin_started_at = start
        state.current_plugin_expires_at = start + timedelta(minutes=10)
        state.last_rotation_at = start
        state.last_shown_at = start
        db.session.commit()
        service = app.extensions["inkdisplay.plugin_service"]
        service._clock = lambda: clock[0]

        assert service.ensure_current() == "weather"
        clock[0] = start + timedelta(seconds=10)
        assert service.ensure_current() == "weather"
        state = db.session.get(DisplayState, 1)
        assert state.current_plugin == "weather"
        assert state.current_plugin_expires_at.replace(tzinfo=UTC) == start + timedelta(
            minutes=10
        )

        clock[0] = start + timedelta(minutes=10)
        assert service.ensure_current() == "clock"
        assert service.ensure_current() == "clock"
        state = db.session.get(DisplayState, 1)
        assert state.current_plugin == "clock"
        assert state.last_rotation_at.replace(tzinfo=UTC) == start + timedelta(
            minutes=10
        )


def test_content_refresh_does_not_change_non_current_display(
    tmp_path: Path, monkeypatch
) -> None:
    app = create_app({"TESTING": True, "DATA_DIR": tmp_path, "SECRET_KEY": "test"})
    with app.app_context():
        db.session.get(PluginSettings, "weather").enabled = True
        state = db.session.get(DisplayState, 1)
        state.current_plugin = "weather"
        state.current_plugin_started_at = datetime.now(UTC)
        state.current_plugin_expires_at = datetime.now(UTC) + timedelta(minutes=10)
        db.session.commit()
        service = app.extensions["inkdisplay.plugin_service"]
        assert service.redraw_current() == "weather"
        display = app.extensions["inkdisplay.display"]
        weather_hash = display.last_hash

        service.refresh_plugin("clock")
        assert display.last_hash == weather_hash
        assert db.session.get(DisplayState, 1).last_displayed_plugin == "weather"

        state.current_plugin = "clock"
        state.current_plugin_started_at = datetime.now(UTC)
        state.current_plugin_expires_at = datetime.now(UTC) + timedelta(minutes=10)
        db.session.commit()
        assert service.redraw_current() == "clock"
        clock_hash = display.last_hash
        weather = service._plugins["weather"]
        monkeypatch.setattr(weather, "refresh_content", lambda: None)

        service.refresh_plugin("weather")
        assert display.last_hash == clock_hash
        assert db.session.get(DisplayState, 1).last_displayed_plugin == "clock"


def test_weather_refresh_updates_cache_and_preview_without_displaying_weather(
    tmp_path: Path, monkeypatch
) -> None:
    app = create_app({"TESTING": True, "DATA_DIR": tmp_path, "SECRET_KEY": "test"})
    snapshot = WeatherSnapshot(
        location="Roma",
        observed_at="2026-10-01T20:08:00+02:00",
        weather_code=0,
        description="Sereno",
        temperature=21,
        humidity=60,
        wind_speed=8,
        pressure=1018,
        forecast=(ForecastDay("2026-10-02", 2, 14, 22),),
    )

    class FixedProvider:
        name = "open-meteo"

        def fetch(self, request):
            return snapshot

    with app.app_context():
        db.session.get(PluginSettings, "weather").enabled = True
        state = db.session.get(DisplayState, 1)
        state.current_plugin = "clock"
        state.current_plugin_started_at = datetime.now(UTC)
        state.current_plugin_expires_at = datetime.now(UTC) + timedelta(minutes=10)
        db.session.commit()
        weather_service = app.extensions["inkdisplay.weather_service"]
        monkeypatch.setattr(
            weather_service, "_providers", {"open-meteo": FixedProvider()}
        )
        service = app.extensions["inkdisplay.plugin_service"]
        assert service.redraw_current() == "clock"
        display = app.extensions["inkdisplay.display"]
        clock_hash = display.last_hash

        service.refresh_plugin("weather")

        assert db.session.get(WeatherCache, 1) is not None
        assert (tmp_path / "previews" / "weather-preview.png").exists()
        assert display.last_hash == clock_hash
        assert db.session.get(DisplayState, 1).current_plugin == "clock"
        assert db.session.get(DisplayState, 1).last_displayed_plugin == "clock"


def test_next_plugin_is_distinct_when_alternatives_are_enabled(
    tmp_path: Path,
) -> None:
    app = create_app({"TESTING": True, "DATA_DIR": tmp_path, "SECRET_KEY": "test"})
    with app.app_context():
        db.session.get(PluginSettings, "weather").enabled = True
        state = db.session.get(DisplayState, 1)
        state.current_plugin = "weather"
        db.session.commit()

        status = app.extensions["inkdisplay.plugin_service"].status()

        assert status["current_plugin"] == "weather"
        assert status["next_plugin"] == "clock"
        assert state.next_plugin is None


def test_disabled_empty_photo_plugin_is_skipped_and_single_plugin_is_explained(
    tmp_path: Path,
) -> None:
    app = create_app({"TESTING": True, "DATA_DIR": tmp_path, "SECRET_KEY": "test"})
    with app.app_context():
        service = app.extensions["inkdisplay.plugin_service"]
        single = service.status()
        assert single["current_plugin"] == "clock"
        assert single["next_plugin"] == "clock"
        assert single["single_plugin"] is True

        db.session.get(PluginSettings, "weather").enabled = True
        db.session.get(PluginSettings, "photo").enabled = True
        state = db.session.get(DisplayState, 1)
        state.current_plugin = "weather"
        db.session.commit()
        multiple = service.status()

        assert multiple["current_plugin"] == "weather"
        assert multiple["next_plugin"] == "clock"
        assert multiple["single_plugin"] is False


def test_hardware_failure_does_not_claim_new_plugin_was_displayed(
    tmp_path: Path, monkeypatch
) -> None:
    app = create_app({"TESTING": True, "DATA_DIR": tmp_path, "SECRET_KEY": "test"})
    with app.app_context():
        db.session.get(PluginSettings, "weather").enabled = True
        service = app.extensions["inkdisplay.plugin_service"]
        assert service.redraw_current() == "clock"
        display = app.extensions["inkdisplay.display"]
        previous_hash = display.last_hash

        def fail_display(image: Image.Image) -> None:
            raise OSError("panel BUSY timeout")

        monkeypatch.setattr(display, "display", fail_display)

        assert service.rotate_next() is None
        state = db.session.get(DisplayState, 1)
        assert state.current_plugin == "clock"
        assert state.last_displayed_plugin == "clock"
        assert state.last_displayed_hash == previous_hash
        assert state.last_display_result == "error"
        assert state.last_display_attempt_plugin == "weather"


def test_plugin_change_forces_full_even_when_frame_is_unchanged(
    tmp_path: Path,
) -> None:
    app = create_app({"TESTING": True, "DATA_DIR": tmp_path, "SECRET_KEY": "test"})
    with app.app_context():
        db.session.get(PluginSettings, "weather").enabled = True
        service = app.extensions["inkdisplay.plugin_service"]
        frame = Image.new("1", (400, 300), color=255)

        class SameFramePlugin:
            key = "weather"

            def refresh_content(self) -> None:
                return None

            def render(self) -> Image.Image:
                return frame.copy()

        service._plugins["clock"] = SameFramePlugin()
        service._plugins["weather"] = SameFramePlugin()
        assert service.redraw_current() == "clock"
        successful_at = db.session.get(DisplayState, 1).last_display_success_at
        display = app.extensions["inkdisplay.display"]
        frame_hash = display.last_hash

        assert service.next_plugin() == "weather"
        state = db.session.get(DisplayState, 1)
        assert state.current_plugin == "weather"
        assert state.last_displayed_plugin == "weather"
        assert state.last_displayed_hash == frame_hash
        assert state.last_display_result == "updated"
        assert state.last_display_success_at != successful_at
        assert display.last_refresh_mode == "full"


def test_scheduler_keeps_refresh_and_rotation_intervals_separate(
    tmp_path: Path, monkeypatch
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
        assert (tmp_path / "previews" / "clock-preview.png").is_file()
        jobs = scheduler._scheduler.get_jobs()
        intervals = {job.id: job.trigger.interval.total_seconds() for job in jobs}
        assert intervals["plugin-refresh-clock"] == 60
        assert intervals["plugin-refresh-weather"] == 1800
        assert intervals["display-plugin-rotation"] == 600
        rotation_job = scheduler._scheduler.get_job("display-plugin-rotation")
        first_rotation_run = rotation_job.next_run_time
        scheduler.reconfigure()
        assert (
            scheduler._scheduler.get_job("display-plugin-rotation").next_run_time
            == first_rotation_run
        )
        assert len(scheduler._scheduler.get_jobs()) == 4
        monkeypatch.setattr(scheduler._plugin_service, "rotate_next", lambda: None)
        scheduler._rotate_in_context()
        assert (
            scheduler._scheduler.get_job("display-plugin-rotation").next_run_time
            == first_rotation_run
        )

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


def test_scheduler_starts_and_uses_alternate_when_clock_render_fails(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    app = create_app({"TESTING": True, "DATA_DIR": tmp_path, "SECRET_KEY": "test"})
    with app.app_context():
        db.session.get(PluginSettings, "weather").enabled = True
        state = db.session.get(DisplayState, 1)
        state.current_plugin = "clock"
        state.current_plugin_started_at = datetime.now(UTC)
        state.current_plugin_expires_at = datetime.now(UTC) + timedelta(minutes=10)
        db.session.commit()

        service = app.extensions["inkdisplay.plugin_service"]
        clock_plugin = service._plugins["clock"]

        def fail_render(**kwargs):
            raise RuntimeError("simulated ClockRenderer failure")

        monkeypatch.setattr(clock_plugin._renderer, "render_clock", fail_render)

        class AlternatePlugin:
            def refresh_content(self) -> None:
                return None

            def render(self) -> Image.Image:
                image = Image.new("1", (400, 300), color=255)
                image.putpixel((10, 10), 0)
                return image

        service._plugins["weather"] = AlternatePlugin()
        scheduler = app.extensions["inkdisplay.scheduler"]

    with caplog.at_level(logging.ERROR):
        assert scheduler.start() is True
    try:
        assert scheduler.running
        assert "Plugin rendering failed plugin=clock" in caplog.text
        assert "simulated ClockRenderer failure" in caplog.text
        with app.app_context():
            state = db.session.get(DisplayState, 1)
            assert state.last_displayed_plugin == "weather"
            assert state.last_display_result in {"updated", "skipped-unchanged"}
    finally:
        scheduler.shutdown()


def test_scheduler_start_preserves_last_frame_when_clock_is_only_plugin(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    app = create_app({"TESTING": True, "DATA_DIR": tmp_path, "SECRET_KEY": "test"})
    with app.app_context():
        service = app.extensions["inkdisplay.plugin_service"]
        assert service.redraw_current() == "clock"
        display = app.extensions["inkdisplay.display"]
        previous_hash = display.last_hash
        current_path = tmp_path / "previews" / "current.png"
        previous_png = current_path.read_bytes()
        clock_plugin = service._plugins["clock"]
        clock_plugin._image = None

        def fail_render(**kwargs):
            raise RuntimeError("simulated ClockRenderer failure")

        monkeypatch.setattr(clock_plugin._renderer, "render_clock", fail_render)
        scheduler = app.extensions["inkdisplay.scheduler"]

    with caplog.at_level(logging.ERROR):
        assert scheduler.start() is True
    try:
        assert scheduler.running
        assert "simulated ClockRenderer failure" in caplog.text
        with app.app_context():
            state = db.session.get(DisplayState, 1)
            assert state.last_display_result == "error"
            assert "rendering failed" in state.last_display_error
            assert state.last_displayed_hash == previous_hash
            assert state.last_displayed_plugin == "clock"
        assert display.last_hash == previous_hash
        assert current_path.read_bytes() == previous_png
    finally:
        scheduler.shutdown()
