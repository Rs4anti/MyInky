"""Clock content plugin backed by the existing Pillow clock renderer."""

from flask import has_app_context
from PIL import Image

from inkdisplay.domain.weather import WeatherSnapshot
from inkdisplay.extensions import db
from inkdisplay.infrastructure.persistence.models import PluginSettings, WeatherCache
from inkdisplay.presentation.rendering.renderer import ClockRenderer


class ClockPlugin:
    key = "clock"

    def __init__(self, renderer: ClockRenderer) -> None:
        self._renderer = renderer
        self._image: Image.Image | None = None

    def refresh_content(self) -> None:
        self._image = self._render()

    def render(self) -> Image.Image:
        if self._image is None:
            self.refresh_content()
        assert self._image is not None
        image = self._image.copy()
        image.info.update(self._image.info)
        image.info["refresh_mode"] = "partial"
        return image

    def _render(self) -> Image.Image:
        if not has_app_context():
            return self._renderer.render_clock()
        setting = db.session.get(PluginSettings, "clock")
        parameters = setting.parameters if setting is not None else {}
        show_seconds = bool(parameters.get("show_seconds", False)) and bool(
            setting and setting.refresh_interval_minutes < 1
        )
        weather_summary = None
        if parameters.get("show_weather_summary", False):
            cache = db.session.get(WeatherCache, 1)
            if cache is not None:
                try:
                    weather = WeatherSnapshot.from_dict(cache.payload)
                except (KeyError, TypeError, ValueError):
                    weather = None
                if weather is not None:
                    weather_summary = (
                        f"{weather.temperature:.0f}{weather.temperature_unit} · "
                        f"{weather.description}"
                    )
        return self._renderer.render_clock(
            time_format=str(parameters.get("time_format", "24h")),
            show_seconds=show_seconds,
            show_timezone=bool(parameters.get("show_timezone", True)),
            weather_summary=weather_summary,
        )
