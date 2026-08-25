"""Explicit-lifecycle static routing for isolated customer ERP readers."""

import asyncio
from typing import Protocol, runtime_checkable

from psycopg_pool import AsyncConnectionPool

from erp_ai.context.models import Identifier
from erp_ai.infrastructure.postgres_erp.config import StaticErpDatabaseConfig
from erp_ai.infrastructure.postgres_erp.contract import verify_reader_contract
from erp_ai.infrastructure.postgres_erp.errors import ErpReadUnavailable


@runtime_checkable
class ErpDatabaseRouter(Protocol):
    def pool(self, customer_environment_id: Identifier) -> AsyncConnectionPool: ...


class StaticErpDatabaseRouter:
    """Trusted static map; customer values are lookup keys, never DSN components."""

    __slots__ = ("_config", "_pools", "_started")

    def __init__(self, config: StaticErpDatabaseConfig) -> None:
        self._config = config
        self._pools: dict[str, AsyncConnectionPool] = {}
        self._started = False

    async def open(self) -> None:  # pragma: no cover - opt-in PostgreSQL boundary
        if self._started:
            return
        asyncio.get_running_loop()
        pools: dict[str, AsyncConnectionPool] = {}
        try:
            for route in self._config.routes:
                pool = AsyncConnectionPool(
                    conninfo=route.reader_dsn.get_secret_value(),
                    min_size=self._config.minimum_pool_size,
                    max_size=self._config.maximum_pool_size,
                    open=False,
                    kwargs={"autocommit": False},
                )
                pools[route.customer_environment_id] = pool
                await pool.open(wait=True)
                async with pool.connection() as connection:
                    await verify_reader_contract(connection, route.expected_database_name)
        except asyncio.CancelledError:
            for pool in pools.values():
                await pool.close()
            raise
        except Exception:
            for pool in pools.values():
                await pool.close()
            raise ErpReadUnavailable("ERP database routes are unavailable") from None
        self._pools = pools
        self._started = True

    async def close(self) -> None:  # pragma: no cover - opt-in PostgreSQL boundary
        for pool in self._pools.values():
            await pool.close()
        self._pools = {}
        self._started = False

    def pool(self, customer_environment_id: Identifier) -> AsyncConnectionPool:
        if not self._started:
            raise ErpReadUnavailable("ERP database router is unavailable")
        try:
            return self._pools[customer_environment_id]
        except KeyError:
            raise ErpReadUnavailable("ERP database route is unavailable") from None

    @property
    def config(self) -> StaticErpDatabaseConfig:
        return self._config
