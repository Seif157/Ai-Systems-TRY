"""Explicit-lifecycle pools dedicated exclusively to audit storage."""

import asyncio
from typing import Protocol, runtime_checkable

from psycopg_pool import AsyncConnectionPool

from erp_ai.infrastructure.postgres_audit.config import StaticAuditDatabaseConfig
from erp_ai.infrastructure.postgres_audit.contracts import (
    AuditDatabaseKind,
    verify_database_contract,
)
from erp_ai.infrastructure.postgres_audit.errors import AuditStorageUnavailable


@runtime_checkable
class AuditDatabaseRouter(Protocol):
    def control_pool(self) -> AsyncConnectionPool: ...
    def customer_pool(self, customer_environment_id: str) -> AsyncConnectionPool: ...


class StaticAuditDatabaseRouter:
    __slots__ = ("_config", "_control", "_customers", "_lifecycle_lock", "_started")

    def __init__(self, config: StaticAuditDatabaseConfig) -> None:
        self._config = StaticAuditDatabaseConfig.model_validate(
            config.model_dump(mode="python"), strict=True
        )
        self._control: AsyncConnectionPool | None = None
        self._customers: dict[str, AsyncConnectionPool] = {}
        self._started = False
        self._lifecycle_lock = asyncio.Lock()

    def _pool(self, dsn: str) -> AsyncConnectionPool:
        return AsyncConnectionPool(
            conninfo=dsn,
            min_size=self._config.minimum_pool_size,
            max_size=self._config.maximum_pool_size,
            timeout=self._config.connection_timeout_seconds,
            open=False,
            kwargs={"autocommit": False},
        )

    async def open(self) -> None:
        async with self._lifecycle_lock:
            await self._open_locked()

    async def _open_locked(self) -> None:
        if self._started:
            return
        control = self._pool(self._config.control.writer_dsn.get_secret_value())
        customers = {
            r.customer_environment_id: self._pool(r.writer_dsn.get_secret_value())
            for r in self._config.customers
        }
        pools = (control, *customers.values())
        try:
            for pool in pools:
                await pool.open(wait=True)
            async with control.connection() as connection:
                await verify_database_contract(
                    connection,
                    expected_name=self._config.control.expected_database_name,
                    expected_identity=self._config.control.expected_database_identity,
                    expected_kind=AuditDatabaseKind.CONTROL,
                    expected_customer=None,
                    expected_role=self._config.control.writer_role,
                )
            for route in self._config.customers:
                async with customers[route.customer_environment_id].connection() as connection:
                    await verify_database_contract(
                        connection,
                        expected_name=route.expected_database_name,
                        expected_identity=route.expected_database_identity,
                        expected_kind=AuditDatabaseKind.CUSTOMER,
                        expected_customer=route.customer_environment_id,
                        expected_role=route.writer_role,
                    )
        except asyncio.CancelledError:
            for pool in pools:
                await pool.close()
            raise
        except Exception:
            for pool in pools:
                await pool.close()
            raise AuditStorageUnavailable("audit database pools are unavailable") from None
        self._control, self._customers, self._started = control, customers, True

    async def close(self) -> None:
        async with self._lifecycle_lock:
            await self._close_locked()

    async def _close_locked(self) -> None:
        pools = (() if self._control is None else (self._control,)) + tuple(
            self._customers.values()
        )
        for pool in pools:
            await pool.close()
        self._control, self._customers, self._started = None, {}, False

    def control_pool(self) -> AsyncConnectionPool:
        if not self._started or self._control is None:
            raise AuditStorageUnavailable("audit database router is unavailable")
        return self._control

    def customer_pool(self, customer_environment_id: str) -> AsyncConnectionPool:
        if not self._started:
            raise AuditStorageUnavailable("audit database router is unavailable")
        try:
            return self._customers[customer_environment_id]
        except KeyError:
            raise AuditStorageUnavailable("audit database route is unavailable") from None
