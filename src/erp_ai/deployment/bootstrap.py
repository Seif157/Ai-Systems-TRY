"""Explicit process entrypoint bootstrap for Alpine system-libpq discovery."""

import ctypes
import ctypes.util
import importlib
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any


@contextmanager
def _system_libpq_discovery() -> Iterator[None]:
    """Bridge Alpine's SONAME to Python's glibc-oriented library discovery."""

    original = ctypes.util.find_library
    patched = sys.platform == "linux" and original("pq") is None
    if patched:
        try:
            ctypes.CDLL("libpq.so.5")
        except OSError:
            raise RuntimeError("required runtime library is unavailable") from None

        def find_library(name: str) -> str | None:
            return "libpq.so.5" if name == "pq" else original(name)

        ctypes.util.find_library = find_library
    try:
        yield
    finally:
        if patched:
            ctypes.util.find_library = original


def _invoke(module_name: str, function_name: str) -> None:
    with _system_libpq_discovery():
        operation: Callable[[], Any] = getattr(importlib.import_module(module_name), function_name)
    operation()


def serve() -> None:
    _invoke("erp_ai.deployment.launcher", "main")


def migrate_control_audit() -> None:
    _invoke("erp_ai.deployment.admin", "migrate_control_audit")


def migrate_customer_audit() -> None:
    _invoke("erp_ai.deployment.admin", "migrate_customer_audit")


def migrate_customer_knowledge() -> None:
    _invoke("erp_ai.deployment.admin", "migrate_customer_knowledge")


def production_preflight() -> None:
    _invoke("erp_ai.deployment.admin", "production_preflight")
