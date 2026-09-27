from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from inkdisplay.app import create_app
from inkdisplay.application.plugins.photo_plugin import PhotoPlugin
from inkdisplay.application.services.photo_service import (
    PhotoService,
    PhotoValidationError,
)
from inkdisplay.extensions import db
from inkdisplay.infrastructure.persistence.models import PluginSettings
from inkdisplay.infrastructure.persistence.photo_models import Photo
from inkdisplay.presentation.rendering.photo_renderer import (
    PhotoProcessingOptions,
    PhotoRenderer,
)


def _png_bytes(size: tuple[int, int] = (40, 20), color: str = "black") -> bytes:
    image = Image.new("RGB", size, color=color)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def app(tmp_path: Path):
    return create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "DATA_DIR": tmp_path,
            "SECRET_KEY": "photo-test-key",
        }
    )


def test_upload_saves_uuid_name_and_metadata(app, tmp_path: Path) -> None:
    with app.app_context():
        service = PhotoService(tmp_path)
        photo = service.upload(
            BytesIO(_png_bytes()),
            original_name=r"C:\photos\holiday.png",
            mime_type="image/png",
            caption="Vacanze",
        )

        assert photo.original_name == "holiday.png"
        assert photo.caption == "Vacanze"
        assert photo.width == 40
        assert photo.height == 20
        assert len(photo.filename.split(".")[0]) == 32
        assert service.source_path(photo).is_file()


def test_upload_rejects_corrupt_or_mismatched_images(app, tmp_path: Path) -> None:
    with app.app_context():
        service = PhotoService(tmp_path)
        with pytest.raises(PhotoValidationError, match="corrotto"):
            service.upload(
                BytesIO(b"not an image"),
                original_name="broken.png",
                mime_type="image/png",
            )
        with pytest.raises(PhotoValidationError, match="MIME"):
            service.upload(
                BytesIO(_png_bytes()),
                original_name="spoof.jpg",
                mime_type="image/jpeg",
            )
        with pytest.raises(PhotoValidationError, match="JPG, PNG"):
            service.upload(
                BytesIO(_png_bytes()),
                original_name="wrong-extension.jpg",
                mime_type="image/png",
            )


def test_upload_rejects_file_above_configured_limit(app, tmp_path: Path) -> None:
    with app.app_context():
        service = PhotoService(tmp_path)
        with pytest.raises(PhotoValidationError, match="limite configurato"):
            service.upload(
                BytesIO(b"x" * (1024 * 1024 + 1)),
                original_name="large.png",
                mime_type="image/png",
                max_upload_mb=1,
            )


def test_upload_corrects_exif_orientation(app, tmp_path: Path) -> None:
    image = Image.new("RGB", (40, 20), color="white")
    exif = Image.Exif()
    exif[274] = 6
    output = BytesIO()
    image.save(output, format="JPEG", exif=exif)

    with app.app_context():
        photo = PhotoService(tmp_path).upload(
            BytesIO(output.getvalue()),
            original_name="rotated.jpeg",
            mime_type="image/jpeg",
        )

    assert (photo.width, photo.height) == (20, 40)


def test_upload_rejects_decompression_bomb(app, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    with app.app_context():
        with pytest.raises(PhotoValidationError, match="valida|grande"):
            PhotoService(tmp_path).upload(
                BytesIO(_png_bytes((20, 20))),
                original_name="bomb.png",
                mime_type="image/png",
            )


def test_photo_settings_persist_and_enable_plugin(app, tmp_path: Path) -> None:
    values = {
        "plugin_enabled": "on",
        "fit_mode": "center_crop",
        "dithering": "atkinson",
        "sequence_mode": "random",
        "contrast": "1.8",
        "sharpness": "1.4",
        "max_upload_mb": "4",
    }
    with app.app_context():
        service = PhotoService(tmp_path)
        service.save_settings(values)
        persisted = service.settings()
        plugin = db.session.get(PluginSettings, "photo")

        assert plugin.enabled is True
        assert persisted["fit_mode"] == "center_crop"
        assert persisted["dithering"] == "atkinson"
        assert persisted["sequence_mode"] == "random"
        assert persisted["max_upload_mb"] == 4


def test_renderer_modes_change_frame_and_keep_epaper_format() -> None:
    source = Image.new("RGB", (800, 200), color="black")
    renderer = PhotoRenderer()
    contain = renderer.render(source, PhotoProcessingOptions(fit_mode="contain"))
    cover = renderer.render(source, PhotoProcessingOptions(fit_mode="cover"))
    center = renderer.render(source, PhotoProcessingOptions(fit_mode="center_crop"))

    assert all(
        frame.size == (400, 300) and frame.mode == "1"
        for frame in (contain, cover, center)
    )
    assert contain.getpixel((2, 2)) == 255
    assert cover.getpixel((2, 150)) == 0
    assert center.getpixel((2, 150)) == 0


def test_floyd_steinberg_and_atkinson_produce_dithered_frames() -> None:
    gradient = Image.linear_gradient("L").resize((400, 300))
    renderer = PhotoRenderer()
    floyd = renderer.render(
        gradient, PhotoProcessingOptions(fit_mode="cover", dithering="floyd_steinberg")
    )
    atkinson = renderer.render(
        gradient, PhotoProcessingOptions(fit_mode="cover", dithering="atkinson")
    )

    assert floyd.mode == atkinson.mode == "1"
    assert floyd.tobytes() != atkinson.tobytes()


def test_photo_selection_is_sequential_or_random(
    app, tmp_path: Path, monkeypatch
) -> None:
    photos = [
        SimpleNamespace(id=1, sort_order=0),
        SimpleNamespace(id=2, sort_order=1),
        SimpleNamespace(id=3, sort_order=2),
    ]

    assert PhotoPlugin._select_photo(photos, {"sequence_mode": "sequential"}).id == 1
    assert (
        PhotoPlugin._select_photo(
            photos, {"sequence_mode": "sequential", "last_photo_id": 2}
        ).id
        == 3
    )
    monkeypatch.setattr(
        "inkdisplay.application.plugins.photo_plugin.random.choice",
        lambda values: values[-1],
    )
    assert (
        PhotoPlugin._select_photo(
            photos, {"sequence_mode": "random", "last_photo_id": 2}
        ).id
        == 3
    )


def test_delete_removes_record_and_original_file(app, tmp_path: Path) -> None:
    with app.app_context():
        service = PhotoService(tmp_path)
        photo = service.upload(
            BytesIO(_png_bytes()), original_name="to-delete.png", mime_type="image/png"
        )
        path = service.source_path(photo)

        assert service.delete(photo.id) is True
        assert path.exists() is False
        assert db.session.get(Photo, photo.id) is None


def test_photo_plugin_generates_preview_without_replacing_current(
    app, tmp_path: Path
) -> None:
    with app.app_context():
        service = PhotoService(tmp_path)
        service.upload(
            BytesIO(_png_bytes()), original_name="preview.png", mime_type="image/png"
        )
        photo_plugin = PhotoPlugin()
        frame = photo_plugin.render()
        preview_path = tmp_path / "previews" / "photo-preview.png"

        assert frame.size == (400, 300)
        assert frame.mode == "1"
        assert preview_path.is_file()
        assert (tmp_path / "previews" / "current.png").exists() is False
