"""Deterministic reader-visible structured ERP view contract."""

import asyncio
import hashlib
import json
from typing import Any

from psycopg import AsyncConnection

from erp_ai.infrastructure.postgres_erp.errors import ErpReadContractError

CONTRACT_VERSION = "1.0.0"
type ColumnSignature = tuple[str, str]
type ViewSignature = tuple[str, tuple[ColumnSignature, ...]]
type ContractDescriptor = tuple[str, tuple[ViewSignature, ...], ViewSignature]

BUSINESS_VIEW_SIGNATURES: tuple[ViewSignature, ...] = (
    (
        "ai_read.hr_employee_profile_v1",
        (
            ("employee_id", "uuid"),
            ("legal_entity_id", "uuid"),
            ("employee_number", "character varying"),
            ("display_name", "character varying"),
            ("work_email", "character varying"),
            ("job_title", "character varying"),
            ("department_name", "character varying"),
            ("branch_name", "character varying"),
            ("legal_entity_name", "character varying"),
            ("employment_status", "character varying"),
            ("hire_date", "date"),
            ("manager_display_name", "character varying"),
            ("freshness_at", "timestamp with time zone"),
        ),
    ),
    (
        "ai_read.leave_balances_v1",
        (
            ("employee_id", "uuid"),
            ("legal_entity_id", "uuid"),
            ("leave_type_id", "uuid"),
            ("leave_type_code", "character varying"),
            ("leave_type_name", "character varying"),
            ("leave_type_name_local", "character varying"),
            ("fiscal_year", "smallint"),
            ("opening_days", "numeric"),
            ("accrued_days", "numeric"),
            ("used_days", "numeric"),
            ("pending_days", "numeric"),
            ("available_days", "numeric"),
            ("calculated_at", "timestamp with time zone"),
            ("source_watermark", "character varying"),
            ("calculation_version", "character varying"),
        ),
    ),
    (
        "ai_read.leave_requests_v1",
        (
            ("request_id", "uuid"),
            ("employee_id", "uuid"),
            ("legal_entity_id", "uuid"),
            ("leave_type_id", "uuid"),
            ("leave_type_code", "character varying"),
            ("leave_type_name", "character varying"),
            ("leave_type_name_local", "character varying"),
            ("start_date", "date"),
            ("end_date", "date"),
            ("working_days", "numeric"),
            ("is_half_day", "boolean"),
            ("half_day_period", "character varying"),
            ("status", "character varying"),
            ("submitted_at", "timestamp with time zone"),
            ("updated_at", "timestamp with time zone"),
            ("working_days_calculation_version", "character varying"),
        ),
    ),
    (
        "ai_read.leave_request_history_v1",
        (
            ("history_id", "uuid"),
            ("request_id", "uuid"),
            ("employee_id", "uuid"),
            ("legal_entity_id", "uuid"),
            ("entity_type", "character varying"),
            ("from_status", "character varying"),
            ("to_status", "character varying"),
            ("changed_at", "timestamp with time zone"),
            ("reason_code", "character varying"),
        ),
    ),
)
METADATA_VIEW_SIGNATURE: ViewSignature = (
    "ai_read.contract_metadata_v1",
    (("contract_version", "character varying"), ("contract_sha256", "character")),
)
CONTRACT_DESCRIPTOR: ContractDescriptor = (
    CONTRACT_VERSION,
    BUSINESS_VIEW_SIGNATURES,
    METADATA_VIEW_SIGNATURE,
)
VIEW_SIGNATURES = dict(BUSINESS_VIEW_SIGNATURES)


def canonical_contract_bytes(descriptor: ContractDescriptor = CONTRACT_DESCRIPTOR) -> bytes:
    """Serialize the frozen descriptor without key sorting or a trailing newline."""
    version, views, metadata_view = descriptor
    payload = {
        "contract_version": version,
        "views": [[name, [list(column) for column in columns]] for name, columns in views],
        "metadata_view": [
            metadata_view[0],
            [list(column) for column in metadata_view[1]],
        ],
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False,
    ).encode("utf-8")


def contract_digest(descriptor: ContractDescriptor = CONTRACT_DESCRIPTOR) -> str:
    return hashlib.sha256(canonical_contract_bytes(descriptor)).hexdigest()


def validate_contract_snapshot(
    *,
    reported_version: object,
    reported_digest: object,
    actual_views: tuple[ViewSignature, ...],
    actual_metadata_view: ViewSignature,
) -> None:
    if (reported_version, reported_digest) != (CONTRACT_VERSION, contract_digest()):
        raise ErpReadContractError("ERP read contract metadata mismatch")
    if actual_metadata_view != METADATA_VIEW_SIGNATURE:
        raise ErpReadContractError("ERP metadata view signature mismatch")
    if actual_views != BUSINESS_VIEW_SIGNATURES:
        raise ErpReadContractError("ERP read view signature mismatch")


def validate_postgres_version(server_version: int) -> None:
    if not 15 <= server_version // 10_000 <= 18:
        raise ErpReadContractError("unsupported ERP PostgreSQL version")


async def verify_reader_contract(  # pragma: no cover - exercised by opt-in PostgreSQL tests
    connection: AsyncConnection[tuple[Any, ...]], expected_database_name: str
) -> None:
    """Verify only reader-visible identity, views, ownership, and grants."""
    try:
        validate_postgres_version(connection.info.server_version)
        identity = await (await connection.execute("SELECT current_database()")).fetchone()
        if identity is None or identity[0] != expected_database_name:
            raise ErpReadContractError("ERP database identity mismatch")
        metadata = await (
            await connection.execute(
                "SELECT contract_version, contract_sha256 FROM ai_read.contract_metadata_v1"
            )
        ).fetchone()
        metadata_columns = await (
            await connection.execute(
                """SELECT column_name,data_type FROM information_schema.columns
                WHERE table_schema='ai_read' AND table_name='contract_metadata_v1'
                ORDER BY ordinal_position"""
            )
        ).fetchall()
        columns = await (
            await connection.execute(
                """SELECT table_name,column_name,data_type FROM information_schema.columns
            WHERE table_schema='ai_read' AND table_name <> 'contract_metadata_v1'
            ORDER BY table_name,ordinal_position"""
            )
        ).fetchall()
        actual: dict[str, list[tuple[str, str]]] = {}
        for view, column, data_type in columns:
            actual.setdefault(f"ai_read.{view}", []).append((str(column), str(data_type)))
        ordered_actual = tuple(
            (name, tuple(actual.pop(name, ()))) for name, _ in BUSINESS_VIEW_SIGNATURES
        ) + tuple((name, tuple(signature)) for name, signature in sorted(actual.items()))
        validate_contract_snapshot(
            reported_version=None if metadata is None else metadata[0],
            reported_digest=None if metadata is None else metadata[1],
            actual_views=ordered_actual,
            actual_metadata_view=(
                "ai_read.contract_metadata_v1",
                tuple((str(name), str(data_type)) for name, data_type in metadata_columns),
            ),
        )
        role = await (
            await connection.execute(
                "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
            )
        ).fetchone()
        if role is None or bool(role[0]) or bool(role[1]):
            raise ErpReadContractError("ERP reader role is unsafe")
        owners = await (
            await connection.execute(
                """SELECT DISTINCT owner.rolname,owner.rolsuper,owner.rolbypassrls,owner.rolcanlogin
                FROM pg_class view_object JOIN pg_namespace namespace
                ON namespace.oid=view_object.relnamespace
                JOIN pg_roles owner ON owner.oid=view_object.relowner
                WHERE namespace.nspname='ai_read' AND view_object.relkind='v'"""
            )
        ).fetchall()
        if len(owners) != 1 or bool(owners[0][1]) or bool(owners[0][2]) or bool(owners[0][3]):
            raise ErpReadContractError("ERP read view ownership is unsafe")
        base_owned = await (
            await connection.execute(
                """SELECT 1 FROM pg_class base_object JOIN pg_namespace namespace
                ON namespace.oid=base_object.relnamespace
                WHERE base_object.relkind IN ('r','p') AND base_object.relowner=(
                    SELECT DISTINCT view_object.relowner FROM pg_class view_object
                    JOIN pg_namespace view_namespace ON view_namespace.oid=view_object.relnamespace
                    WHERE view_namespace.nspname='ai_read' AND view_object.relkind='v')
                AND namespace.nspname NOT IN ('pg_catalog','information_schema','ai_read')
                LIMIT 1"""
            )
        ).fetchone()
        if base_owned is not None:
            raise ErpReadContractError("ERP read view owner owns base tables")
        grants = await (
            await connection.execute(
                """SELECT table_name,privilege_type FROM information_schema.role_table_grants
                WHERE grantee=current_user AND table_schema='ai_read'
                ORDER BY table_name,privilege_type"""
            )
        ).fetchall()
        expected_grants = tuple(
            (name.removeprefix("ai_read."), "SELECT")
            for name in sorted((*VIEW_SIGNATURES, "ai_read.contract_metadata_v1"))
        )
        if tuple(grants) != expected_grants:
            raise ErpReadContractError("ERP reader view privileges mismatch")
        creation = await (
            await connection.execute(
                """SELECT has_database_privilege(current_user,current_database(),'CREATE'),
                has_database_privilege(current_user,current_database(),'TEMP'),
                has_schema_privilege(current_user,'ai_read','CREATE')"""
            )
        ).fetchone()
        if creation is None or any(bool(value) for value in creation):
            raise ErpReadContractError("ERP reader has object-creation privileges")
        forbidden = await (
            await connection.execute(
                """SELECT 1 FROM information_schema.role_table_grants
            WHERE grantee=current_user AND table_schema <> 'ai_read' LIMIT 1"""
            )
        ).fetchone()
        if forbidden is not None:
            raise ErpReadContractError("ERP reader has direct table privileges")
    except asyncio.CancelledError:
        raise
    except ErpReadContractError:
        raise
    except Exception:
        raise ErpReadContractError("ERP read contract verification failed") from None
