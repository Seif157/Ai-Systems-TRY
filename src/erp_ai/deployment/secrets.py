"""Fixed-root, bounded file-backed production secret boundary."""

import os
import stat
from pathlib import Path
from typing import Final

from pydantic import SecretStr

from .config import SecretReference

SECRET_ROOT: Final = Path("/run/secrets/erp-ai")
MAXIMUM_TEXT_SECRET_BYTES: Final = 16_384
MAXIMUM_BINARY_SECRET_BYTES: Final = 1_048_576


class FileSecretProvider:
    __slots__ = ("_root",)

    def __init__(self, root: Path = SECRET_ROOT) -> None:
        self._root = root

    def __repr__(self) -> str:
        return "FileSecretProvider()"

    def _approved_path(self, reference: SecretReference) -> Path:
        candidate = Path(reference)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("secret is unavailable")
        try:
            root = self._root.resolve(strict=True)
            resolved = (root / candidate).resolve(strict=True)
            resolved.relative_to(root)
            info = resolved.stat()
            if not stat.S_ISREG(info.st_mode):
                raise ValueError
            return resolved
        except Exception:
            raise ValueError("secret is unavailable") from None

    def read_bytes(self, reference: SecretReference) -> bytes:
        path = self._approved_path(reference)
        try:
            descriptor = os.open(
                path,
                os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0),
            )
            try:
                info = os.fstat(descriptor)
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError
                raw = os.read(descriptor, MAXIMUM_BINARY_SECRET_BYTES + 1)
            finally:
                os.close(descriptor)
            if not raw or len(raw) > MAXIMUM_BINARY_SECRET_BYTES:
                raise ValueError
            return raw
        except Exception:
            raise ValueError("secret is unavailable") from None

    def materialized_path(self, reference: SecretReference) -> Path:
        """Return a validated mounted path for APIs that require an OS file name."""

        return self._approved_path(reference)

    def read_text(self, reference: SecretReference) -> SecretStr:
        raw = self.read_bytes(reference)
        if len(raw) > MAXIMUM_TEXT_SECRET_BYTES or b"\x00" in raw:
            raise ValueError("secret is unavailable")
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeError:
            raise ValueError("secret is unavailable") from None
        if text.endswith("\r\n"):
            text = text[:-2]
        elif text.endswith("\n"):
            text = text[:-1]
        if not text or any(ord(character) < 0x20 or ord(character) == 0x7F for character in text):
            raise ValueError("secret is unavailable")
        return SecretStr(text)
