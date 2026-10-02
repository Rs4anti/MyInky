"""Hash-aware, process/thread-serialized display wrapper."""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from types import TracebackType

from filelock import FileLock, Timeout
from PIL import Image

from inkdisplay.infrastructure.display.port import DisplayPort

logger = logging.getLogger(__name__)
MAX_CONSECUTIVE_PARTIAL_REFRESHES = 5


class DisplayBusyError(RuntimeError):
    """Raised when another thread/process is updating the display."""


class ManagedDisplay:
    def __init__(
        self,
        delegate: DisplayPort,
        *,
        mode: str,
        driver_name: str,
        lock_path: Path,
        fallback_reason: str | None = None,
        fallback_display: DisplayPort | None = None,
    ) -> None:
        self._delegate = delegate
        self._fallback_display = fallback_display
        self.mode = mode
        self.driver_name = driver_name
        self.fallback_reason = fallback_reason
        self._thread_lock = threading.Lock()
        self._process_lock = FileLock(str(lock_path))
        self._lock_path = lock_path
        self._hash_path = lock_path.with_name(f"display-{mode}.sha256")
        self.last_hash = self._load_hash()
        self.previous_hash: str | None = None
        self.new_hash: str | None = None
        self.last_update_at: str | None = None
        self.last_result = "not-updated"
        self.last_error: str | None = None
        self.last_refresh_mode = "full"
        self._partial_refresh_count = 0

    @property
    def supports_partial_refresh(self) -> bool:
        return self._delegate.supports_partial_refresh

    @property
    def supports_fast_refresh(self) -> bool:
        return self._delegate.supports_fast_refresh

    def initialize(self) -> None:
        with self._exclusive():
            self._run_with_fallback(lambda display: display.initialize())

    def display(self, image: Image.Image) -> None:
        with self._exclusive():
            frame = image.convert("1", dither=Image.Dither.NONE)
            frame.info.update(image.info)
            if frame.size != (400, 300):
                raise ValueError("Display image must be exactly 400x300 pixels.")
            refresh_mode = str(frame.info.get("refresh_mode", "full")).lower()
            if refresh_mode == "partial" and not self.supports_partial_refresh:
                logger.warning("Partial refresh non supportato; uso full refresh")
                refresh_mode = "full"
            if refresh_mode == "fast" and not self.supports_fast_refresh:
                logger.warning("Fast refresh non supportato; uso full refresh")
                refresh_mode = "full"
            if (
                refresh_mode == "partial"
                and self._partial_refresh_count >= MAX_CONSECUTIVE_PARTIAL_REFRESHES
            ):
                logger.warning(
                    "Forzo un full refresh dopo %s aggiornamenti parziali",
                    self._partial_refresh_count,
                )
                refresh_mode = "full"
            frame.info["refresh_mode"] = refresh_mode
            new_hash = hashlib.sha256(frame.tobytes()).hexdigest()
            force_full_refresh = bool(frame.info.get("force_full_refresh"))
            self.previous_hash = self.last_hash
            self.new_hash = new_hash
            if new_hash == self.last_hash and not force_full_refresh:
                self.last_result = "skipped-unchanged"
                self.last_refresh_mode = "skipped"
                logger.info(
                    "Display update skipped: old_hash=%s new_hash=%s result=%s",
                    self.previous_hash,
                    new_hash,
                    self.last_result,
                )
                return
            try:
                self._run_with_fallback(lambda display: display.display(frame))
            except Exception as error:
                self.last_result = "error"
                self.last_error = str(error)
                logger.exception(
                    "Display update failed: old_hash=%s new_hash=%s",
                    self.previous_hash,
                    new_hash,
                )
                raise
            self.last_hash = new_hash
            self._persist_hash(new_hash)
            self.last_result = "updated"
            self.last_refresh_mode = refresh_mode
            if refresh_mode == "partial":
                self._partial_refresh_count += 1
            elif refresh_mode == "full":
                self._partial_refresh_count = 0
            self.last_error = None
            self.last_update_at = datetime.now(UTC).isoformat()
            logger.info(
                "Display updated: old_hash=%s new_hash=%s result=%s",
                self.previous_hash,
                new_hash,
                self.last_result,
            )

    def clear(self) -> None:
        with self._exclusive():
            self._run_with_fallback(lambda display: display.clear())
            self.previous_hash = self.last_hash
            self.new_hash = hashlib.sha256(
                Image.new("1", (400, 300), color=255).tobytes()
            ).hexdigest()
            self.last_hash = self.new_hash
            self._persist_hash(self.new_hash)
            self.last_result = "cleared"
            self.last_refresh_mode = "full"
            self._partial_refresh_count = 0
            self.last_error = None
            self.last_update_at = datetime.now(UTC).isoformat()

    def sleep(self) -> None:
        with self._exclusive():
            self._run_with_fallback(lambda display: display.sleep())

    def close(self) -> None:
        with self._exclusive():
            self._run_with_fallback(lambda display: display.close())

    def _run_with_fallback(self, operation: Callable[[DisplayPort], None]) -> None:
        try:
            operation(self._delegate)
        except Exception as error:
            if self._fallback_display is None:
                raise

            failed_display = self._delegate
            try:
                failed_display.close()
            except Exception:
                logger.warning("Could not close failed display", exc_info=True)

            self._delegate = self._fallback_display
            self._fallback_display = None
            self.mode = "mock"
            self.driver_name = "MockDisplay"
            self.fallback_reason = str(error)
            if error.__cause__ is not None:
                self.fallback_reason += f": {error.__cause__}"
            self._hash_path = self._lock_path.with_name("display-mock.sha256")
            self.last_hash = self._load_hash()
            self._partial_refresh_count = 0
            logger.warning(
                "Display hardware failed; switching to MockDisplay: %s", error
            )
            operation(self._delegate)

    def _exclusive(self) -> _DisplayLock:
        return _DisplayLock(self._thread_lock, self._process_lock)

    def _load_hash(self) -> str | None:
        try:
            value = self._hash_path.read_text(encoding="ascii").strip()
        except FileNotFoundError:
            return None
        except OSError:
            logger.warning("Could not read persisted display hash", exc_info=True)
            return None
        if len(value) == 64 and all(
            character in "0123456789abcdef" for character in value
        ):
            return value
        logger.warning("Ignoring invalid persisted display hash")
        return None

    def _persist_hash(self, value: str) -> None:
        temporary_path: Path | None = None
        try:
            self._hash_path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(
                mode="w", encoding="ascii", dir=self._hash_path.parent, delete=False
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(value + "\n")
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, self._hash_path)
        except OSError:
            logger.warning("Could not persist display hash", exc_info=True)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


class _DisplayLock:
    def __init__(self, thread_lock: threading.Lock, process_lock: FileLock) -> None:
        self._thread_lock = thread_lock
        self._process_lock = process_lock

    def __enter__(self) -> _DisplayLock:
        if not self._thread_lock.acquire(blocking=False):
            raise DisplayBusyError("A display update is already in progress.")
        try:
            self._process_lock.acquire(timeout=0)
        except Timeout as error:
            self._thread_lock.release()
            raise DisplayBusyError("Another process holds the display lock.") from error
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._process_lock.release()
        self._thread_lock.release()
