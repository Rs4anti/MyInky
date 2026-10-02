"""Lazy adapter for the official Waveshare 4.2-inch V2 Python driver."""

from __future__ import annotations

import hashlib
import importlib
import logging
import threading
from collections.abc import Callable
from typing import Any

from PIL import Image

logger = logging.getLogger(__name__)
DRIVER_MODULE = "waveshare_epd.epd4in2_V2"


class DisplayHardwareError(RuntimeError):
    """A hardware operation failed in the Waveshare driver."""


class Waveshare4In2V2Display:
    driver_name = f"{DRIVER_MODULE}.EPD"
    width = 400
    height = 300

    def __init__(
        self,
        driver: Any | None = None,
        driver_loader: Callable[[], Any] | None = None,
    ) -> None:
        self._driver = (
            driver if driver is not None else self._load_driver(driver_loader)
        )
        self._lock = threading.Lock()
        self._initialized = False
        self._active_mode = "full"
        self._validate_driver()
        self.supports_partial_refresh = callable(
            getattr(self._driver, "display_Partial", None)
        )
        self.supports_fast_refresh = (
            callable(getattr(self._driver, "init_fast", None))
            and callable(getattr(self._driver, "display_Fast", None))
            and hasattr(self._driver, "Seconds_1S")
        )

    @staticmethod
    def _load_driver(driver_loader: Callable[[], Any] | None) -> Any:
        if driver_loader is not None:
            return driver_loader()
        module = importlib.import_module(DRIVER_MODULE)
        driver_class = getattr(module, "EPD", None)
        if driver_class is None:
            raise DisplayHardwareError(
                f"{DRIVER_MODULE} non espone la classe EPD attesa."
            )
        return driver_class()

    def _validate_driver(self) -> None:
        required_methods = (
            "init",
            "ReadBusy",
            "getbuffer",
            "display",
            "Clear",
            "sleep",
        )
        missing = [
            name
            for name in required_methods
            if not callable(getattr(self._driver, name, None))
        ]
        if missing:
            raise DisplayHardwareError(
                "Driver Waveshare incompatibile; API mancanti: " + ", ".join(missing)
            )
        if (
            getattr(self._driver, "width", self.width) != self.width
            or getattr(self._driver, "height", self.height) != self.height
        ):
            raise DisplayHardwareError("Il driver non dichiara la risoluzione 400x300.")

    def initialize(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            self._initialize_normal()

    def _initialize_normal(self) -> None:
        try:
            result = self._driver.init()
        except Exception as error:
            raise DisplayHardwareError(
                "Inizializzazione Waveshare fallita (SPI/GPIO)."
            ) from error
        if result not in (None, 0):
            raise DisplayHardwareError(
                f"Il driver Waveshare init() ha restituito {result!r}."
            )
        self._initialized = True
        self._active_mode = "full"

    def display(self, image: Image.Image) -> None:
        if not self._lock.acquire(blocking=False):
            raise DisplayHardwareError("Aggiornamento Waveshare già in corso.")
        try:
            self._display_locked(image)
        finally:
            self._lock.release()

    def _display_locked(self, image: Image.Image) -> None:
        if image.size != (self.width, self.height):
            raise ValueError("Display image must be exactly 400x300 pixels.")
        plugin_change = bool(image.info.get("force_full_refresh"))
        if plugin_change:
            self._initialize_normal()
            logger.info(
                "PLUGIN_CHANGE_FULL_REFRESH from=%s to=%s method=EPD.init",
                image.info.get("plugin_change_from", "unknown"),
                image.info.get("plugin_change_to", "unknown"),
            )
        elif not self._initialized:
            self._initialize_normal()
        frame = image.convert("1", dither=Image.Dither.NONE)
        if isinstance(image.info.get("clock_render"), dict):
            logger.info(
                "CLOCK_RENDER display_frame=%s source=%s frame=%sx%s hash=%s",
                self.driver_name,
                __file__,
                frame.width,
                frame.height,
                hashlib.sha256(frame.tobytes()).hexdigest(),
            )
        requested_mode = (
            "full"
            if plugin_change
            else str(image.info.get("refresh_mode", "full")).lower()
        )
        if requested_mode not in {"full", "fast", "partial"}:
            logger.warning("Refresh mode %r sconosciuta; uso full", requested_mode)
            requested_mode = "full"
        if requested_mode == "partial" and not self.supports_partial_refresh:
            logger.warning("Driver Waveshare senza display_Partial; uso refresh full")
            requested_mode = "full"
        if requested_mode == "fast" and not self.supports_fast_refresh:
            logger.warning("Driver Waveshare senza API fast completa; uso refresh full")
            requested_mode = "full"

        try:
            buffer = self._driver.getbuffer(frame)
            if requested_mode == "partial":
                if self._active_mode == "fast":
                    self._initialize_normal()
                self._driver.display_Partial(buffer)
            elif requested_mode == "fast":
                result = self._driver.init_fast(self._driver.Seconds_1S)
                if result not in (None, 0):
                    logger.warning("init_fast() fallito; riprovo con refresh full")
                    self._initialize_normal()
                    self._driver.display(buffer)
                else:
                    self._initialized = True
                    self._active_mode = "fast"
                    self._driver.display_Fast(buffer)
            else:
                if self._active_mode == "fast":
                    self._initialize_normal()
                    buffer = self._driver.getbuffer(frame)
                self._driver.display(buffer)
                self._active_mode = "full"
                if plugin_change:
                    logger.info(
                        "PLUGIN_CHANGE_FULL_REFRESH from=%s to=%s method=EPD.display",
                        image.info.get("plugin_change_from", "unknown"),
                        image.info.get("plugin_change_to", "unknown"),
                    )
        except DisplayHardwareError:
            raise
        except Exception as error:
            raise DisplayHardwareError(
                "Aggiornamento Waveshare fallito (SPI/GPIO/BUSY)."
            ) from error

    def clear(self) -> None:
        with self._lock:
            if not self._initialized:
                self._initialize_normal()
            try:
                self._driver.Clear()
                self._active_mode = "full"
            except Exception as error:
                raise DisplayHardwareError("Pulizia Waveshare fallita.") from error

    def sleep(self) -> None:
        with self._lock:
            if not self._initialized:
                return
            try:
                self._driver.sleep()
            except Exception as error:
                raise DisplayHardwareError("Sleep Waveshare fallito.") from error
            finally:
                self._initialized = False
                self._active_mode = "full"

    def close(self) -> None:
        self.sleep()
