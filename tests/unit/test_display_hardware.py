from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from inkdisplay.infrastructure.display.factory import select_display
from inkdisplay.infrastructure.display.managed_display import (
    DisplayBusyError,
    ManagedDisplay,
)
from inkdisplay.infrastructure.display.mock_display import MockDisplay
from inkdisplay.infrastructure.display.waveshare_4in2_v2 import (
    DisplayHardwareError,
    Waveshare4In2V2Display,
)


class FakeDriver:
    width = 400
    height = 300
    Seconds_1S = 1

    def __init__(self) -> None:
        self.calls: list[object] = []

    def init(self) -> int:
        self.calls.append("init")
        return 0

    def getbuffer(self, image: Image.Image) -> bytes:
        self.calls.append("getbuffer")
        return image.convert("1").tobytes()

    def ReadBusy(self) -> None:
        self.calls.append("busy-complete")

    def display(self, buffer: bytes) -> None:
        self.calls.append(("full", len(buffer)))

    def display_Partial(self, buffer: bytes) -> None:
        self.calls.append(("partial", len(buffer)))

    def init_fast(self, mode: int) -> int:
        self.calls.append(("init_fast", mode))
        return 0

    def display_Fast(self, buffer: bytes) -> None:
        self.calls.append(("fast", len(buffer)))

    def Clear(self) -> None:
        self.calls.append("clear")

    def sleep(self) -> None:
        self.calls.append("sleep")


def _frame(color: int = 0) -> Image.Image:
    return Image.new("1", (400, 300), color=color)


def test_waveshare_driver_load_is_injected_and_capabilities_are_detected() -> None:
    driver = FakeDriver()
    adapter = Waveshare4In2V2Display(driver=driver)

    assert adapter.supports_partial_refresh is True
    assert adapter.supports_fast_refresh is True
    adapter.initialize()
    adapter.display(_frame())
    assert ("full", 15000) in driver.calls


def test_driver_module_import_uses_official_module_name(monkeypatch) -> None:
    driver = FakeDriver()
    imported = []

    def fake_import(module_name: str):
        imported.append(module_name)
        return SimpleNamespace(EPD=lambda: driver)

    monkeypatch.setattr(
        "inkdisplay.infrastructure.display.waveshare_4in2_v2.importlib.import_module",
        fake_import,
    )

    adapter = Waveshare4In2V2Display()

    assert imported == ["waveshare_epd.epd4in2_V2"]
    assert adapter.driver_name == "waveshare_epd.epd4in2_V2.EPD"


def test_waveshare_partial_fast_and_clear_use_real_driver_methods() -> None:
    driver = FakeDriver()
    adapter = Waveshare4In2V2Display(driver=driver)
    adapter.initialize()

    partial = _frame(1)
    partial.info["refresh_mode"] = "partial"
    adapter.display(partial)
    fast = _frame(0)
    fast.info["refresh_mode"] = "fast"
    adapter.display(fast)
    adapter.clear()
    adapter.sleep()
    adapter.close()

    assert any(
        isinstance(call, tuple) and call[0] == "partial" for call in driver.calls
    )
    assert ("init_fast", driver.Seconds_1S) in driver.calls
    assert any(isinstance(call, tuple) and call[0] == "fast" for call in driver.calls)
    assert "clear" in driver.calls
    assert "sleep" in driver.calls


def test_capability_detection_does_not_claim_missing_refresh_modes() -> None:
    driver = FakeDriver()
    driver.display_Partial = None
    driver.display_Fast = None
    driver.init_fast = None
    adapter = Waveshare4In2V2Display(driver=driver)

    assert adapter.supports_partial_refresh is False
    assert adapter.supports_fast_refresh is False
    adapter.initialize()
    frame = _frame()
    frame.info["refresh_mode"] = "partial"
    adapter.display(frame)
    assert any(isinstance(call, tuple) and call[0] == "full" for call in driver.calls)


def test_hardware_selection_falls_back_when_not_pi_or_driver_missing(
    tmp_path: Path,
) -> None:
    not_pi = select_display(
        "waveshare",
        tmp_path / "previews" / "current.png",
        tmp_path / "display.lock",
        raspberry_detector=lambda: False,
        driver_loader=lambda: pytest.fail("driver import should not be attempted"),
    )
    missing_module = select_display(
        "waveshare",
        tmp_path / "previews" / "current.png",
        tmp_path / "display-missing.lock",
        raspberry_detector=lambda: True,
        driver_loader=lambda: (_ for _ in ()).throw(ModuleNotFoundError("driver")),
    )

    assert not_pi.mode == missing_module.mode == "mock"
    assert isinstance(not_pi.display._delegate, MockDisplay)
    assert "non rilevato" in str(not_pi.fallback_reason)
    assert "driver" in str(missing_module.fallback_reason)


def test_hash_skips_unchanged_frame_and_records_both_hashes(tmp_path: Path) -> None:
    delegate = MockDisplay(tmp_path / "current.png")
    display = ManagedDisplay(
        delegate,
        mode="mock",
        driver_name="MockDisplay",
        lock_path=tmp_path / "display.lock",
    )
    display.display(_frame(0))
    current_hash = display.last_hash
    physical_update_at = display.last_update_at
    display.display(_frame(0))

    assert display.last_result == "skipped-unchanged"
    assert display.previous_hash == current_hash
    assert display.new_hash == current_hash
    assert display.last_update_at == physical_update_at


def test_image_hash_survives_managed_display_recreation(tmp_path: Path) -> None:
    lock_path = tmp_path / "display.lock"
    preview_path = tmp_path / "current.png"
    first = ManagedDisplay(
        MockDisplay(preview_path),
        mode="mock",
        driver_name="MockDisplay",
        lock_path=lock_path,
    )
    frame = _frame(0)
    first.display(frame)

    restarted = ManagedDisplay(
        MockDisplay(preview_path),
        mode="mock",
        driver_name="MockDisplay",
        lock_path=lock_path,
    )
    restarted.display(frame)

    assert restarted.last_hash == first.last_hash
    assert restarted.last_result == "skipped-unchanged"


def test_partial_clock_refresh_is_forced_full_after_five_updates(
    tmp_path: Path,
) -> None:
    class RecordingDisplay:
        supports_partial_refresh = True
        supports_fast_refresh = False

        def __init__(self) -> None:
            self.refresh_modes: list[str] = []

        def initialize(self) -> None:
            return None

        def display(self, image: Image.Image) -> None:
            self.refresh_modes.append(str(image.info["refresh_mode"]))

        def clear(self) -> None:
            return None

        def sleep(self) -> None:
            return None

        def close(self) -> None:
            return None

    delegate = RecordingDisplay()
    display = ManagedDisplay(
        delegate,
        mode="waveshare",
        driver_name="fake-driver",
        lock_path=tmp_path / "partial.lock",
    )
    for index in range(6):
        frame = Image.new("1", (400, 300), color=255)
        for y in range(index + 1):
            for x in range(30):
                frame.putpixel((x, y), 0)
        frame.info["refresh_mode"] = "partial"
        display.display(frame)

    assert delegate.refresh_modes == ["partial"] * 5 + ["full"]


def test_display_lock_rejects_concurrent_update(tmp_path: Path) -> None:
    entered = threading.Event()
    release = threading.Event()

    class BlockingDisplay:
        supports_partial_refresh = False
        supports_fast_refresh = False

        def initialize(self) -> None:
            return None

        def display(self, image: Image.Image) -> None:
            entered.set()
            release.wait(timeout=3)

        def clear(self) -> None:
            return None

        def sleep(self) -> None:
            return None

        def close(self) -> None:
            return None

    display = ManagedDisplay(
        BlockingDisplay(),
        mode="waveshare",
        driver_name="fake-driver",
        lock_path=tmp_path / "display.lock",
    )
    first = threading.Thread(target=display.display, args=(_frame(),))
    first.start()
    assert entered.wait(timeout=2)
    try:
        with pytest.raises(DisplayBusyError):
            display.display(_frame(1))
    finally:
        release.set()
        first.join(timeout=2)
    assert first.is_alive() is False


def test_driver_initialization_errors_are_translated() -> None:
    driver = FakeDriver()

    def fail_init() -> int:
        raise OSError("SPI unavailable")

    driver.init = fail_init
    adapter = Waveshare4In2V2Display(driver=driver)

    with pytest.raises(DisplayHardwareError, match="SPI/GPIO"):
        adapter.initialize()
