"""Fernet-encrypted local secrets backed by a private filesystem key."""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class SecretStore:
    def __init__(self, data_dir: Path) -> None:
        key_dir = data_dir / "secrets"
        key_dir.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            key_dir.chmod(0o700)
        self._key_path = key_dir / "weather-fernet.key"
        self._fernet = Fernet(self._load_or_create_key())

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError) as error:
            raise ValueError(
                "The stored weather API key cannot be decrypted."
            ) from error

    def _load_or_create_key(self) -> bytes:
        try:
            with self._key_path.open("xb") as key_file:
                key = Fernet.generate_key()
                key_file.write(key)
                key_file.flush()
                os.fsync(key_file.fileno())
            self._restrict_permissions()
            return key
        except FileExistsError:
            key = self._key_path.read_bytes().strip()
            Fernet(key)
            self._restrict_permissions()
            return key

    def _restrict_permissions(self) -> None:
        if os.name != "nt":
            self._key_path.chmod(0o600)
