"""Visual plugin contract."""

from typing import Protocol

from PIL import Image


class VisualPlugin(Protocol):
    key: str

    def refresh_content(self) -> None: ...

    def render(self) -> Image.Image: ...
