"""Explicit-lifecycle static routing to separate customer and privilege pools."""

import asyncio
from enum import Enum
from typing import Protocol, runtime_checkable

from psycopg_pool import AsyncConnectionPool

from erp_ai.context.models import Identifier
from erp_ai.infrastructure.postgres.config import StaticKnowledgeDatabaseConfig
from erp_ai.infrastructure.postgres.errors import KnowledgeStorageUnavailable


class KnowledgeDatabaseAccess(str, Enum):
    READER = "reader"
    PUBLISHER = "publisher"
    MIGRATION = "migration"


@runtime_checkable
class KnowledgeDatabaseRouter(Protocol):
    def pool(
        self, customer_environment_id: Identifier, access: KnowledgeDatabaseAccess
    ) -> AsyncConnectionPool: ...


class StaticKnowledgeDatabaseRouter:
    """Trusted startup mapping; never derives connection data from a customer identifier."""

    __slots__ = ("_config", "_pools", "_started")

    def __init__(self, config: StaticKnowledgeDatabaseConfig) -> None:
        self._config = config
        self._pools: dict[tuple[str, KnowledgeDatabaseAccess], AsyncConnectionPool] = {}
        self._started = False

    async def open(self) -> None:
        if self._started:
            return
        asyncio.get_running_loop()
        pools: dict[tuple[str, KnowledgeDatabaseAccess], AsyncConnectionPool] = {}
        for route in self._config.routes:
            dsns = {
                KnowledgeDatabaseAccess.READER: route.reader_dsn,
                KnowledgeDatabaseAccess.PUBLISHER: route.publisher_dsn,
                KnowledgeDatabaseAccess.MIGRATION: route.migration_dsn,
            }
            for access, secret in dsns.items():
                pools[(route.customer_environment_id, access)] = AsyncConnectionPool(
                    conninfo=secret.get_secret_value(),
                    min_size=self._config.minimum_pool_size,
                    max_size=self._config.maximum_pool_size,
                    open=False,
                    kwargs={"autocommit": False},
                )
        try:
            for pool in pools.values():
                await pool.open(wait=True)
        except asyncio.CancelledError:
            for pool in pools.values():
                await pool.close()
            raise
        except Exception:
            for pool in pools.values():
                await pool.close()
            raise KnowledgeStorageUnavailable("knowledge database pools are unavailable") from None
        self._pools = pools
        self._started = True

    async def close(self) -> None:
        for pool in self._pools.values():
            await pool.close()
        self._pools = {}
        self._started = False

    def pool(
        self, customer_environment_id: Identifier, access: KnowledgeDatabaseAccess
    ) -> AsyncConnectionPool:
        if not self._started:
            raise KnowledgeStorageUnavailable("knowledge database router is unavailable")
        try:
            return self._pools[(customer_environment_id, access)]
        except KeyError:
            raise KnowledgeStorageUnavailable("knowledge database route is unavailable") from None
