"""Clock content plugin backed by the existing Pillow clock renderer."""

from PIL import Image

from inkdisplay.presentation.rendering.renderer import ClockRenderer


class ClockPlugin:
    key = "clock"

    def __init__(self, renderer: ClockRenderer) -> None:
        self._renderer = renderer
        self._image: Image.Image | None = None

    def refresh_content(self) -> None:
        self._image = self._renderer.render_clock()

    def render(self) -> Image.Image:
        if self._image is None:
            self.refresh_content()
        assert self._image is not None
        image = self._image.copy()
        image.info["refresh_mode"] = "partial"
        return image
