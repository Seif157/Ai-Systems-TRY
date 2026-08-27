"""Per-runtime deterministic ownership of external resources."""

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
from threading import Lock
from typing import Protocol, runtime_checkable

from erp_ai.infrastructure.erp_trust import ErpTrustHttpClient
from erp_ai.infrastructure.postgres_audit import StaticAuditDatabaseRouter

from .errors import RuntimeLifecycleError
from .models import RuntimeState


@runtime_checkable
class ProviderRuntimeLifecycle(Protocol):
    """Mandatory externally supplied lifecycle for every approved provider resource."""

    async def open(self) -> None: ...
    async def close(self) -> None: ...


@dataclass(slots=True, init=False)
class ProviderLifecycleLease:
    """Concurrency-safe, single-runtime ownership lease with no global registry."""

    _lifecycle: ProviderRuntimeLifecycle = field(repr=False)
    _lock: Lock = field(repr=False)
    _token: object | None = field(default=None, repr=False)
    _committed: bool = field(default=False, repr=False)

    def __init__(self, lifecycle: ProviderRuntimeLifecycle) -> None:
        if not isinstance(lifecycle, ProviderRuntimeLifecycle):
            raise TypeError("provider runtime lifecycle is required")
        self._lifecycle = lifecycle
        self._lock = Lock()
        self._token = None
        self._committed = False

    @property
    def lifecycle(self) -> ProviderRuntimeLifecycle:
        return self._lifecycle

    def claim(self) -> object:
        token = object()
        with self._lock:
            if self._token is not None or self._committed:
                raise RuntimeLifecycleError("provider lifecycle ownership is unavailable")
            self._token = token
        return token

    def release(self, token: object) -> None:
        with self._lock:
            if self._token is not token or self._committed:
                raise RuntimeLifecycleError("provider lifecycle ownership is unavailable")
            self._token = None

    def commit(self, token: object) -> None:
        with self._lock:
            if self._token is not token or self._committed:
                raise RuntimeLifecycleError("provider lifecycle ownership is unavailable")
            self._committed = True


@dataclass(slots=True, init=False)
class ProductionRuntimeLifecycle:
    _audit: StaticAuditDatabaseRouter = field(repr=False)
    _erp: ErpTrustHttpClient = field(repr=False)
    _providers: ProviderRuntimeLifecycle = field(repr=False)
    _state: RuntimeState
    _lock: asyncio.Lock = field(repr=False)
    _rolled_back: bool = field(repr=False)
    _shutdown_attempted: bool = field(repr=False)

    def __init__(
        self,
        audit: StaticAuditDatabaseRouter,
        erp: ErpTrustHttpClient,
        providers: ProviderRuntimeLifecycle,
    ) -> None:
        if not isinstance(providers, ProviderRuntimeLifecycle):
            raise TypeError("provider runtime lifecycle is required")
        self._audit, self._erp, self._providers = audit, erp, providers
        self._state, self._lock = RuntimeState.CREATED, asyncio.Lock()
        self._rolled_back = False
        self._shutdown_attempted = False

    @property
    def state(self) -> RuntimeState:
        return self._state

    async def startup(self) -> None:
        async with self._lock:
            if self._state is not RuntimeState.CREATED:
                raise RuntimeLifecycleError("runtime startup is unavailable")
            self._state = RuntimeState.STARTING
            opened: list[object] = []
            try:
                opened.append(self._audit)
                await self._audit.open()
                opened.append(self._erp)
                await self._erp.open()
                opened.append(self._providers)
                await self._providers.open()
            except BaseException as error:
                await self._reverse_close(opened)
                self._rolled_back = True
                self._state = RuntimeState.FAILED
                if isinstance(error, asyncio.CancelledError):
                    raise
                raise RuntimeLifecycleError("runtime startup failed") from None
            self._state = RuntimeState.READY

    async def shutdown(self) -> None:
        async with self._lock:
            if self._shutdown_attempted or self._state is RuntimeState.CLOSED:
                raise RuntimeLifecycleError("runtime shutdown is unavailable")
            self._shutdown_attempted = True
            if self._state is RuntimeState.CREATED:
                self._state = RuntimeState.CLOSED
                return
            if self._rolled_back:
                self._state = RuntimeState.CLOSED
                return
            self._state = RuntimeState.STOPPING
            errors: list[BaseException] = []
            cancellation: asyncio.CancelledError | None = None
            for resource in (self._providers, self._erp, self._audit):
                try:
                    await resource.close()
                except asyncio.CancelledError as error:
                    cancellation = error
                except BaseException as error:
                    errors.append(error)
            self._state = (
                RuntimeState.CLOSED if not errors and cancellation is None else RuntimeState.FAILED
            )
            if cancellation is not None:
                raise cancellation
            if errors:
                raise RuntimeLifecycleError("runtime shutdown failed") from None

    @staticmethod
    async def _reverse_close(opened: list[object]) -> None:
        for resource in reversed(opened):
            with suppress(BaseException):
                await resource.close()  # type: ignore[attr-defined]
