"""Photo upload, storage, settings, and metadata use cases."""

from __future__ import annotations

import logging
import os
import re
import warnings
from collections.abc import Mapping
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import IO
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.exc import SQLAlchemyError

from inkdisplay.extensions import db
from inkdisplay.infrastructure.persistence.models import PluginSettings
from inkdisplay.infrastructure.persistence.photo_models import Photo
from inkdisplay.presentation.rendering.photo_renderer import (
    DITHER_MODES,
    FIT_MODES,
    PhotoProcessingOptions,
    PhotoRenderer,
)

logger = logging.getLogger(__name__)
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_MIME_FORMATS = {
    "image/jpeg": {"JPEG"},
    "image/png": {"PNG"},
    "image/webp": {"WEBP"},
}
ALLOWED_MIME_EXTENSIONS = {
    "image/jpeg": {".jpg", ".jpeg"},
    "image/png": {".png"},
    "image/webp": {".webp"},
}
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
SAFE_FILENAME = re.compile(r"[0-9a-f]{32}\.(?:jpg|jpeg|png|webp)\Z")
DEFAULT_PHOTO_SETTINGS: dict[str, object] = {
    "fit_mode": "contain",
    "dithering": "floyd_steinberg",
    "contrast": 1.2,
    "sharpness": 1.0,
    "sequence_mode": "sequential",
    "max_upload_mb": 10,
    "last_photo_id": None,
}


class PhotoValidationError(ValueError):
    """Raised when an uploaded image or photo setting is invalid."""


class PhotoService:
    def __init__(self, data_dir: Path, renderer: PhotoRenderer | None = None) -> None:
        self.upload_dir = data_dir.resolve() / "uploads"
        self.upload_dir.mkdir(parents=True, exist_ok=True, mode=0o750)
        self._renderer = renderer or PhotoRenderer()

    def settings(self) -> dict[str, object]:
        plugin = self._plugin_settings()
        return {
            **DEFAULT_PHOTO_SETTINGS,
            **plugin.parameters,
            "plugin_enabled": plugin.enabled,
        }

    def save_settings(self, form: Mapping[str, str]) -> None:
        plugin = self._plugin_settings()
        parameters = {**DEFAULT_PHOTO_SETTINGS, **plugin.parameters}
        fit_mode = form.get("fit_mode", "contain")
        if fit_mode not in FIT_MODES:
            raise PhotoValidationError("Modalità di adattamento non valida.")
        dithering = form.get("dithering", "floyd_steinberg")
        if dithering not in DITHER_MODES:
            raise PhotoValidationError("Modalità dithering non valida.")
        sequence_mode = form.get("sequence_mode", "sequential")
        if sequence_mode not in {"sequential", "random"}:
            raise PhotoValidationError("Modalità di sequenza non valida.")
        max_upload_mb = self._parse_number(
            form.get("max_upload_mb"), "Limite upload", 1, 10
        )
        contrast = self._parse_float(form.get("contrast"), "Contrasto", 0.0, 3.0)
        sharpness = self._parse_float(form.get("sharpness"), "Nitidezza", 0.0, 3.0)

        parameters.update(
            fit_mode=fit_mode,
            dithering=dithering,
            sequence_mode=sequence_mode,
            max_upload_mb=max_upload_mb,
            contrast=contrast,
            sharpness=sharpness,
        )
        plugin.parameters = parameters
        plugin.enabled = "plugin_enabled" in form
        self._commit()

    def list_photos(self) -> list[Photo]:
        return list(
            db.session.query(Photo)
            .order_by(Photo.sort_order, Photo.created_at, Photo.id)
            .all()
        )

    def upload(
        self,
        stream: IO[bytes],
        *,
        original_name: str,
        mime_type: str,
        caption: str | None = None,
        max_upload_mb: int = 10,
    ) -> Photo:
        safe_name = self._safe_original_name(original_name)
        extension = Path(safe_name).suffix.lower()
        normalized_mime = mime_type.split(";", maxsplit=1)[0].strip().lower()
        allowed_formats = ALLOWED_MIME_FORMATS.get(normalized_mime)
        allowed_extensions = ALLOWED_MIME_EXTENSIONS.get(normalized_mime)
        if (
            extension not in ALLOWED_EXTENSIONS
            or allowed_formats is None
            or allowed_extensions is None
            or extension not in allowed_extensions
        ):
            raise PhotoValidationError("Sono consentite solo immagini JPG, PNG o WEBP.")

        if not 1 <= max_upload_mb <= 10:
            raise PhotoValidationError("Il limite upload deve essere tra 1 e 10 MB.")
        limit = min(max_upload_mb * 1024 * 1024, MAX_UPLOAD_BYTES)
        content = stream.read(limit + 1)
        if len(content) > limit:
            raise PhotoValidationError(
                f"Il file supera il limite configurato di {max_upload_mb} MB."
            )
        width, height = self._verify_image(content, allowed_formats)

        filename = f"{uuid4().hex}{extension}"
        target = self._photo_path(filename)
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                dir=self.upload_dir, suffix=extension, delete=False
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(content)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, target)
            last_order = db.session.query(db.func.max(Photo.sort_order)).scalar() or -1
            photo = Photo(
                filename=filename,
                original_name=safe_name[:255],
                sort_order=last_order + 1,
                caption=(caption or "").strip()[:240] or None,
                width=width,
                height=height,
            )
            db.session.add(photo)
            self._commit()
            logger.info("Photo uploaded: id=%s, bytes=%s", photo.id, len(content))
            return photo
        except (OSError, SQLAlchemyError):
            db.session.rollback()
            target.unlink(missing_ok=True)
            logger.exception("Could not save uploaded photo")
            raise
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def photo(self, photo_id: int) -> Photo | None:
        return db.session.get(Photo, photo_id)

    def source_path(self, photo: Photo) -> Path:
        return self._photo_path(photo.filename)

    def processed_image(self, photo: Photo) -> Image.Image:
        settings = self.settings()
        contrast = settings.get("contrast", 1.2)
        sharpness = settings.get("sharpness", 1.0)
        options = PhotoProcessingOptions(
            fit_mode=str(settings["fit_mode"]),
            dithering=str(settings["dithering"]),
            contrast=(
                float(contrast) if isinstance(contrast, (int, float, str)) else 1.2
            ),
            sharpness=(
                float(sharpness) if isinstance(sharpness, (int, float, str)) else 1.0
            ),
        )
        with Image.open(self.source_path(photo)) as source:
            return self._renderer.render(source, options)

    def set_enabled(self, photo_id: int, enabled: bool) -> bool:
        photo = self.photo(photo_id)
        if photo is None:
            return False
        photo.enabled = enabled
        self._commit()
        return True

    def delete(self, photo_id: int) -> bool:
        photo = self.photo(photo_id)
        if photo is None:
            return False
        path = self.source_path(photo)
        db.session.delete(photo)
        self._commit()
        path.unlink(missing_ok=True)
        logger.info("Photo deleted: id=%s", photo_id)
        return True

    def move(self, photo_id: int, direction: str) -> bool:
        photos = self.list_photos()
        current_index = next(
            (index for index, photo in enumerate(photos) if photo.id == photo_id),
            None,
        )
        if current_index is None or direction not in {"up", "down"}:
            return False
        target_index = current_index + (-1 if direction == "up" else 1)
        if not 0 <= target_index < len(photos):
            return False
        photos[current_index], photos[target_index] = (
            photos[target_index],
            photos[current_index],
        )
        for order, photo in enumerate(photos):
            photo.sort_order = order
        self._commit()
        return True

    @staticmethod
    def _safe_original_name(filename: str) -> str:
        safe_name = filename.replace("\\", "/").rsplit("/", maxsplit=1)[-1].strip()
        if not safe_name or safe_name in {".", ".."}:
            raise PhotoValidationError("Nome file non valido.")
        return safe_name

    @staticmethod
    def _verify_image(content: bytes, allowed_formats: set[str]) -> tuple[int, int]:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(content)) as image:
                    actual_format = image.format
                    image.verify()
                if actual_format not in allowed_formats:
                    raise PhotoValidationError(
                        "Il contenuto non corrisponde al tipo MIME dichiarato."
                    )
                with Image.open(BytesIO(content)) as reopened:
                    corrected = ImageOps.exif_transpose(reopened)
                    if (
                        Image.MAX_IMAGE_PIXELS is not None
                        and corrected.width * corrected.height > Image.MAX_IMAGE_PIXELS
                    ):
                        raise PhotoValidationError(
                            "Immagine troppo grande per l'elaborazione."
                        )
                    return corrected.size
        except PhotoValidationError:
            raise
        except (
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
            OSError,
            UnidentifiedImageError,
            ValueError,
        ) as error:
            raise PhotoValidationError(
                "Il file non è un'immagine valida o è corrotto."
            ) from error

    def _photo_path(self, filename: str) -> Path:
        if SAFE_FILENAME.fullmatch(filename) is None:
            raise PhotoValidationError("Nome file interno non valido.")
        path = (self.upload_dir / filename).resolve()
        if path.parent != self.upload_dir.resolve():
            raise PhotoValidationError("Percorso file non valido.")
        return path

    @staticmethod
    def _plugin_settings() -> PluginSettings:
        plugin = db.session.get(PluginSettings, "photo")
        if plugin is None:
            plugin = PluginSettings(plugin_key="photo", enabled=False, sort_order=2)
            db.session.add(plugin)
            db.session.commit()
        return plugin

    @staticmethod
    def _parse_number(value: str | None, label: str, minimum: int, maximum: int) -> int:
        try:
            result = int(value or "")
        except ValueError as error:
            raise PhotoValidationError(
                f"{label}: valore numerico non valido."
            ) from error
        if not minimum <= result <= maximum:
            raise PhotoValidationError(
                f"{label}: inserire un valore tra {minimum} e {maximum}."
            )
        return result

    @staticmethod
    def _parse_float(
        value: str | None, label: str, minimum: float, maximum: float
    ) -> float:
        try:
            result = float(value or "")
        except ValueError as error:
            raise PhotoValidationError(
                f"{label}: valore numerico non valido."
            ) from error
        if not minimum <= result <= maximum:
            raise PhotoValidationError(
                f"{label}: inserire un valore tra {minimum} e {maximum}."
            )
        return result

    @staticmethod
    def _commit() -> None:
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            raise
