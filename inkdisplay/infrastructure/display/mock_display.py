"""Cross-platform display adapter that stores the last frame as a PNG."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from tempfile import NamedTemporaryFile

from PIL import Image


class MockDisplay:
    supports_partial_refresh = False
    supports_fast_refresh = False

    def __init__(self, preview_path: Path) -> None:
        self.preview_path = preview_path
        self._lock = threading.Lock()
        self._initialized = False

    def initialize(self) -> None:
        self.preview_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialized = True

    def display(self, image: Image.Image) -> None:
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("A display update is already in progress.")
        temporary_path: Path | None = None
        try:
            self.initialize()
            frame = image.convert("1")
            if frame.size != (400, 300):
                raise ValueError("Display image must be exactly 400x300 pixels.")
            with NamedTemporaryFile(
                suffix=".png", dir=self.preview_path.parent, delete=False
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
            frame.save(temporary_path, format="PNG")
            os.replace(temporary_path, self.preview_path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
            self._lock.release()

    def clear(self) -> None:
        self.display(Image.new("1", (400, 300), color=255))

    def sleep(self) -> None:
        self._initialized = False

    def close(self) -> None:
        self.sleep()
