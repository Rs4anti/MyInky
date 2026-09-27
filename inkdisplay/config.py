"""Application configuration and startup validation."""

from __future__ import annotations

import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv


class ConfigurationError(ValueError):
    """Raised when application configuration is invalid."""


@dataclass(frozen=True)
class AppSettings:
    host: str = "0.0.0.0"
    port: int = 5000
    timezone: str = "Europe/Rome"
    display_mode: str = "mock"
    data_dir: Path = Path("data")
    secret_key: str = ""

    @classmethod
    def from_environment(cls) -> AppSettings:
        """Read bootstrap settings from environment variables."""
        load_dotenv()
        raw_port = os.getenv("INKDISPLAY_PORT", "5000")
        try:
            port = int(raw_port)
        except ValueError as error:
            raise ConfigurationError("INKDISPLAY_PORT must be an integer.") from error

        configured_key = os.getenv("INKDISPLAY_SECRET_KEY")
        return cls(
            host=os.getenv("INKDISPLAY_HOST", "0.0.0.0"),
            port=port,
            timezone=os.getenv("INKDISPLAY_TIMEZONE", "Europe/Rome"),
            display_mode=os.getenv("INKDISPLAY_DISPLAY", "mock").lower(),
            data_dir=Path(os.getenv("INKDISPLAY_DATA_DIR", "data")),
            secret_key=configured_key or secrets.token_urlsafe(32),
        )

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> AppSettings:
        """Build and validate settings from Flask-style configuration keys."""
        defaults = cls.from_environment()
        raw_port = values.get("PORT", defaults.port)
        if not isinstance(raw_port, (int, str)):
            raise ConfigurationError("PORT must be an integer.")
        try:
            port = int(raw_port)
        except ValueError as error:
            raise ConfigurationError("PORT must be an integer.") from error

        raw_data_dir = values.get("DATA_DIR", defaults.data_dir)
        if not isinstance(raw_data_dir, (str, Path)):
            raise ConfigurationError("DATA_DIR must be a filesystem path.")
        settings = cls(
            host=str(values.get("HOST", defaults.host)),
            port=port,
            timezone=str(values.get("TIMEZONE", defaults.timezone)),
            display_mode=str(values.get("DISPLAY_MODE", defaults.display_mode)).lower(),
            data_dir=Path(raw_data_dir),
            secret_key=str(values.get("SECRET_KEY", defaults.secret_key)),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not self.host.strip():
            raise ConfigurationError("INKDISPLAY_HOST must not be empty.")
        if not 1 <= self.port <= 65535:
            raise ConfigurationError("INKDISPLAY_PORT must be between 1 and 65535.")
        if self.display_mode not in {"mock", "hardware", "waveshare"}:
            raise ConfigurationError(
                "INKDISPLAY_DISPLAY must be 'mock' or 'waveshare'."
            )
        if not self.secret_key:
            raise ConfigurationError("A non-empty Flask secret key is required.")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ConfigurationError(
                f"Unknown timezone {self.timezone!r}; use an IANA timezone "
                "such as Europe/Rome."
            ) from error

    def as_flask_config(self) -> dict[str, object]:
        return {
            "HOST": self.host,
            "PORT": self.port,
            "TIMEZONE": self.timezone,
            "DISPLAY_MODE": self.display_mode,
            "DATA_DIR": self.data_dir,
            "SECRET_KEY": self.secret_key,
            "MAX_CONTENT_LENGTH": 10 * 1024 * 1024,
            "SESSION_COOKIE_HTTPONLY": True,
            "SESSION_COOKIE_SAMESITE": "Lax",
        }
