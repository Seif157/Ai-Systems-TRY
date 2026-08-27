"""Required-mode synthetic PostgreSQL audit-storage verification."""

import asyncio
import os
import selectors
from collections.abc import Coroutine
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from erp_ai.application.audit import ApplicationAuditEvent
from erp_ai.capabilities import DataClassification
from erp_ai.infrastructure.postgres_audit import (
    AuditDatabaseKind,
    AuditStorageConflict,
    AuditStorageUnavailable,
    ControlAuditDatabaseConfig,
    CustomerAuditDatabaseRoute,
    PostgresAgentAuditSink,
    PostgresApplicationAuditSink,
    PostgresToolAuditSink,
    StaticAuditDatabaseConfig,
    StaticAuditDatabaseRouter,
)
from erp_ai.infrastructure.postgres_audit.migrations import (
    grant_writer_role,
    provision_identity,
    run_migrations,
)
from erp_ai.orchestration.audit import AgentAuditEvent
from erp_ai.tools.audit import ToolAuditEvent

pytestmark = pytest.mark.postgres


def _run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    if os.name == "nt":

        def selector_loop() -> asyncio.SelectorEventLoop:
            return asyncio.SelectorEventLoop(selectors.SelectSelector())

        with asyncio.Runner(loop_factory=selector_loop) as runner:
            return runner.run(coroutine)
    return asyncio.run(coroutine)


def _required() -> str:
    dsn = os.getenv("ERP_AI_TEST_AUDIT_ADMIN_DSN")
    required = os.getenv("ERP_AI_REQUIRE_AUDIT_POSTGRES_TESTS") == "1"
    if not dsn:
        if required:
            pytest.fail("required audit PostgreSQL DSN is missing")
        pytest.skip("audit PostgreSQL tests are opt-in")
    return dsn


async def _prepare(admin_dsn: str) -> tuple[StaticAuditDatabaseConfig, list[str]]:
    suffix = uuid4().hex[:10]
    databases = [f"audit_control_{suffix}", f"audit_a_{suffix}", f"audit_b_{suffix}"]
    writers = [f"audit_app_{suffix}", f"audit_customer_{suffix}"]
    owners = [f"audit_owner_{index}_{suffix}" for index in range(3)]
    async with await psycopg.AsyncConnection.connect(admin_dsn, autocommit=True) as admin:
        for role in writers:
            await admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD 'synthetic_writer'").format(
                    sql.Identifier(role)
                )
            )
        for owner in owners:
            await admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD 'synthetic_owner'").format(
                    sql.Identifier(owner)
                )
            )
        for database, owner in zip(databases, owners, strict=True):
            await admin.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(database), sql.Identifier(owner)
                )
            )

    def dsn(database: str, role: str, password: str) -> str:
        values = conninfo_to_dict(admin_dsn)
        values.update(dbname=database, user=role, password=password)
        return make_conninfo(**values)

    for index, database in enumerate(databases):
        kind = AuditDatabaseKind.CONTROL if index == 0 else AuditDatabaseKind.CUSTOMER
        owner_dsn = dsn(database, owners[index], "synthetic_owner")
        async with await psycopg.AsyncConnection.connect(owner_dsn) as connection:
            await run_migrations(
                connection,
                kind=kind,
                expected_database_name=database,
                expected_migration_owner=owners[index],
            )
            await provision_identity(
                connection,
                kind=kind,
                database_identity=f"identity_{index}_{suffix}",
                customer_environment_id=None if index == 0 else f"customer_{index}",
            )
            await grant_writer_role(
                connection, kind=kind, writer_role=writers[0 if index == 0 else 1]
            )

    return StaticAuditDatabaseConfig(
        control=ControlAuditDatabaseConfig(
            writer_dsn=dsn(databases[0], writers[0], "synthetic_writer"),
            migration_dsn=dsn(databases[0], owners[0], "synthetic_owner"),
            expected_database_name=databases[0],
            expected_database_identity=f"identity_0_{suffix}",
            writer_role=writers[0],
        ),
        customers=tuple(
            CustomerAuditDatabaseRoute(
                customer_environment_id=f"customer_{index}",
                writer_dsn=dsn(databases[index], writers[1], "synthetic_writer"),
                migration_dsn=dsn(databases[index], owners[index], "synthetic_owner"),
                expected_database_name=databases[index],
                expected_database_identity=f"identity_{index}_{suffix}",
                writer_role=writers[1],
            )
            for index in (1, 2)
        ),
        minimum_pool_size=0,
    ), databases


async def _exercise() -> None:
    admin_dsn = _required()
    config, databases = await _prepare(admin_dsn)
    router = StaticAuditDatabaseRouter(config)
    await router.open()
    try:
        request = f"request_{uuid4().hex}"
        application = ApplicationAuditEvent(
            request_id=request,
            stage="orchestration",
            outcome="success",
            internal_reason="completed",
        )
        agent = AgentAuditEvent(
            request_id=request,
            customer_environment_id="customer_1",
            user_id="user_synthetic",
            purpose="test",
            outcome="success",
            internal_reason="completed",
        )
        tool = ToolAuditEvent(
            request_id=request,
            customer_environment_id="customer_1",
            user_id="user_synthetic",
            tool_name="synthetic_read",
            tool_version="1.0.0",
            audit_action="synthetic.read",
            data_classification=DataClassification.INTERNAL,
            outcome="success",
            internal_reason="completed",
            purpose="test",
        )
        app_sink = PostgresApplicationAuditSink(router, config)
        agent_sink = PostgresAgentAuditSink(router, config)
        tool_sink = PostgresToolAuditSink(router, config)
        await app_sink.record(application)
        await agent_sink.record(agent)
        await tool_sink.record(tool)
        await app_sink.record(application)
        await agent_sink.record(agent)
        await tool_sink.record(tool)
        with pytest.raises(AuditStorageConflict):
            await app_sink.record(application.model_copy(update={"outcome": "failure"}))
        with pytest.raises(AuditStorageConflict):
            await agent_sink.record(agent.model_copy(update={"outcome": "failure"}))
        with pytest.raises(AuditStorageConflict):
            await tool_sink.record(tool.model_copy(update={"outcome": "failure"}))
        await agent_sink.record(agent.model_copy(update={"customer_environment_id": "customer_2"}))

        forbidden = (
            "SELECT count(*) FROM erp_ai_audit.agent_events",
            "UPDATE erp_ai_audit.agent_events SET outcome='failure'",
            "DELETE FROM erp_ai_audit.agent_events",
            "CREATE TABLE erp_ai_audit.forbidden(value integer)",
        )
        for statement in forbidden:
            async with (
                router.customer_pool("customer_1").connection() as connection,
                connection.transaction(),
            ):
                await connection.execute(
                    "SELECT set_config('erp_ai_audit.customer_environment_id','customer_1',true)"
                )
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    await connection.execute(statement)
        async with (
            router.customer_pool("customer_1").connection() as connection,
            connection.transaction(),
        ):
            await connection.execute(
                "SELECT set_config('erp_ai_audit.customer_environment_id','customer_1',true)"
            )
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                await connection.execute(
                    "INSERT INTO erp_ai_audit.agent_events"
                    "(request_id,customer_environment_id,user_id,purpose,action,outcome,"
                    "internal_reason,event_digest) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        "cross_customer_request",
                        "customer_2",
                        "user_synthetic",
                        "test",
                        "agent.chat",
                        "success",
                        "completed",
                        "0" * 64,
                    ),
                )
    finally:
        await router.close()

    await router.open()
    try:
        await PostgresApplicationAuditSink(router, config).record(application)
    finally:
        await router.close()

    expected = ((1, None, None), (None, 1, 1), (None, 1, 0))
    for database, counts in zip(databases, expected, strict=True):
        admin_values = conninfo_to_dict(admin_dsn)
        admin_values["dbname"] = database
        async with await psycopg.AsyncConnection.connect(
            make_conninfo(**admin_values)
        ) as connection:
            application_table = await (
                await connection.execute("SELECT to_regclass('erp_ai_audit.application_events')")
            ).fetchone()
            agent_table = await (
                await connection.execute("SELECT to_regclass('erp_ai_audit.agent_events')")
            ).fetchone()
            tool_table = await (
                await connection.execute("SELECT to_regclass('erp_ai_audit.tool_events')")
            ).fetchone()
            assert (
                application_table[0] is not None,
                agent_table[0] is not None,
                tool_table[0] is not None,
            ) == (
                counts[0] is not None,
                counts[1] is not None,
                counts[2] is not None,
            ), database
            for table, count in zip(
                ("application_events", "agent_events", "tool_events"), counts, strict=True
            ):
                if count is not None:
                    row = await (
                        await connection.execute(
                            sql.SQL("SELECT count(*) FROM erp_ai_audit.{}").format(
                                sql.Identifier(table)
                            )
                        )
                    ).fetchone()
                    assert row == (count,)

    async with await psycopg.AsyncConnection.connect(
        config.customers[1].migration_dsn.get_secret_value()
    ) as connection:
        await connection.execute(
            "ALTER TABLE erp_ai_audit.tool_events ALTER COLUMN purpose TYPE text"
        )
        await connection.commit()
    drifted = StaticAuditDatabaseRouter(config)
    with pytest.raises(AuditStorageUnavailable):
        await drifted.open()


def test_live_postgres_audit_storage() -> None:
    _run(_exercise())
