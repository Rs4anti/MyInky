"""Clock preview use case."""

from PIL import Image

from inkdisplay.infrastructure.display.port import DisplayPort
from inkdisplay.presentation.rendering.renderer import ClockRenderer


class PreviewService:
    def __init__(self, renderer: ClockRenderer, display: DisplayPort) -> None:
        self._renderer = renderer
        self._display = display

    def refresh_clock_preview(self) -> Image.Image:
        image = self._renderer.render_clock()
        self._display.display(image)
        return image
