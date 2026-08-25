import asyncio
import base64
import os
import selectors
from collections.abc import Coroutine
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.errors import DuplicateObject, InsufficientPrivilege
from pydantic import SecretStr

from erp_ai.infrastructure.postgres_erp import (
    ErpCursorKey,
    ErpCursorKeyring,
    ErpDatabaseRouteConfig,
    PostgresHrCoreReadProvider,
    PostgresLeaveReadProvider,
    SignedLeaveRequestCursor,
    StaticErpDatabaseConfig,
    StaticErpDatabaseRouter,
)
from erp_ai.infrastructure.postgres_erp.contract import verify_reader_contract
from erp_ai.infrastructure.postgres_erp.errors import ErpReadContractError

ADMIN_DSN = os.environ.get("ERP_AI_TEST_ADMIN_DSN")
REQUIRE_POSTGRES = os.environ.get("ERP_AI_REQUIRE_POSTGRES_TESTS") == "1"
if REQUIRE_POSTGRES and not ADMIN_DSN:
    raise pytest.UsageError("ERP_AI_TEST_ADMIN_DSN is required in required PostgreSQL mode")
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not ADMIN_DSN and not REQUIRE_POSTGRES,
        reason="ERP_AI_TEST_ADMIN_DSN is not configured",
    ),
]

DATABASES = (
    ("customer-a", "erp_ai_hr_a", "erp_ai_hr_reader_a"),
    ("customer-b", "erp_ai_hr_b", "erp_ai_hr_reader_b"),
)
VIEW_OWNER = "erp_ai_test_view_owner"
PASSWORD = "synthetic_hr_reader_password"
EMPLOYEE_ID = UUID("10000000-0000-4000-8000-000000000001")
ENTITY_ID = UUID("20000000-0000-4000-8000-000000000001")
OTHER_ENTITY_ID = UUID("20000000-0000-4000-8000-000000000002")
LEAVE_TYPE_ID = UUID("30000000-0000-4000-8000-000000000001")
REQUEST_IDS = tuple(UUID(f"40000000-0000-4000-8000-{value:012d}") for value in range(1, 5))


def _run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    if os.name == "nt":

        def selector_loop() -> asyncio.SelectorEventLoop:
            return asyncio.SelectorEventLoop(selectors.SelectSelector())

        with asyncio.Runner(loop_factory=selector_loop) as runner:
            return runner.run(coroutine)
    return asyncio.run(coroutine)


def _dsn(database: str, *, user: str = "postgres", password: str | None = None) -> str:
    assert ADMIN_DSN is not None
    values = {"dbname": database, "user": user}
    if password is not None:
        values["password"] = password
    return make_conninfo(ADMIN_DSN, **values)


async def _prepare() -> StaticErpDatabaseRouter:
    assert ADMIN_DSN is not None
    admin = await psycopg.AsyncConnection.connect(ADMIN_DSN, autocommit=True)
    try:
        for role, login in ((VIEW_OWNER, False), *((item[2], True) for item in DATABASES)):
            statement = sql.SQL("CREATE ROLE {} {} NOSUPERUSER NOBYPASSRLS").format(
                sql.Identifier(role),
                sql.SQL("LOGIN PASSWORD {}" if login else "NOLOGIN").format(sql.Literal(PASSWORD))
                if login
                else sql.SQL("NOLOGIN"),
            )
            try:
                await admin.execute(statement)
            except DuplicateObject:
                await admin.execute(
                    sql.SQL("ALTER ROLE {} WITH {} NOSUPERUSER NOBYPASSRLS").format(
                        sql.Identifier(role),
                        sql.SQL("LOGIN PASSWORD {}").format(sql.Literal(PASSWORD))
                        if login
                        else sql.SQL("NOLOGIN"),
                    )
                )
        for _, database, reader in DATABASES:
            await admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s",
                (database,),
            )
            await admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database))
            )
            await admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
            await admin.execute(
                sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database))
            )
            await admin.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(database), sql.Identifier(reader)
                )
            )
    finally:
        await admin.close()

    ddl = Path("tests/fixtures/postgres_erp/schema.sql").read_text(encoding="utf-8")
    routes = []
    for customer, database, reader in DATABASES:
        connection = await psycopg.AsyncConnection.connect(_dsn(database))
        try:
            await connection.execute(ddl.replace("__READER_ROLE__", reader))
            await _insert_customer_rows(connection, customer)
            await connection.commit()
        finally:
            await connection.close()
        routes.append(
            ErpDatabaseRouteConfig(
                customer_environment_id=customer,
                reader_dsn=SecretStr(_dsn(database, user=reader, password=PASSWORD)),
                expected_database_name=database,
            )
        )
    cursor_key = ErpCursorKey(
        key_id="integration", key_base64=SecretStr(base64.b64encode(b"k" * 32).decode())
    )
    router = StaticErpDatabaseRouter(
        StaticErpDatabaseConfig(
            routes=tuple(routes),
            cursor_keyring=ErpCursorKeyring(active=cursor_key),
            minimum_pool_size=0,
        )
    )
    await router.open()
    return router


async def _insert_customer_rows(connection: Any, customer: str) -> None:
    suffix = "Alpha" if customer == "customer-a" else "Beta"
    await connection.execute(
        "INSERT INTO erp.legal_entities VALUES (%s,%s),(%s,%s)",
        (ENTITY_ID, f"{suffix} Entity", OTHER_ENTITY_ID, f"{suffix} Other"),
    )
    await connection.execute(
        "INSERT INTO erp.organization_branches VALUES (%s,%s,%s)",
        (UUID("50000000-0000-4000-8000-000000000001"), ENTITY_ID, f"{suffix} Branch"),
    )
    await connection.execute(
        "INSERT INTO erp.branch_departments VALUES (%s,%s,%s,%s)",
        (
            UUID("60000000-0000-4000-8000-000000000001"),
            UUID("50000000-0000-4000-8000-000000000001"),
            ENTITY_ID,
            f"{suffix} HR",
        ),
    )
    await connection.execute(
        "INSERT INTO erp.positions VALUES (%s,%s,%s)",
        (UUID("70000000-0000-4000-8000-000000000001"), ENTITY_ID, f"{suffix} Manager"),
    )
    await connection.execute(
        """INSERT INTO erp.employees(employee_id,legal_entity_id,employee_number,display_name,
        email_work,position_id,dept_id,branch_id,employment_status,hire_date,
        profile_freshness_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'active',%s,%s,NULL)""",
        (
            EMPLOYEE_ID,
            ENTITY_ID,
            "EMP-1",
            f"{suffix} Employee",
            f"employee@{suffix.lower()}.invalid",
            UUID("70000000-0000-4000-8000-000000000001"),
            UUID("60000000-0000-4000-8000-000000000001"),
            UUID("50000000-0000-4000-8000-000000000001"),
            date(2020, 1, 1),
            "2026-08-01T00:00:00Z",
        ),
    )
    await connection.execute(
        "INSERT INTO erp.leave_types VALUES (%s,%s,'annual','Annual','سنوية')",
        (LEAVE_TYPE_ID, ENTITY_ID),
    )
    await connection.execute(
        """INSERT INTO erp.leave_balances VALUES
        (%s,%s,%s,%s,2026,10.00,5.00,12.00,4.00,-1.00,%s,'ledger:42','1.2.3')""",
        (
            UUID("80000000-0000-4000-8000-000000000001"),
            EMPLOYEE_ID,
            ENTITY_ID,
            LEAVE_TYPE_ID,
            "2026-08-01T00:00:00Z",
        ),
    )
    for index, request_id in enumerate(REQUEST_IDS):
        await connection.execute(
            """INSERT INTO erp.leave_requests VALUES
            (%s,%s,%s,%s,%s,%s,1.00,false,NULL,%s,%s,NULL,'1.0.0')""",
            (
                request_id,
                EMPLOYEE_ID,
                ENTITY_ID,
                LEAVE_TYPE_ID,
                date(2026, 8, index + 1),
                date(2026, 8, index + 1),
                "approved" if index == 0 else "pending",
                f"2026-08-0{index + 1}T10:00:00Z",
            ),
        )
    await connection.execute(
        """INSERT INTO erp.workflow_status_history VALUES
        (%s,'leave_request',%s,NULL,'pending',%s,NULL),
        (%s,'leave_request',%s,'pending','approved',%s,'approved')""",
        (
            UUID("90000000-0000-4000-8000-000000000001"),
            REQUEST_IDS[0],
            "2026-08-01T10:00:00Z",
            UUID("90000000-0000-4000-8000-000000000002"),
            REQUEST_IDS[0],
            "2026-08-01T11:00:00Z",
        ),
    )


async def _exercise() -> None:
    router = await _prepare()
    try:
        profiles = PostgresHrCoreReadProvider(router)
        alpha = await profiles.get_my_employee_profile(
            customer_environment_id="customer-a",
            employee_id=str(EMPLOYEE_ID),
            authorized_legal_entity_ids=(str(ENTITY_ID),),
        )
        beta = await profiles.get_my_employee_profile(
            customer_environment_id="customer-b",
            employee_id=str(EMPLOYEE_ID),
            authorized_legal_entity_ids=(str(ENTITY_ID),),
        )
        assert alpha is not None and beta is not None
        assert alpha.display_name == "Alpha Employee" and beta.display_name == "Beta Employee"
        assert alpha.job_title == "Alpha Manager" and alpha.freshness_at.isoformat().startswith(
            "2026-08-01"
        )
        assert (
            await profiles.get_my_employee_profile(
                customer_environment_id="customer-a",
                employee_id=str(EMPLOYEE_ID),
                authorized_legal_entity_ids=(str(OTHER_ENTITY_ID),),
            )
            is None
        )

        cursor = SignedLeaveRequestCursor(router.config.cursor_keyring)
        leave = PostgresLeaveReadProvider(router, cursor)
        balances = await leave.get_my_leave_balances(
            customer_environment_id="customer-a",
            employee_id=str(EMPLOYEE_ID),
            authorized_legal_entity_ids=(str(ENTITY_ID),),
        )
        assert balances[0].available_days == Decimal("-1.00")
        first = await leave.list_my_leave_requests(
            customer_environment_id="customer-a",
            employee_id=str(EMPLOYEE_ID),
            authorized_legal_entity_ids=(str(ENTITY_ID),),
            statuses=(),
            start_from=None,
            start_to=None,
            limit=2,
            cursor=None,
            authorization_snapshot_id="snapshot-a",
        )
        assert [item.request_id for item in first.items] == [REQUEST_IDS[3], REQUEST_IDS[2]]
        assert first.next_cursor is not None
        second = await leave.list_my_leave_requests(
            customer_environment_id="customer-a",
            employee_id=str(EMPLOYEE_ID),
            authorized_legal_entity_ids=(str(ENTITY_ID),),
            statuses=(),
            start_from=None,
            start_to=None,
            limit=2,
            cursor=first.next_cursor,
            authorization_snapshot_id="snapshot-a",
        )
        assert [item.request_id for item in second.items] == [REQUEST_IDS[1], REQUEST_IDS[0]]
        detail = await leave.get_my_leave_request(
            customer_environment_id="customer-a",
            employee_id=str(EMPLOYEE_ID),
            authorized_legal_entity_ids=(str(ENTITY_ID),),
            request_id=REQUEST_IDS[0],
        )
        assert detail is not None and [item.to_status.value for item in detail.status_history] == [
            "pending",
            "approved",
        ]
        reader_dsn = _dsn("erp_ai_hr_a", user="erp_ai_hr_reader_a", password=PASSWORD)
        reader = await psycopg.AsyncConnection.connect(reader_dsn)
        try:
            with pytest.raises(ErpReadContractError, match="identity mismatch"):
                await verify_reader_contract(reader, "wrong_database")
            with pytest.raises(InsufficientPrivilege):
                await reader.execute("SELECT employee_id FROM erp.employees")
        finally:
            await reader.close()

        admin = await psycopg.AsyncConnection.connect(_dsn("erp_ai_hr_a"))
        try:
            await admin.execute(
                """CREATE OR REPLACE VIEW ai_read.contract_metadata_v1
                WITH (security_barrier=true) AS SELECT '1.0.0'::varchar(64) contract_version,
                repeat('0',64)::char(64) contract_sha256"""
            )
            await admin.commit()
        finally:
            await admin.close()
        drift_reader = await psycopg.AsyncConnection.connect(reader_dsn)
        try:
            with pytest.raises(ErpReadContractError, match="metadata mismatch"):
                await verify_reader_contract(drift_reader, "erp_ai_hr_a")
        finally:
            await drift_reader.close()
    finally:
        await router.close()


def test_live_two_customer_structured_erp_reads() -> None:
    _run(_exercise())
