"""Production PostgreSQL adapters for the three existing audit protocols."""
# ruff: noqa: E501

import asyncio
from typing import Any

from psycopg import AsyncConnection, Error

from erp_ai.application.audit import ApplicationAuditEvent
from erp_ai.infrastructure.postgres_audit.config import (
    RuntimeAuditDatabaseConfig,
    StaticAuditDatabaseConfig,
)
from erp_ai.infrastructure.postgres_audit.contracts import event_digest, validated_event_values
from erp_ai.infrastructure.postgres_audit.errors import (
    AuditStorageConflict,
    AuditStorageUnavailable,
)
from erp_ai.infrastructure.postgres_audit.routing import AuditDatabaseRouter
from erp_ai.orchestration.audit import AgentAuditEvent
from erp_ai.tools.audit import ToolAuditEvent


async def _settings(
    connection: AsyncConnection[tuple[Any, ...]],
    config: RuntimeAuditDatabaseConfig,
    customer: str | None,
) -> None:
    for setting, value in (
        ("statement_timeout", config.statement_timeout_ms),
        ("lock_timeout", config.lock_timeout_ms),
        ("idle_in_transaction_session_timeout", config.idle_transaction_timeout_ms),
    ):
        await connection.execute("SELECT set_config(%s,%s,true)", (setting, f"{value}ms"))
    if customer is not None:
        await connection.execute(
            "SELECT set_config('erp_ai_audit.customer_environment_id',%s,true)", (customer,)
        )


async def _verify_write_binding(
    connection: AsyncConnection[tuple[Any, ...]],
    *,
    expected_database: str,
    expected_role: str,
    expected_identity: str,
    expected_kind: str,
    expected_customer: str | None,
) -> None:
    row = await (
        await connection.execute(
            "SELECT current_database(),current_user,database_kind,database_identity,"
            "customer_environment_id FROM erp_ai_audit.database_identity"
        )
    ).fetchall()
    if row != [
        (
            expected_database,
            expected_role,
            expected_kind,
            expected_identity,
            expected_customer,
        )
    ]:
        raise AuditStorageUnavailable("audit storage identity is unavailable")


async def _insert(
    connection: AsyncConnection[tuple[Any, ...]],
    sql: str,
    values: tuple[object, ...],
) -> None:
    await connection.execute(sql, values)


def _translate_driver_error(error: Error) -> AuditStorageUnavailable:
    if error.sqlstate == "P2301":
        return AuditStorageConflict("audit logical slot conflicts")
    return AuditStorageUnavailable("audit storage is unavailable")


class PostgresApplicationAuditSink:
    __slots__ = ("_config", "_router")

    def __init__(
        self,
        router: AuditDatabaseRouter,
        config: RuntimeAuditDatabaseConfig | StaticAuditDatabaseConfig,
    ) -> None:
        self._router = router
        self._config = (
            RuntimeAuditDatabaseConfig.from_static(config)
            if isinstance(config, StaticAuditDatabaseConfig)
            else RuntimeAuditDatabaseConfig.model_validate(
                config.model_dump(mode="python"), strict=True
            )
        )

    async def record(self, event: ApplicationAuditEvent) -> None:
        try:
            validated = ApplicationAuditEvent.model_validate(
                event.model_dump(mode="python"), strict=True
            )
            digest = event_digest(validated)
            route = self._config.control
            async with (
                self._router.control_pool().connection() as connection,
                connection.transaction(),
            ):
                await _settings(connection, self._config, None)
                await _verify_write_binding(
                    connection,
                    expected_database=route.expected_database_name,
                    expected_role=route.writer_role,
                    expected_identity=route.expected_database_identity,
                    expected_kind="control",
                    expected_customer=None,
                )
                await _insert(
                    connection,
                    "INSERT INTO erp_ai_audit.application_events(request_id,stage,outcome,internal_reason,event_digest) VALUES (%s,%s,%s,%s,%s)",
                    (*validated_event_values(validated), digest),
                )
        except asyncio.CancelledError:
            raise
        except AuditStorageConflict:
            raise
        except Error as error:
            raise _translate_driver_error(error) from None
        except Exception:
            raise AuditStorageUnavailable("audit storage is unavailable") from None


class PostgresAgentAuditSink:
    __slots__ = ("_config", "_router")

    def __init__(
        self,
        router: AuditDatabaseRouter,
        config: RuntimeAuditDatabaseConfig | StaticAuditDatabaseConfig,
    ) -> None:
        self._router = router
        self._config = (
            RuntimeAuditDatabaseConfig.from_static(config)
            if isinstance(config, StaticAuditDatabaseConfig)
            else RuntimeAuditDatabaseConfig.model_validate(
                config.model_dump(mode="python"), strict=True
            )
        )

    async def record(self, event: AgentAuditEvent) -> None:
        try:
            validated = AgentAuditEvent.model_validate(event.model_dump(mode="python"), strict=True)
            digest = event_digest(validated)
            route = next(
                route
                for route in self._config.customers
                if route.customer_environment_id == validated.customer_environment_id
            )
            async with (
                self._router.customer_pool(
                    validated.customer_environment_id
                ).connection() as connection,
                connection.transaction(),
            ):
                await _settings(connection, self._config, validated.customer_environment_id)
                await _verify_write_binding(
                    connection,
                    expected_database=route.expected_database_name,
                    expected_role=route.writer_role,
                    expected_identity=route.expected_database_identity,
                    expected_kind="customer",
                    expected_customer=validated.customer_environment_id,
                )
                await _insert(
                    connection,
                    "INSERT INTO erp_ai_audit.agent_events(request_id,customer_environment_id,user_id,purpose,action,outcome,internal_reason,event_digest) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (*validated_event_values(validated), digest),
                )
        except asyncio.CancelledError:
            raise
        except AuditStorageConflict:
            raise
        except Error as error:
            raise _translate_driver_error(error) from None
        except Exception:
            raise AuditStorageUnavailable("audit storage is unavailable") from None


class PostgresToolAuditSink:
    __slots__ = ("_config", "_router")

    def __init__(
        self,
        router: AuditDatabaseRouter,
        config: RuntimeAuditDatabaseConfig | StaticAuditDatabaseConfig,
    ) -> None:
        self._router = router
        self._config = (
            RuntimeAuditDatabaseConfig.from_static(config)
            if isinstance(config, StaticAuditDatabaseConfig)
            else RuntimeAuditDatabaseConfig.model_validate(
                config.model_dump(mode="python"), strict=True
            )
        )

    async def record(self, event: ToolAuditEvent) -> None:
        try:
            validated = ToolAuditEvent.model_validate(event.model_dump(mode="python"), strict=True)
            digest = event_digest(validated)
            route = next(
                route
                for route in self._config.customers
                if route.customer_environment_id == validated.customer_environment_id
            )
            async with (
                self._router.customer_pool(
                    validated.customer_environment_id
                ).connection() as connection,
                connection.transaction(),
            ):
                await _settings(connection, self._config, validated.customer_environment_id)
                await _verify_write_binding(
                    connection,
                    expected_database=route.expected_database_name,
                    expected_role=route.writer_role,
                    expected_identity=route.expected_database_identity,
                    expected_kind="customer",
                    expected_customer=validated.customer_environment_id,
                )
                await _insert(
                    connection,
                    "INSERT INTO erp_ai_audit.tool_events(request_id,customer_environment_id,user_id,tool_name,tool_version,audit_action,data_classification,outcome,internal_reason,purpose,event_digest) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (*validated_event_values(validated), digest),
                )
        except asyncio.CancelledError:
            raise
        except AuditStorageConflict:
            raise
        except Error as error:
            raise _translate_driver_error(error) from None
        except Exception:
            raise AuditStorageUnavailable("audit storage is unavailable") from None
