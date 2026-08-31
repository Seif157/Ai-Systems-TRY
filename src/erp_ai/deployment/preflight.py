"""Read-only deployment preflight contract."""

import asyncio
from typing import Protocol, runtime_checkable


@runtime_checkable
class PreflightCheck(Protocol):
    async def verify(self) -> None: ...


async def run_preflight(checks: tuple[PreflightCheck, ...]) -> None:
    """Run fixed ordered checks once; never sends model or embedding content."""

    for check in checks:
        try:
            await check.verify()
        except asyncio.CancelledError:
            raise
        except Exception:
            raise RuntimeError("deployment preflight failed") from None
