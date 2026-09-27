"""Display mode selection with non-fatal Waveshare fallback."""

from __future__ import annotations

import logging
import platform
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from inkdisplay.infrastructure.display.managed_display import ManagedDisplay
from inkdisplay.infrastructure.display.mock_display import MockDisplay
from inkdisplay.infrastructure.display.waveshare_4in2_v2 import (
    DisplayHardwareError,
    Waveshare4In2V2Display,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DisplaySelection:
    display: ManagedDisplay
    mode: str
    driver_name: str
    fallback_reason: str | None = None


def is_raspberry_pi() -> bool:
    if platform.system() != "Linux":
        return False
    try:
        model = Path("/proc/device-tree/model").read_text(errors="ignore")
    except OSError:
        model = ""
    if "Raspberry Pi" in model:
        return True
    try:
        cpu_info = Path("/proc/cpuinfo").read_text(errors="ignore")
    except OSError:
        return False
    return "Raspberry Pi" in cpu_info or "BCM" in cpu_info


def select_display(
    requested_mode: str,
    preview_path: Path,
    lock_path: Path,
    *,
    raspberry_detector: Callable[[], bool] = is_raspberry_pi,
    driver_loader: Callable[[], Any] | None = None,
) -> DisplaySelection:
    mode = requested_mode.lower()
    if mode == "mock":
        return _mock_selection(preview_path, lock_path)
    if mode not in {"waveshare", "hardware"}:
        raise ValueError(f"Display mode non supportata: {requested_mode}")

    if not raspberry_detector():
        reason = "Raspberry Pi non rilevato"
        logger.warning("Waveshare richiesto ma %s; uso mock", reason)
        return _mock_selection(preview_path, lock_path, reason)

    try:
        driver = Waveshare4In2V2Display(driver_loader=driver_loader)
        managed = ManagedDisplay(
            driver,
            mode="waveshare",
            driver_name=driver.driver_name,
            lock_path=lock_path,
        )
        managed.initialize()
        return DisplaySelection(managed, "waveshare", driver.driver_name)
    except (DisplayHardwareError, ImportError, OSError, RuntimeError) as error:
        reason = str(error)
        logger.warning("Waveshare non disponibile (%s); uso mock", reason)
        return _mock_selection(preview_path, lock_path, reason)


def _mock_selection(
    preview_path: Path, lock_path: Path, reason: str | None = None
) -> DisplaySelection:
    managed = ManagedDisplay(
        MockDisplay(preview_path),
        mode="mock",
        driver_name="MockDisplay",
        lock_path=lock_path,
        fallback_reason=reason,
    )
    return DisplaySelection(managed, "mock", "MockDisplay", reason)
