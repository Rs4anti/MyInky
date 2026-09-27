"""Weather content plugin; rendering reads only the persisted cache."""

import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from flask import current_app, has_app_context
from PIL import Image

from inkdisplay.application.services.weather_service import WeatherService
from inkdisplay.domain.weather import WeatherSnapshot
from inkdisplay.extensions import db
from inkdisplay.infrastructure.persistence.models import PluginSettings, WeatherCache
from inkdisplay.presentation.rendering.weather_renderer import (
    WeatherDisplayOptions,
    WeatherRenderer,
)


class WeatherPlugin:
    key = "weather"

    def __init__(self, service: WeatherService, renderer: WeatherRenderer) -> None:
        self._service = service
        self._renderer = renderer

    def refresh_content(self) -> None:
        self._service.refresh(force=True)

    def render(self) -> Image.Image:
        snapshot = self._service.cached()
        if snapshot is None:
            image = self._renderer.render_unavailable()
        else:
            snapshot = self._with_refresh_timestamp(snapshot)
            image = self._renderer.render(snapshot, self._display_options())
        self._save_preview(image)
        return image

    @staticmethod
    def _with_refresh_timestamp(snapshot: WeatherSnapshot) -> WeatherSnapshot:
        cache = db.session.get(WeatherCache, 1)
        if cache is None:
            return snapshot
        refreshed_at = cache.fetched_at
        if refreshed_at.tzinfo is None:
            refreshed_at = refreshed_at.replace(tzinfo=UTC)
        try:
            observed_timezone = datetime.fromisoformat(snapshot.observed_at).tzinfo
        except ValueError:
            observed_timezone = UTC
        if observed_timezone is not None:
            refreshed_at = refreshed_at.astimezone(observed_timezone)
        return replace(snapshot, refreshed_at=refreshed_at.isoformat())

    @staticmethod
    def _display_options() -> WeatherDisplayOptions:
        setting = db.session.get(PluginSettings, "weather")
        parameters = setting.parameters if setting is not None else {}
        return WeatherDisplayOptions(
            show_humidity=bool(parameters.get("show_humidity", True)),
            show_wind=bool(parameters.get("show_wind", True)),
            show_pressure=bool(parameters.get("show_pressure", True)),
            show_feels_like=bool(parameters.get("show_feels_like", False)),
            show_forecast=bool(parameters.get("show_forecast", True)),
        )

    @staticmethod
    def _save_preview(image: Image.Image) -> None:
        if not has_app_context():
            return
        preview_path = (
            Path(current_app.config["DATA_DIR"]).resolve()
            / "previews"
            / "weather-preview.png"
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
