"""Read-only preview of the currently scheduled plugin."""

from PIL import Image

from inkdisplay.application.services.plugin_service import PluginService


class PreviewService:
    def __init__(self, plugin_service: PluginService) -> None:
        self._plugin_service = plugin_service

    def render_current(self) -> Image.Image:
        return self._plugin_service.preview_current()
