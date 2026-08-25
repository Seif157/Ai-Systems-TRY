"""Production read-only providers querying only approved structured ERP views."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from typing import Any, cast
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from pydantic import ValidationError

from erp_ai.capabilities.hr_core.models import EmployeeProfileRecord
from erp_ai.capabilities.leave.models import (
    LeaveBalanceRecord,
    LeaveRequestDetailRecord,
    LeaveRequestHistoryRecord,
    LeaveRequestPageRecord,
    LeaveRequestStatus,
    LeaveRequestSummaryRecord,
)
from erp_ai.infrastructure.postgres_erp.cursor import (
    CursorPosition,
    SignedLeaveRequestCursor,
    filter_digest,
)
from erp_ai.infrastructure.postgres_erp.errors import ErpReadError, ErpReadUnavailable
from erp_ai.infrastructure.postgres_erp.routing import ErpDatabaseRouter

_PROFILE_SQL = """SELECT employee_id,legal_entity_id,employee_number,display_name,work_email,
job_title,department_name,branch_name,legal_entity_name,employment_status,hire_date,
manager_display_name,freshness_at FROM ai_read.hr_employee_profile_v1
WHERE employee_id=%s::uuid AND legal_entity_id=ANY(%s::uuid[])"""

_BALANCES_SQL = """SELECT employee_id,legal_entity_id,leave_type_id,leave_type_code,
leave_type_name,leave_type_name_local,fiscal_year,opening_days,accrued_days,used_days,pending_days,
available_days,calculated_at,source_watermark,calculation_version
FROM ai_read.leave_balances_v1 WHERE employee_id=%s::uuid
AND legal_entity_id=ANY(%s::uuid[])
ORDER BY fiscal_year,leave_type_code,legal_entity_id,leave_type_id"""

_LIST_SQL = """WITH page_clock AS (
SELECT COALESCE(%s::timestamptz,clock_timestamp()) AS ceiling)
SELECT request_id,employee_id,legal_entity_id,leave_type_id,leave_type_code,leave_type_name,
leave_type_name_local,start_date,end_date,working_days,is_half_day,half_day_period,status,
submitted_at,updated_at,working_days_calculation_version,page_clock.ceiling AS snapshot_ceiling
FROM ai_read.leave_requests_v1 CROSS JOIN page_clock
WHERE employee_id=%s::uuid AND legal_entity_id=ANY(%s::uuid[])
AND submitted_at<=page_clock.ceiling
AND (cardinality(%s::text[])=0 OR status=ANY(%s::text[]))
AND (%s::date IS NULL OR start_date>=%s::date)
AND (%s::date IS NULL OR start_date<=%s::date)
AND (%s::timestamptz IS NULL OR submitted_at<%s::timestamptz
    OR (submitted_at=%s::timestamptz AND request_id>%s::uuid))
ORDER BY submitted_at DESC,request_id ASC LIMIT %s"""

_DETAIL_SQL = """SELECT request_id,employee_id,legal_entity_id,leave_type_id,leave_type_code,
leave_type_name,leave_type_name_local,start_date,end_date,working_days,is_half_day,half_day_period,
status,submitted_at,updated_at,working_days_calculation_version
FROM ai_read.leave_requests_v1 WHERE request_id=%s::uuid AND employee_id=%s::uuid
AND legal_entity_id=ANY(%s::uuid[])"""

_HISTORY_SQL = """SELECT history_id,entity_type,request_id AS entity_id,from_status,to_status,
changed_at,reason_code FROM ai_read.leave_request_history_v1 WHERE request_id=%s::uuid
AND employee_id=%s::uuid AND legal_entity_id=ANY(%s::uuid[])
ORDER BY changed_at ASC,history_id ASC"""


class _ReadTransaction:
    __slots__ = ("idle_timeout_ms", "lock_timeout_ms", "statement_timeout_ms")

    def __init__(
        self, statement_timeout_ms: int, lock_timeout_ms: int, idle_timeout_ms: int
    ) -> None:
        self.statement_timeout_ms = statement_timeout_ms
        self.lock_timeout_ms = lock_timeout_ms
        self.idle_timeout_ms = idle_timeout_ms

    @asynccontextmanager
    async def connection(  # pragma: no cover - opt-in PostgreSQL boundary
        self, pool: AsyncConnectionPool
    ) -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
        async with pool.connection() as raw:
            raw.row_factory = cast(Any, dict_row)
            async with raw.transaction():
                await raw.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                await raw.execute(
                    "SELECT set_config('statement_timeout',%s,true)",
                    (f"{self.statement_timeout_ms}ms",),
                )
                await raw.execute(
                    "SELECT set_config('lock_timeout',%s,true)", (f"{self.lock_timeout_ms}ms",)
                )
                await raw.execute(
                    "SELECT set_config('idle_in_transaction_session_timeout',%s,true)",
                    (f"{self.idle_timeout_ms}ms",),
                )
                yield cast(Any, raw)


class PostgresHrCoreReadProvider:
    """Customer-routed safe employee profile projection."""

    __slots__ = ("_router", "_transaction")

    def __init__(
        self,
        router: ErpDatabaseRouter,
        *,
        statement_timeout_ms: int = 5_000,
        lock_timeout_ms: int = 2_000,
        idle_transaction_timeout_ms: int = 10_000,
    ) -> None:
        self._router = router
        self._transaction = _ReadTransaction(
            statement_timeout_ms, lock_timeout_ms, idle_transaction_timeout_ms
        )

    async def get_my_employee_profile(  # pragma: no cover - opt-in PostgreSQL boundary
        self,
        *,
        customer_environment_id: str,
        employee_id: str,
        authorized_legal_entity_ids: tuple[str, ...],
    ) -> EmployeeProfileRecord | None:
        if not authorized_legal_entity_ids:
            return None
        try:
            pool = self._router.pool(customer_environment_id)
            async with self._transaction.connection(pool) as connection:
                row = await (
                    await connection.execute(
                        _PROFILE_SQL, (employee_id, list(authorized_legal_entity_ids))
                    )
                ).fetchone()
            if row is None:
                return None
            values = dict(row)
            values["employee_id"] = str(values["employee_id"])
            values["legal_entity_id"] = str(values["legal_entity_id"])
            return EmployeeProfileRecord.model_validate(values)
        except asyncio.CancelledError:
            raise
        except (ErpReadError, ValidationError):
            raise ErpReadUnavailable("ERP profile is unavailable") from None
        except Exception:
            raise ErpReadUnavailable("ERP profile is unavailable") from None


class PostgresLeaveReadProvider:
    """Customer-routed balances, keyset listing, and request detail provider."""

    __slots__ = ("_cursor", "_router", "_transaction")

    def __init__(
        self,
        router: ErpDatabaseRouter,
        cursor: SignedLeaveRequestCursor,
        *,
        statement_timeout_ms: int = 5_000,
        lock_timeout_ms: int = 2_000,
        idle_transaction_timeout_ms: int = 10_000,
    ) -> None:
        self._router = router
        self._cursor = cursor
        self._transaction = _ReadTransaction(
            statement_timeout_ms, lock_timeout_ms, idle_transaction_timeout_ms
        )

    async def get_my_leave_balances(  # pragma: no cover - opt-in PostgreSQL boundary
        self,
        *,
        customer_environment_id: str,
        employee_id: str,
        authorized_legal_entity_ids: tuple[str, ...],
    ) -> tuple[LeaveBalanceRecord, ...]:
        if not authorized_legal_entity_ids:
            return ()
        try:
            pool = self._router.pool(customer_environment_id)
            async with self._transaction.connection(pool) as connection:
                rows = await (
                    await connection.execute(
                        _BALANCES_SQL, (employee_id, list(authorized_legal_entity_ids))
                    )
                ).fetchall()
            records = []
            for row in rows:
                values = dict(row)
                for field in ("employee_id", "legal_entity_id", "leave_type_id"):
                    values[field] = str(values[field])
                records.append(LeaveBalanceRecord.model_validate(values))
            return tuple(records)
        except asyncio.CancelledError:
            raise
        except Exception:
            raise ErpReadUnavailable("ERP leave balances are unavailable") from None

    async def list_my_leave_requests(  # pragma: no cover - opt-in PostgreSQL boundary
        self,
        *,
        customer_environment_id: str,
        employee_id: str,
        authorized_legal_entity_ids: tuple[str, ...],
        statuses: tuple[LeaveRequestStatus, ...],
        start_from: date | None,
        start_to: date | None,
        limit: int,
        cursor: str | None,
        authorization_snapshot_id: str,
    ) -> LeaveRequestPageRecord:
        if not authorized_legal_entity_ids:
            return LeaveRequestPageRecord(items=())
        digest = filter_digest(statuses, start_from, start_to)
        position = (
            None
            if cursor is None
            else self._cursor.decode(
                cursor,
                customer_environment_id=customer_environment_id,
                employee_id=employee_id,
                legal_entity_ids=authorized_legal_entity_ids,
                authorization_snapshot_id=authorization_snapshot_id,
                filters_digest=digest,
                limit=limit,
            )
        )
        status_values = [status.value for status in statuses]
        try:
            pool = self._router.pool(customer_environment_id)
            async with self._transaction.connection(pool) as connection:
                result = await connection.execute(
                    _LIST_SQL,
                    (
                        None if position is None else position.snapshot_ceiling,
                        employee_id,
                        list(authorized_legal_entity_ids),
                        status_values,
                        status_values,
                        start_from,
                        start_from,
                        start_to,
                        start_to,
                        None if position is None else position.submitted_at,
                        None if position is None else position.submitted_at,
                        None if position is None else position.submitted_at,
                        None if position is None else position.request_id,
                        limit + 1,
                    ),
                )
                rows = list(await result.fetchall())
            has_more = len(rows) > limit
            page_rows = rows[:limit]
            snapshot = (
                position.snapshot_ceiling
                if position is not None
                else (page_rows[0]["snapshot_ceiling"] if page_rows else datetime.now(UTC))
            )
            records = []
            for row in page_rows:
                values = dict(row)
                values.pop("snapshot_ceiling")
                records.append(LeaveRequestSummaryRecord.model_validate(values))
            next_cursor = None
            if has_more and records:
                last = records[-1]
                next_cursor = self._cursor.encode(
                    customer_environment_id=customer_environment_id,
                    employee_id=employee_id,
                    legal_entity_ids=authorized_legal_entity_ids,
                    authorization_snapshot_id=authorization_snapshot_id,
                    filters_digest=digest,
                    limit=limit,
                    position=CursorPosition(snapshot, last.submitted_at, last.request_id),
                )
            return LeaveRequestPageRecord(items=tuple(records), next_cursor=next_cursor)
        except asyncio.CancelledError:
            raise
        except Exception:
            raise ErpReadUnavailable("ERP leave requests are unavailable") from None

    async def get_my_leave_request(  # pragma: no cover - opt-in PostgreSQL boundary
        self,
        *,
        customer_environment_id: str,
        employee_id: str,
        authorized_legal_entity_ids: tuple[str, ...],
        request_id: UUID,
    ) -> LeaveRequestDetailRecord | None:
        if not authorized_legal_entity_ids:
            return None
        try:
            pool = self._router.pool(customer_environment_id)
            async with self._transaction.connection(pool) as connection:
                request = await (
                    await connection.execute(
                        _DETAIL_SQL, (request_id, employee_id, list(authorized_legal_entity_ids))
                    )
                ).fetchone()
                if request is None:
                    return None
                history_rows = await (
                    await connection.execute(
                        _HISTORY_SQL, (request_id, employee_id, list(authorized_legal_entity_ids))
                    )
                ).fetchall()
            history = tuple(LeaveRequestHistoryRecord.model_validate(row) for row in history_rows)
            return LeaveRequestDetailRecord.model_validate(
                {
                    **request,
                    "customer_environment_id": customer_environment_id,
                    "status_history": history,
                }
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            raise ErpReadUnavailable("ERP leave request is unavailable") from None
