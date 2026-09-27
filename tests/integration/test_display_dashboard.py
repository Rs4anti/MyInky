from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image

from inkdisplay.app import create_app
from inkdisplay.application.services.photo_service import PhotoService
from inkdisplay.extensions import db
from inkdisplay.infrastructure.persistence.models import PluginSettings


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
    assert client.post("/display/sleep").status_code == 302


def test_dashboard_preserves_current_preview_link(tmp_path: Path) -> None:
    app = _app(tmp_path)
    response = app.test_client().get("/")

    assert response.status_code == 200
    assert b"/api/preview" in response.data
    assert app.test_client().get("/health").json["display_mode"] == "mock"


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
