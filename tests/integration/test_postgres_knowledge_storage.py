import asyncio
import hashlib
import os
import selectors
from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.errors import DuplicateObject

from erp_ai.infrastructure.postgres import (
    KnowledgeDatabaseAccess,
    KnowledgeDatabaseRouteConfig,
    PostgresKnowledgeIndexRepository,
    PostgresLexicalKnowledgeRetrievalProvider,
    StaticKnowledgeDatabaseConfig,
    StaticKnowledgeDatabaseRouter,
)
from erp_ai.infrastructure.postgres.errors import (
    KnowledgeDatabaseIdentityError,
    KnowledgeMigrationError,
    KnowledgeStorageUnavailable,
)
from erp_ai.infrastructure.postgres.migrations import (
    MIGRATIONS,
    _migration_bytes,
    grant_runtime_roles,
    provision_database_identity,
    run_migrations,
)
from erp_ai.knowledge import KnowledgeRetrievalRequest
from erp_ai.knowledge.indexing import KnowledgeIndexPublisher, KnowledgePublicationConflict
from tests.unit.test_knowledge_index_publication import bundle, context

ADMIN_DSN = os.environ.get("ERP_AI_TEST_ADMIN_DSN")
REQUIRE_POSTGRES = os.environ.get("ERP_AI_REQUIRE_POSTGRES_TESTS") == "1"
if REQUIRE_POSTGRES and not ADMIN_DSN:
    raise pytest.UsageError(
        "ERP_AI_TEST_ADMIN_DSN is required when ERP_AI_REQUIRE_POSTGRES_TESTS=1"
    )
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not ADMIN_DSN and not REQUIRE_POSTGRES,
        reason="ERP_AI_TEST_ADMIN_DSN is not configured; PostgreSQL tests were not required",
    ),
]

CUSTOMERS = (("customer-a", "erp_ai_test_a"), ("customer-b", "erp_ai_test_b"))
READER_ROLE = "erp_ai_test_reader"
PUBLISHER_ROLE = "erp_ai_test_publisher"
PASSWORD = "synthetic_role_password"


def _run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    if os.name == "nt":

        def selector_loop() -> asyncio.SelectorEventLoop:
            return asyncio.SelectorEventLoop(selectors.SelectSelector())

        with asyncio.Runner(loop_factory=selector_loop) as runner:
            return runner.run(coroutine)
    return asyncio.run(coroutine)


async def _recreate_databases() -> None:
    assert ADMIN_DSN is not None
    connection = await psycopg.AsyncConnection.connect(ADMIN_DSN, autocommit=True)
    try:
        for role in (READER_ROLE, PUBLISHER_ROLE):
            command = sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS").format(
                sql.Identifier(role), sql.Literal(PASSWORD)
            )
            try:
                await connection.execute(command)
            except DuplicateObject:
                await connection.execute(
                    sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS").format(
                        sql.Identifier(role), sql.Literal(PASSWORD)
                    )
                )
        for _, database in CUSTOMERS:
            await connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s",
                (database,),
            )
            await connection.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database))
            )
            await connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
            await connection.execute(
                sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database))
            )
            for role in (READER_ROLE, PUBLISHER_ROLE):
                await connection.execute(
                    sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                        sql.Identifier(database), sql.Identifier(role)
                    )
                )
    finally:
        await connection.close()


def _database_dsn(database: str, *, role: str = "postgres", password: str | None = None) -> str:
    assert ADMIN_DSN is not None
    values: dict[str, str] = {"dbname": database, "user": role}
    if password is not None:
        values["password"] = password
    return make_conninfo(ADMIN_DSN, **values)


async def _provision() -> StaticKnowledgeDatabaseRouter:
    await _recreate_databases()
    routes = []
    for customer, database in CUSTOMERS:
        admin_dsn = _database_dsn(database)
        connection = await psycopg.AsyncConnection.connect(admin_dsn)
        try:
            await run_migrations(connection)
            await run_migrations(connection)
            versions = await (
                await connection.execute(
                    "SELECT current_setting('server_version_num')::integer, "
                    "(SELECT extversion FROM pg_extension WHERE extname='vector')"
                )
            ).fetchone()
            assert versions is not None and versions[0] // 10_000 == 17
            assert versions[1] == "0.8.6"
            await connection.commit()
            await provision_database_identity(connection, customer)
            await provision_database_identity(connection, customer)
            await grant_runtime_roles(
                connection, reader_role=READER_ROLE, publisher_role=PUBLISHER_ROLE
            )
        finally:
            await connection.close()
        routes.append(
            KnowledgeDatabaseRouteConfig(
                customer_environment_id=customer,
                reader_dsn=_database_dsn(database, role=READER_ROLE, password=PASSWORD),
                publisher_dsn=_database_dsn(database, role=PUBLISHER_ROLE, password=PASSWORD),
                migration_dsn=admin_dsn,
            )
        )
    router = StaticKnowledgeDatabaseRouter(
        StaticKnowledgeDatabaseConfig(routes=tuple(routes), minimum_pool_size=0)
    )
    await router.open()
    return router


async def _exercise_storage() -> None:
    router = await _provision()
    try:
        repository_a = PostgresKnowledgeIndexRepository(router, "customer-a")
        publisher_a = KnowledgeIndexPublisher(repository_a)
        prepared = bundle(
            content="Annual leave policy سياسة الإجازات",
            version="12.34.567",
            legal_entities=("entity-a",),
        )
        first = await publisher_a.publish(
            context(), (prepared,), expected_active_generation_id=None
        )
        assert (
            await publisher_a.publish(context(), (prepared,), expected_active_generation_id=None)
            == first
        )
        snapshot = await repository_a.get_active_snapshot(first.scope)
        assert snapshot is not None and snapshot.active_generation_id == first.generation_id

        replacement = await publisher_a.publish(
            context(operation="replace"),
            (
                bundle(
                    content="Updated annual leave policy سياسة الإجازات",
                    version="12.34.567",
                    legal_entities=("entity-a",),
                ),
            ),
            expected_active_generation_id=first.generation_id,
        )
        rollback = await publisher_a.rollback(
            context(operation="rollback"),
            target_generation_id=first.generation_id,
            expected_active_generation_id=replacement.generation_id,
        )
        assert rollback.activated_generation_id == first.generation_id
        bound_snapshot = await repository_a.get_active_snapshot(first.scope)

        failed_plan = publisher_a.build_plan(
            context(operation="invalid-count"), (bundle(content="Must roll back"),)
        )
        failed_plan = failed_plan.model_copy(
            update={
                "manifest": failed_plan.manifest.model_copy(
                    update={"document_count": failed_plan.manifest.document_count + 1}
                )
            }
        )
        with pytest.raises(KnowledgeStorageUnavailable):
            await repository_a.commit_generation(failed_plan, first.generation_id)
        assert (await repository_a.get_active_snapshot(first.scope)) == bound_snapshot

        async def concurrent_publish(operation: str, text: str):
            return await publisher_a.publish(
                context(operation=operation),
                (
                    bundle(
                        content=text,
                        version="12.34.567",
                        legal_entities=("entity-a",),
                    ),
                ),
                expected_active_generation_id=first.generation_id,
            )

        concurrent = await asyncio.gather(
            concurrent_publish("concurrent-a", "Annual concurrent A سياسة الإجازات"),
            concurrent_publish("concurrent-b", "Annual concurrent B سياسة الإجازات"),
            return_exceptions=True,
        )
        assert sum(not isinstance(value, Exception) for value in concurrent) == 1
        assert sum(isinstance(value, KnowledgePublicationConflict) for value in concurrent) == 1
        assert (
            bound_snapshot is not None
            and bound_snapshot.active_generation_id == first.generation_id
        )

        provider = PostgresLexicalKnowledgeRetrievalProvider(router, "customer-a")
        request = KnowledgeRetrievalRequest(
            namespace="hr",
            query="سياسة الإجازات",
            maximum_results=5,
            customer_environment_id="customer-a",
            enabled_modules=("hr_core", "leave"),
            permission_codes=("hr.knowledge.read",),
            roles=("employee",),
            authorized_legal_entity_ids=("entity-a",),
            purpose="employee_self_service",
            locale="ar-EG",
            effective_at=datetime.now(UTC),
        )
        matches = await provider.retrieve(request)
        assert matches and matches[0].content.startswith("Annual")
        assert matches[0].document_version == "12.34.567"
        assert await provider.retrieve(request.model_copy(update={"query": "Annual"}))
        assert (
            await provider.retrieve(request.model_copy(update={"enabled_modules": ("leave",)}))
            == ()
        )
        assert await provider.retrieve(request.model_copy(update={"permission_codes": ()})) == ()
        assert (
            await provider.retrieve(request.model_copy(update={"purpose": "manager_assistance"}))
            == ()
        )
        assert (
            await provider.retrieve(
                request.model_copy(update={"authorized_legal_entity_ids": ("entity-b",)})
            )
            == ()
        )
        assert await provider.retrieve(request.model_copy(update={"query": "notfoundtoken"})) == ()
        sql_input = request.model_copy(update={"query": "'); DROP TABLE chunks; --"})
        assert await provider.retrieve(sql_input) == ()

        current = await repository_a.get_active_snapshot(first.scope)
        assert current is not None
        reader_pool = router.pool("customer-a", KnowledgeDatabaseAccess.READER)
        async with reader_pool.connection() as connection, connection.transaction():
            await connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            await connection.execute(
                "SELECT set_config('erp_ai.customer_environment_id', %s, true)",
                ("customer-a",),
            )
            before = await (
                await connection.execute(
                    """SELECT generation_id FROM erp_ai_knowledge.active_generations
                    WHERE customer_environment_id=%s AND namespace=%s""",
                    ("customer-a", "hr"),
                )
            ).fetchone()
            activated = await publisher_a.publish(
                context(operation="snapshot-activation"),
                (
                    bundle(
                        content="Snapshot activation policy سياسة الإجازات",
                        version="12.34.567",
                        legal_entities=("entity-a",),
                    ),
                ),
                expected_active_generation_id=current.active_generation_id,
            )
            after = await (
                await connection.execute(
                    """SELECT generation_id FROM erp_ai_knowledge.active_generations
                    WHERE customer_environment_id=%s AND namespace=%s""",
                    ("customer-a", "hr"),
                )
            ).fetchone()
            assert before == after == (current.active_generation_id,)
        assert (await repository_a.get_active_snapshot(first.scope)).active_generation_id == (
            activated.generation_id
        )

        repository_b = PostgresKnowledgeIndexRepository(router, "customer-b")
        second_customer = await KnowledgeIndexPublisher(repository_b).publish(
            context(operation="customer-b-op", customer="customer-b"),
            (prepared,),
            expected_active_generation_id=None,
        )
        assert second_customer.scope.customer_environment_id == "customer-b"
        with pytest.raises(KnowledgeDatabaseIdentityError):
            await PostgresLexicalKnowledgeRetrievalProvider(router, "customer-b").retrieve(request)

        pool = router.pool("customer-a", KnowledgeDatabaseAccess.READER)
        async with pool.connection() as connection:
            async with connection.transaction():
                assert (
                    await (
                        await connection.execute(
                            "SELECT count(*) FROM erp_ai_knowledge.database_identity"
                        )
                    ).fetchone()
                )[0] == 0
            async with connection.transaction():
                await connection.execute(
                    "SELECT set_config('erp_ai.customer_environment_id', %s, true)",
                    ("wrong",),
                )
                assert (
                    await (
                        await connection.execute(
                            "SELECT count(*) FROM erp_ai_knowledge.database_identity"
                        )
                    ).fetchone()
                )[0] == 0
            async with connection.transaction():
                await connection.execute(
                    "SELECT set_config('erp_ai.customer_environment_id', %s, true)",
                    ("customer-a",),
                )
                assert (
                    await (
                        await connection.execute(
                            "SELECT count(*) FROM erp_ai_knowledge.database_identity"
                        )
                    ).fetchone()
                )[0] == 1
                privileges = await (
                    await connection.execute(
                        """SELECT has_table_privilege(current_user,
                        'erp_ai_knowledge.chunks','INSERT'),
                        current_setting('row_security'),
                        (SELECT rolsuper FROM pg_roles WHERE rolname=current_user),
                        (SELECT rolbypassrls FROM pg_roles WHERE rolname=current_user),
                        pg_has_role(current_user,
                            (SELECT relowner FROM pg_class
                             WHERE oid='erp_ai_knowledge.chunks'::regclass), 'MEMBER')"""
                    )
                ).fetchone()
                assert privileges == (False, "on", False, False, False)
            async with connection.transaction():
                assert (
                    await (
                        await connection.execute(
                            "SELECT current_setting('erp_ai.customer_environment_id', true)"
                        )
                    ).fetchone()
                )[0] == ""

        publisher_pool = router.pool("customer-a", KnowledgeDatabaseAccess.PUBLISHER)
        async with publisher_pool.connection() as connection, connection.transaction():
            privileges = await (
                await connection.execute(
                    """SELECT has_table_privilege(current_user,
                    'erp_ai_knowledge.documents','UPDATE'),
                    has_table_privilege(current_user,
                    'erp_ai_knowledge.publication_audit_outbox','SELECT')"""
                )
            ).fetchone()
            assert privileges == (False, False)
        admin = await psycopg.AsyncConnection.connect(_database_dsn("erp_ai_test_a"))
        try:
            outbox_count = await (
                await admin.execute(
                    "SELECT count(*) FROM erp_ai_knowledge.publication_audit_outbox"
                )
            ).fetchone()
            assert outbox_count[0] == 5
            runtime_roles = await (
                await admin.execute(
                    """SELECT rolname, rolsuper, rolbypassrls
                    FROM pg_roles WHERE rolname IN (%s,%s) ORDER BY rolname""",
                    (READER_ROLE, PUBLISHER_ROLE),
                )
            ).fetchall()
            assert runtime_roles == [
                (PUBLISHER_ROLE, False, False),
                (READER_ROLE, False, False),
            ]
        finally:
            await admin.close()

        active_before_restart = await repository_a.get_active_snapshot(first.scope)
        await router.close()
        await router.open()
        restarted = PostgresKnowledgeIndexRepository(router, "customer-a")
        assert await restarted.get_active_snapshot(first.scope) == active_before_restart
    finally:
        await router.close()


def test_postgres_migrations_rls_publication_retrieval_and_rollback() -> None:
    _run(_exercise_storage())


def test_migration_checksum_drift_and_identity_rebinding() -> None:
    async def scenario() -> None:
        await _recreate_databases()
        dsn = _database_dsn(CUSTOMERS[0][1])
        connection = await psycopg.AsyncConnection.connect(dsn)
        try:
            await run_migrations(connection)
            await provision_database_identity(connection, "customer-a")
            with pytest.raises(KnowledgeMigrationError, match="bound"):
                await provision_database_identity(connection, "customer-b")
            async with connection.transaction():
                await connection.execute(
                    """UPDATE erp_ai_knowledge.schema_migrations SET sha256=%s
                    WHERE migration_name=%s""",
                    ("0" * 64, MIGRATIONS[0]),
                )
            with pytest.raises(KnowledgeMigrationError, match="checksum"):
                await run_migrations(connection)
            digest = hashlib.sha256(_migration_bytes(MIGRATIONS[0])).hexdigest()
            async with connection.transaction():
                await connection.execute(
                    """UPDATE erp_ai_knowledge.schema_migrations SET sha256=%s
                    WHERE migration_name=%s""",
                    (digest, MIGRATIONS[0]),
                )
        finally:
            await connection.close()

    _run(scenario())
