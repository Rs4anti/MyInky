from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image

from inkdisplay.app import create_app
from inkdisplay.extensions import db
from inkdisplay.infrastructure.persistence.models import DisplayState, PluginSettings
from inkdisplay.infrastructure.persistence.photo_models import Photo


def _app(data_dir: Path):
    return create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "DATA_DIR": data_dir,
            "SECRET_KEY": "photo-web-test",
        }
    )


def _image_bytes(color: str) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (80, 40), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def test_photo_pages_upload_thumbnail_and_error_handling(tmp_path: Path) -> None:
    app = _app(tmp_path)
    client = app.test_client()

    assert client.get("/photos").status_code == 200
    assert client.get("/photos/upload").status_code == 200
    uploaded = client.post(
        "/photos/upload",
        data={
            "photos": [
                (BytesIO(_image_bytes("black")), "../first.png"),
                (BytesIO(_image_bytes("white")), "second.png"),
            ],
            "caption": "Album",
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert uploaded.status_code == 200
    assert b"first.png" in uploaded.data
    with app.app_context():
        records = db.session.query(Photo).order_by(Photo.sort_order).all()
        assert len(records) == 2
        assert records[0].original_name == "first.png"
        assert "/" not in records[0].filename
        assert "\\" not in records[0].filename
        photo_id = records[0].id
        original_path = tmp_path / "uploads" / records[0].filename

    thumbnail = client.get(f"/photos/{photo_id}/thumbnail")
    assert thumbnail.status_code == 200
    assert thumbnail.mimetype == "image/png"
    with Image.open(BytesIO(thumbnail.data)) as image:
        assert image.size == (400, 300)
        assert image.mode == "1"

    disabled = client.post(f"/photos/{photo_id}/toggle", data={"enabled": "0"})
    assert disabled.status_code == 302
    with app.app_context():
        assert db.session.get(Photo, photo_id).enabled is False

    removed = client.post(f"/photos/{photo_id}/delete", follow_redirects=True)
    assert removed.status_code == 200
    assert original_path.exists() is False
    with app.app_context():
        assert db.session.get(Photo, photo_id) is None

    rejected = client.post(
        "/photos/upload",
        data={"photos": (BytesIO(b"broken"), "broken.png")},
        content_type="multipart/form-data",
    )
    assert rejected.status_code == 400
    assert b"corrotto" in rejected.data


def test_photo_settings_are_applied_and_photo_rotates_after_clock(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path)
    service = app.extensions["inkdisplay.plugin_service"]
    client = app.test_client()

    response = client.post(
        "/photos",
        data={
            "plugin_enabled": "on",
            "fit_mode": "cover",
            "dithering": "atkinson",
            "sequence_mode": "sequential",
            "contrast": "1.5",
            "sharpness": "1.3",
            "max_upload_mb": "5",
        },
    )
    assert response.status_code == 302

    with app.app_context():
        plugin_settings = db.session.get(PluginSettings, "photo")
        assert plugin_settings.enabled is True
        assert plugin_settings.parameters["fit_mode"] == "cover"
        assert plugin_settings.parameters["dithering"] == "atkinson"

    assert (
        client.post(
            "/photos/upload",
            data={"photos": (BytesIO(_image_bytes("black")), "first.png")},
            content_type="multipart/form-data",
        ).status_code
        == 302
    )
    assert (
        client.post(
            "/photos/upload",
            data={"photos": (BytesIO(_image_bytes("white")), "second.png")},
            content_type="multipart/form-data",
        ).status_code
        == 302
    )

    with app.app_context():
        assert service.rotate_next() == "clock"
        assert service.rotate_next() == "photo"
    with app.app_context():
        assert db.session.get(DisplayState, 1).last_plugin_shown == "photo"
        settings = db.session.get(PluginSettings, "photo")
        first_selected_id = settings.parameters["last_photo_id"]
        assert (tmp_path / "previews" / "photo-preview.png").is_file()

    restarted_app = _app(tmp_path)
    with restarted_app.app_context():
        settings = db.session.get(PluginSettings, "photo")
        assert settings.parameters["last_photo_id"] == first_selected_id
        frame = restarted_app.extensions["inkdisplay.plugin_service"].render_plugin(
            "photo"
        )
        assert frame.size == (400, 300)
        assert frame.mode == "1"
        assert db.session.get(PluginSettings, "photo").parameters["last_photo_id"] != (
            first_selected_id
        )
