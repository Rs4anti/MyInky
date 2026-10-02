from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image

from inkdisplay.app import create_app
from inkdisplay.application.services.photo_service import PhotoService
from inkdisplay.extensions import db
from inkdisplay.infrastructure.persistence.models import DisplayState, PluginSettings


def _app(data_dir: Path, **config):
    return create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "DATA_DIR": data_dir,
            "SECRET_KEY": "dashboard-test",
            **config,
        }
    )


def _png_bytes(color: str) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (32, 24), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def test_dashboard_navigation_photo_stats_and_disabled_badge(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with app.app_context():
        service = PhotoService(tmp_path)
        first = service.upload(
            BytesIO(_png_bytes("black")),
            original_name="first.png",
            mime_type="image/png",
            caption="Prima",
        )
        second = service.upload(
            BytesIO(_png_bytes("white")),
            original_name="second.png",
            mime_type="image/png",
        )
        second.enabled = False
        settings = db.session.get(PluginSettings, "photo")
        settings.parameters = {
            **settings.parameters,
            "sequence_mode": "random",
            "last_photo_id": first.id,
        }
        db.session.commit()

    client = app.test_client()
    dashboard = client.get("/")
    for link in (
        b'href="/"',
        b'href="/settings/plugins"',
        b'href="/settings/weather"',
        b'href="/photos"',
        b'href="/photos/upload"',
        b'href="/display"',
    ):
        assert link in dashboard.data
    assert b"2" in dashboard.data
    assert b"1" in dashboard.data
    assert b"casuale" in dashboard.data
    assert b"Prima" in dashboard.data
    assert b"Plugin disattivato" in dashboard.data

    app.test_client().post(
        "/photos",
        data={
            "plugin_enabled": "on",
            "fit_mode": "contain",
            "dithering": "none",
            "sequence_mode": "random",
            "contrast": "1.2",
            "sharpness": "1",
            "max_upload_mb": "10",
        },
    )
    enabled_dashboard = client.get("/")
    assert b'href="/photos"' in enabled_dashboard.data
    assert b"Plugin disattivato" not in enabled_dashboard.data


def test_waveshare_config_falls_back_on_windows_and_display_controls_work(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path, DISPLAY_MODE="waveshare")
    client = app.test_client()

    assert app.config["DISPLAY_MODE"] == "mock"
    assert client.get("/display").status_code == 200
    assert b"MockDisplay" in client.get("/display").data
    assert client.post("/display/clear").status_code == 302
    assert client.post("/display/refresh").status_code == 302
    assert client.post("/display/next").status_code == 302
    assert client.post("/display/sleep").status_code == 302


def test_dashboard_preserves_current_preview_link(tmp_path: Path) -> None:
    app = _app(tmp_path)
    response = app.test_client().get("/")

    assert response.status_code == 200
    assert b"/api/preview" in response.data
    assert app.test_client().get("/health").json["display_mode"] == "mock"


def test_dashboard_preview_read_does_not_redraw_clock_or_change_current_plugin(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path)
    with app.app_context():
        state = db.session.get(DisplayState, 1)
        state.last_plugin_shown = "weather"
        db.session.get(PluginSettings, "weather").enabled = True
        db.session.commit()

    display = app.extensions["inkdisplay.display"]
    response = app.test_client().get("/api/preview")

    assert response.status_code == 200
    assert display.last_result == "not-updated"
    with app.app_context():
        assert db.session.get(DisplayState, 1).last_plugin_shown == "weather"


def test_dashboard_preview_serves_last_successful_frame_without_cache(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path)
    with app.app_context():
        state = db.session.get(DisplayState, 1)
        state.current_plugin = "weather"
        db.session.get(PluginSettings, "weather").enabled = True
        db.session.commit()
        service = app.extensions["inkdisplay.plugin_service"]
        assert service.redraw_current() == "weather"

    display = app.extensions["inkdisplay.display"]
    previous_result = display.last_result
    expected_frame = (tmp_path / "previews" / "current.png").read_bytes()
    client = app.test_client()
    preview = client.get("/api/preview")
    dashboard = client.get("/")

    assert preview.data == expected_frame
    assert preview.headers["Cache-Control"].startswith("no-store")
    assert display.last_result == previous_result
    assert b"Plugin pianificato" in dashboard.data
    assert b"Plugin realmente mostrato" in dashboard.data
    assert (
        b"weather-preview" in dashboard.data or b"Contenuto: weather" in dashboard.data
    )
    assert b"v=" in dashboard.data


def test_clock_plugin_writes_large_clock_preview(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    app = _app(tmp_path)
    fixed_time = datetime(2026, 10, 2, 18, 54, tzinfo=ZoneInfo("Europe/Rome"))

    with app.app_context():
        state = db.session.get(DisplayState, 1)
        state.current_plugin = "clock"
        db.session.get(PluginSettings, "clock").enabled = True
        db.session.commit()

        service = app.extensions["inkdisplay.plugin_service"]
        clock_plugin = service._plugins["clock"]
        renderer = clock_plugin._renderer
        render_clock = renderer.render_clock
        monkeypatch.setattr(
            renderer,
            "render_clock",
            lambda **kwargs: render_clock(fixed_time, **kwargs),
        )
        with caplog.at_level(
            logging.DEBUG, logger="inkdisplay.application.services.plugin_service"
        ):
            service.refresh_plugin("clock")

    clock_preview_path = tmp_path / "previews" / "clock-preview.png"
    current_preview_path = tmp_path / "previews" / "current.png"
    assert clock_preview_path.is_file()
    assert current_preview_path.is_file()
    for preview_path in (clock_preview_path, current_preview_path):
        with Image.open(preview_path) as image:
            assert image.size == (400, 300)
            assert image.mode == "1"
            time_ink = Image.eval(
                image.crop((12, 10, 388, 190)).convert("L"),
                lambda value: 255 - value,
            ).getbbox()
            assert time_ink is not None
            assert time_ink[2] - time_ink[0] >= 300
            assert time_ink[3] - time_ink[1] >= 100
    assert "clock-preview.png" in caplog.text
    assert "png_sha256=" in caplog.text


def test_dashboard_formats_persisted_times_in_configured_timezone(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path, TIMEZONE="Europe/Rome")
    with app.app_context():
        state = db.session.get(DisplayState, 1)
        state.current_plugin = "weather"
        state.current_plugin_started_at = datetime(2026, 10, 1, 18, 23, 20, tzinfo=UTC)
        state.current_plugin_expires_at = datetime(2026, 10, 1, 18, 33, 20, tzinfo=UTC)
        state.last_display_success_at = datetime(2026, 10, 1, 18, 23, 20, tzinfo=UTC)
        state.last_displayed_plugin = "weather"
        state.last_display_result = "updated"
        db.session.get(PluginSettings, "weather").enabled = True
        db.session.commit()

    response = app.test_client().get("/")

    assert b"01/10/2026 20:23:20" in response.data
    assert b"2026-10-01T18:23:20" not in response.data


def test_manual_refresh_keeps_dwell_deadline_and_next_advances_once(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path)
    start = datetime.now(UTC)
    expires = start + timedelta(minutes=10)
    with app.app_context():
        state = db.session.get(DisplayState, 1)
        state.current_plugin = "weather"
        state.current_plugin_started_at = start
        state.current_plugin_expires_at = expires
        state.last_rotation_at = start
        db.session.get(PluginSettings, "weather").enabled = True
        db.session.commit()

    client = app.test_client()
    assert client.post("/display/refresh").status_code == 302
    with app.app_context():
        state = db.session.get(DisplayState, 1)
        assert state.current_plugin == "weather"
        assert state.current_plugin_expires_at.replace(tzinfo=UTC) == expires

    assert client.post("/display/next").status_code == 302
    with app.app_context():
        state = db.session.get(DisplayState, 1)
        assert state.current_plugin == "clock"
        assert state.last_rotation_at is not None
        assert state.current_plugin_expires_at is not None
        assert (
            state.current_plugin_expires_at.replace(tzinfo=UTC)
            - state.current_plugin_started_at.replace(tzinfo=UTC)
        ) == timedelta(minutes=10)


def test_clear_preserves_planned_plugin_and_records_blank_frame(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with app.app_context():
        state = db.session.get(DisplayState, 1)
        state.current_plugin = "weather"
        state.current_plugin_started_at = datetime.now(UTC)
        state.current_plugin_expires_at = datetime.now(UTC) + timedelta(minutes=10)
        db.session.get(PluginSettings, "weather").enabled = True
        db.session.commit()
        assert app.extensions["inkdisplay.plugin_service"].redraw_current() == "weather"

    assert app.test_client().post("/display/clear").status_code == 302
    with app.app_context():
        state = db.session.get(DisplayState, 1)
        assert state.current_plugin == "weather"
        assert state.last_displayed_plugin is None
        assert state.last_display_result == "cleared"
        frame = Image.open(tmp_path / "previews" / "current.png").convert("L")
        assert frame.getextrema() == (255, 255)


def test_shared_navigation_is_present_on_all_feature_pages(tmp_path: Path) -> None:
    client = _app(tmp_path).test_client()
    paths = (
        "/",
        "/settings/plugins",
        "/settings/weather",
        "/photos",
        "/photos/upload",
        "/display",
    )
    required_links = (
        b'href="/"',
        b'href="/settings/plugins"',
        b'href="/settings/weather"',
        b'href="/photos"',
        b'href="/photos/upload"',
        b'href="/display"',
    )

    for path in paths:
        response = client.get(path)
        assert response.status_code == 200
        for link in required_links:
            assert link in response.data
