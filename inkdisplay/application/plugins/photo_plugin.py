"""Persistent photo content plugin."""

from __future__ import annotations

import logging
import os
import random
from collections.abc import Mapping
from pathlib import Path
from tempfile import NamedTemporaryFile

from flask import current_app, has_app_context
from PIL import Image
from sqlalchemy.exc import SQLAlchemyError

from inkdisplay.application.services.photo_service import PhotoService
from inkdisplay.extensions import db
from inkdisplay.infrastructure.persistence.models import PluginSettings
from inkdisplay.infrastructure.persistence.photo_models import Photo
from inkdisplay.presentation.rendering.photo_renderer import PhotoRenderer

logger = logging.getLogger(__name__)


class PhotoPlugin:
    key = "photo"

    def refresh_content(self) -> None:
        return None

    def render(self) -> Image.Image:
        if not has_app_context():
            return PhotoRenderer.render_unavailable()
        settings = self._plugin_settings()
        photo_service = PhotoService(Path(current_app.config["DATA_DIR"]))
        photos = photo_service.list_photos()
        enabled = [photo for photo in photos if photo.enabled]
        if not enabled:
            image = PhotoRenderer.render_unavailable()
            self._save_preview(image)
            return image

        photo = self._select_photo(enabled, settings.parameters)
        try:
            image = photo_service.processed_image(photo)
        except (OSError, ValueError):
            logger.exception("Could not render photo id=%s", photo.id)
            image = PhotoRenderer.render_unavailable()
        settings.parameters = {**settings.parameters, "last_photo_id": photo.id}
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            logger.exception("Could not persist last displayed photo")
        self._save_preview(image)
        return image

    @staticmethod
    def _plugin_settings() -> PluginSettings:
        settings = db.session.get(PluginSettings, "photo")
        if settings is None:
            settings = PluginSettings(plugin_key="photo", enabled=False, sort_order=2)
            db.session.add(settings)
            db.session.commit()
        return settings

    @staticmethod
    def _select_photo(photos: list[Photo], parameters: Mapping[str, object]) -> Photo:
        sequence_mode = parameters.get("sequence_mode", "sequential")
        previous_id = parameters.get("last_photo_id")
        if sequence_mode == "random":
            choices = [photo for photo in photos if photo.id != previous_id] or photos
            return random.choice(choices)
        ordered = sorted(photos, key=lambda photo: (photo.sort_order, photo.id))
        for index, photo in enumerate(ordered):
            if photo.id == previous_id:
                return ordered[(index + 1) % len(ordered)]
        return ordered[0]

    @staticmethod
    def _save_preview(image: Image.Image) -> None:
        preview_path = (
            Path(current_app.config["DATA_DIR"]).resolve()
            / "previews"
            / "photo-preview.png"
        )
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                suffix=".png", dir=preview_path.parent, delete=False
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
            image.save(temporary_path, format="PNG")
            os.replace(temporary_path, preview_path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
