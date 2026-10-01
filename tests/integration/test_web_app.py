from io import BytesIO
from pathlib import Path

from PIL import Image

from inkdisplay.app import create_app


def test_health_endpoint_reports_mock_mode(tmp_path: Path) -> None:
    app = create_app({"TESTING": True, "DATA_DIR": tmp_path, "SECRET_KEY": "test-key"})

    response = app.test_client().get("/health")

    assert response.status_code == 200
    assert response.json == {"status": "ok", "display_mode": "mock"}


def test_preview_is_monochrome_png_without_claiming_a_display_success(
    tmp_path: Path,
) -> None:
    app = create_app({"TESTING": True, "DATA_DIR": tmp_path, "SECRET_KEY": "test-key"})

    response = app.test_client().get("/api/preview")
    saved_preview = tmp_path / "previews" / "current.png"

    assert response.status_code == 200
    assert response.mimetype == "image/png"
    assert response.headers["Cache-Control"].startswith("no-store")
    with Image.open(BytesIO(response.data)) as image:
        assert image.size == (400, 300)
        assert image.mode == "1"
    assert not saved_preview.exists()


def test_preview_supports_relative_data_directory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = create_app(
        {"TESTING": True, "DATA_DIR": Path("data"), "SECRET_KEY": "test-key"}
    )

    response = app.test_client().get("/api/preview")

    assert response.status_code == 200
    assert response.mimetype == "image/png"
    assert not (tmp_path / "data" / "previews" / "current.png").exists()
