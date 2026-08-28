"""Explicit Laravel provider bundle for injection into provider-neutral runtime composition."""

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
from typing import cast

from erp_ai.capabilities.hr_core import GetMyEmployeeProfileHandler
from erp_ai.capabilities.leave import (
    GetMyLeaveBalancesHandler,
    GetMyLeaveRequestHandler,
    ListMyLeaveRequestsHandler,
)
from erp_ai.runtime.lifecycle import ProviderRuntimeLifecycle
from erp_ai.tools import ReadToolHandler

from .client import LaravelErpReadClient
from .config import LaravelErpReadConfig
from .providers import LaravelHrCoreReadProvider, LaravelLeaveReadProvider


@dataclass(slots=True)
class LaravelProviderLifecycle:
    client: LaravelErpReadClient = field(repr=False)
    downstream: ProviderRuntimeLifecycle = field(repr=False)

    async def open(self) -> None:
        await self.client.open()
        try:
            await self.downstream.open()
        except BaseException:
            with suppress(BaseException):
                await self.client.close()
            raise

    async def close(self) -> None:
        cancellation: asyncio.CancelledError | None = None
        failed = False
        for resource in (self.downstream, self.client):
            try:
                await resource.close()
            except asyncio.CancelledError as error:
                cancellation = error
            except BaseException:
                failed = True
        if cancellation is not None:
            raise cancellation
        if failed:
            raise RuntimeError("provider shutdown failed")


@dataclass(frozen=True, slots=True, init=False)
class LaravelErpReadProviderBundle:
    client: LaravelErpReadClient = field(repr=False)
    handlers: tuple[ReadToolHandler, ...] = field(repr=False)
    lifecycle: LaravelProviderLifecycle = field(repr=False)

    def __init__(
        self,
        config: LaravelErpReadConfig,
        ssl_context: object,
        downstream_lifecycle: ProviderRuntimeLifecycle,
    ) -> None:
        if not isinstance(downstream_lifecycle, ProviderRuntimeLifecycle):
            raise TypeError("downstream provider lifecycle is required")
        client = LaravelErpReadClient(config, ssl_context)  # type: ignore[arg-type]
        hr = LaravelHrCoreReadProvider(client)
        leave = LaravelLeaveReadProvider(client)
        handlers = tuple(
            cast(ReadToolHandler, handler)
            for handler in (
                GetMyEmployeeProfileHandler(hr),
                GetMyLeaveBalancesHandler(leave),
                ListMyLeaveRequestsHandler(leave),
                GetMyLeaveRequestHandler(leave),
            )
        )
        object.__setattr__(self, "client", client)
        object.__setattr__(self, "handlers", handlers)
        object.__setattr__(
            self, "lifecycle", LaravelProviderLifecycle(client, downstream_lifecycle)
        )
