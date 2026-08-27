"""Frozen relational audit contracts and canonical event digests."""
# ruff: noqa: E501

import asyncio
import hashlib
import json
from enum import StrEnum
from typing import Any, Final

from psycopg import AsyncConnection
from pydantic import BaseModel

from erp_ai.application.audit import ApplicationAuditEvent
from erp_ai.orchestration.audit import AgentAuditEvent
from erp_ai.tools.audit import ToolAuditEvent

CONTRACT_VERSION = "1.0.0"
type ColumnSignature = tuple[str, str]
type TableSignature = tuple[str, tuple[ColumnSignature, ...]]


class AuditDatabaseKind(StrEnum):
    CONTROL = "control"
    CUSTOMER = "customer"


IDENTITY_SIGNATURE: TableSignature = (
    "erp_ai_audit.database_identity",
    (
        ("singleton", "boolean"),
        ("database_kind", "character varying(16)"),
        ("database_identity", "character varying(100)"),
        ("customer_environment_id", "character varying(100)"),
    ),
)
METADATA_SIGNATURE: TableSignature = (
    "erp_ai_audit.contract_metadata",
    (
        ("singleton", "boolean"),
        ("contract_version", "character varying(20)"),
        ("contract_sha256", "character(64)"),
    ),
)
APPLICATION_SIGNATURE: TableSignature = (
    "erp_ai_audit.application_events",
    (
        ("request_id", "character varying(100)"),
        ("stage", "character varying(32)"),
        ("outcome", "character varying(16)"),
        ("internal_reason", "character varying(200)"),
        ("event_digest", "character(64)"),
        ("recorded_at", "timestamp with time zone"),
    ),
)
AGENT_SIGNATURE: TableSignature = (
    "erp_ai_audit.agent_events",
    (
        ("request_id", "character varying(100)"),
        ("customer_environment_id", "character varying(100)"),
        ("user_id", "character varying(100)"),
        ("purpose", "character varying(100)"),
        ("action", "character varying(100)"),
        ("outcome", "character varying(16)"),
        ("internal_reason", "character varying(200)"),
        ("event_digest", "character(64)"),
        ("recorded_at", "timestamp with time zone"),
    ),
)
TOOL_SIGNATURE: TableSignature = (
    "erp_ai_audit.tool_events",
    (
        ("request_id", "character varying(100)"),
        ("customer_environment_id", "character varying(100)"),
        ("user_id", "character varying(100)"),
        ("tool_name", "character varying(100)"),
        ("tool_version", "character varying(32)"),
        ("audit_action", "character varying(100)"),
        ("data_classification", "character varying(32)"),
        ("outcome", "character varying(16)"),
        ("internal_reason", "character varying(200)"),
        ("purpose", "character varying(100)"),
        ("event_digest", "character(64)"),
        ("recorded_at", "timestamp with time zone"),
    ),
)
CONTROL_DESCRIPTOR = (
    CONTRACT_VERSION,
    (IDENTITY_SIGNATURE, METADATA_SIGNATURE, APPLICATION_SIGNATURE),
)
CUSTOMER_DESCRIPTOR = (
    CONTRACT_VERSION,
    (IDENTITY_SIGNATURE, METADATA_SIGNATURE, AGENT_SIGNATURE, TOOL_SIGNATURE),
)


def canonical_contract_bytes(descriptor: tuple[str, tuple[TableSignature, ...]]) -> bytes:
    version, tables = descriptor
    payload = {
        "contract_version": version,
        "tables": [[name, [list(c) for c in columns]] for name, columns in tables],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=False).encode()


def contract_digest(descriptor: tuple[str, tuple[TableSignature, ...]]) -> str:
    return hashlib.sha256(canonical_contract_bytes(descriptor)).hexdigest()


def validate_contract_snapshot(
    *,
    descriptor: tuple[str, tuple[TableSignature, ...]],
    reported_version: object,
    reported_digest: object,
    actual_tables: tuple[TableSignature, ...],
) -> None:
    from erp_ai.infrastructure.postgres_audit.errors import AuditStorageUnavailable

    if (reported_version, reported_digest) != (CONTRACT_VERSION, contract_digest(descriptor)):
        raise AuditStorageUnavailable("audit storage contract is unavailable")
    if actual_tables != descriptor[1]:
        raise AuditStorageUnavailable("audit storage signature is unavailable")


_EVENT_SPECS: Final = {
    ApplicationAuditEvent: (
        "erp-ai:application-audit:v1",
        ("request_id", "stage", "outcome", "internal_reason"),
    ),
    AgentAuditEvent: (
        "erp-ai:agent-audit:v1",
        (
            "request_id",
            "customer_environment_id",
            "user_id",
            "purpose",
            "action",
            "outcome",
            "internal_reason",
        ),
    ),
    ToolAuditEvent: (
        "erp-ai:tool-audit:v1",
        (
            "request_id",
            "customer_environment_id",
            "user_id",
            "tool_name",
            "tool_version",
            "audit_action",
            "data_classification",
            "outcome",
            "internal_reason",
            "purpose",
        ),
    ),
}


def validated_event_values(event: BaseModel) -> tuple[object, ...]:
    """Strictly revalidate and project an event in its frozen persisted order."""
    event_type = type(event)
    if event_type not in _EVENT_SPECS:
        raise TypeError("unsupported audit event")
    _, fields = _EVENT_SPECS[event_type]
    validated = event_type.model_validate(event.model_dump(mode="python"), strict=True)
    return tuple(validated.model_dump(mode="json")[field] for field in fields)


def event_digest(event: BaseModel) -> str:
    event_type = type(event)
    if event_type not in _EVENT_SPECS:
        raise TypeError("unsupported audit event")
    domain, fields = _EVENT_SPECS[event_type]
    values = validated_event_values(event)
    payload: dict[str, Any] = {
        "domain": domain,
        "event": {field: value for field, value in zip(fields, values, strict=True)},
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=False).encode()
    return hashlib.sha256(raw).hexdigest()


async def verify_database_contract(  # pragma: no cover - live PostgreSQL boundary
    connection: AsyncConnection[tuple[Any, ...]],
    *,
    expected_name: str,
    expected_identity: str,
    expected_kind: AuditDatabaseKind,
    expected_customer: str | None,
    expected_role: str,
) -> None:
    """Fail closed on identity, relational signature, role or privilege drift."""
    from erp_ai.infrastructure.postgres_audit.errors import AuditStorageUnavailable

    descriptor = (
        CONTROL_DESCRIPTOR if expected_kind is AuditDatabaseKind.CONTROL else CUSTOMER_DESCRIPTOR
    )
    try:
        if not 15 <= connection.info.server_version // 10_000 <= 18:
            raise AuditStorageUnavailable("audit storage contract is unavailable")
        database = await (
            await connection.execute("SELECT current_database(),current_user")
        ).fetchone()
        identity = await (
            await connection.execute(
                "SELECT database_kind,database_identity,customer_environment_id FROM erp_ai_audit.database_identity WHERE singleton=true"
            )
        ).fetchone()
        metadata = await (
            await connection.execute(
                "SELECT contract_version,contract_sha256 FROM erp_ai_audit.contract_metadata WHERE singleton=true"
            )
        ).fetchone()
        if database != (expected_name, expected_role) or identity != (
            expected_kind.value,
            expected_identity,
            expected_customer,
        ):
            raise AuditStorageUnavailable("audit storage identity is unavailable")
        actual_rows = await (
            await connection.execute(
                "SELECT object.relname,attribute.attname,pg_catalog.format_type(attribute.atttypid,attribute.atttypmod) "
                "FROM pg_catalog.pg_class object JOIN pg_catalog.pg_namespace namespace ON namespace.oid=object.relnamespace "
                "JOIN pg_catalog.pg_attribute attribute ON attribute.attrelid=object.oid "
                "WHERE namespace.nspname='erp_ai_audit' AND object.relname=ANY(%s) "
                "AND attribute.attnum>0 AND NOT attribute.attisdropped "
                "ORDER BY array_position(%s::text[],object.relname),attribute.attnum",
                (
                    [name.split(".", 1)[1] for name, _ in descriptor[1]],
                    [name.split(".", 1)[1] for name, _ in descriptor[1]],
                ),
            )
        ).fetchall()
        actual: dict[str, list[ColumnSignature]] = {}
        for table, column, data_type in actual_rows:
            actual.setdefault(f"erp_ai_audit.{table}", []).append((str(column), str(data_type)))
        actual_tables = tuple((name, tuple(actual.get(name, ()))) for name, _ in descriptor[1])
        validate_contract_snapshot(
            descriptor=descriptor,
            reported_version=None if metadata is None else metadata[0],
            reported_digest=None if metadata is None else metadata[1],
            actual_tables=actual_tables,
        )
        role = await (
            await connection.execute(
                "SELECT rolname,rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolreplication "
                "FROM pg_roles WHERE rolname=current_user"
            )
        ).fetchone()
        creation = await (
            await connection.execute(
                "SELECT has_database_privilege(current_user,current_database(),'CREATE'),has_database_privilege(current_user,current_database(),'TEMP'),has_schema_privilege(current_user,'erp_ai_audit','CREATE')"
            )
        ).fetchone()
        if (
            role is None
            or any(bool(v) for v in role[1:])
            or creation is None
            or any(bool(v) for v in creation)
        ):
            raise AuditStorageUnavailable("audit storage role is unsafe")
        owners = await (
            await connection.execute(
                "SELECT DISTINCT owner.rolname,owner.rolsuper,owner.rolbypassrls "
                "FROM pg_class object JOIN pg_namespace namespace ON namespace.oid=object.relnamespace "
                "JOIN pg_roles owner ON owner.oid=object.relowner "
                "WHERE namespace.nspname='erp_ai_audit' AND object.relkind IN ('r','p')"
            )
        ).fetchall()
        database_owner = await (
            await connection.execute(
                "SELECT owner.rolname,owner.rolsuper,owner.rolbypassrls "
                "FROM pg_database database JOIN pg_roles owner ON owner.oid=database.datdba "
                "WHERE database.datname=current_database()"
            )
        ).fetchone()
        if (
            len(owners) != 1
            or database_owner is None
            or owners[0][0] != database_owner[0]
            or owners[0][0] == role[0]
        ):
            raise AuditStorageUnavailable("audit storage ownership is unsafe")
        if any(bool(value) for value in (*owners[0][1:], *database_owner[1:])):
            raise AuditStorageUnavailable("audit storage ownership is unsafe")
        grants = await (
            await connection.execute(
                "SELECT table_name,privilege_type FROM information_schema.role_table_grants "
                "WHERE grantee=current_user AND table_schema='erp_ai_audit' "
                "ORDER BY table_name,privilege_type"
            )
        ).fetchall()
        expected_grants = (
            ("contract_metadata", "SELECT"),
            ("database_identity", "SELECT"),
        )
        if tuple(grants) != expected_grants:
            raise AuditStorageUnavailable("audit storage grants are unsafe")
        column_grants = await (
            await connection.execute(
                "SELECT table_name,column_name,privilege_type FROM information_schema.column_privileges "
                "WHERE grantee=current_user AND table_schema='erp_ai_audit' "
                "AND privilege_type='INSERT' "
                "ORDER BY table_name,column_name,privilege_type"
            )
        ).fetchall()
        expected_columns = {
            "application_events": tuple(name for name, _ in APPLICATION_SIGNATURE[1][:-1]),
            "agent_events": tuple(name for name, _ in AGENT_SIGNATURE[1][:-1]),
            "tool_events": tuple(name for name, _ in TOOL_SIGNATURE[1][:-1]),
        }
        allowed_tables = (
            ("application_events",)
            if expected_kind is AuditDatabaseKind.CONTROL
            else ("agent_events", "tool_events")
        )
        expected_column_grants = tuple(
            sorted(
                (table, column, "INSERT")
                for table in allowed_tables
                for column in expected_columns[table]
            )
        )
        if tuple(column_grants) != expected_column_grants:
            raise AuditStorageUnavailable("audit storage column grants are unsafe")
        table_security = await (
            await connection.execute(
                "SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class object "
                "JOIN pg_namespace namespace ON namespace.oid=object.relnamespace "
                "WHERE namespace.nspname='erp_ai_audit' AND relname=ANY(%s) ORDER BY relname",
                ([name.split(".", 1)[1] for name, _ in descriptor[1][2:]],),
            )
        ).fetchall()
        expected_security = (
            (("application_events", False, False),)
            if expected_kind is AuditDatabaseKind.CONTROL
            else (("agent_events", True, True), ("tool_events", True, True))
        )
        if tuple(table_security) != expected_security:
            raise AuditStorageUnavailable("audit storage RLS is unsafe")
        triggers = await (
            await connection.execute(
                "SELECT event_object_table,trigger_name FROM information_schema.triggers "
                "WHERE trigger_schema='erp_ai_audit' ORDER BY event_object_table,trigger_name"
            )
        ).fetchall()
        expected_triggers = (
            (
                ("application_events", "application_events_idempotency"),
                ("application_events", "application_events_immutable"),
                ("application_events", "application_events_immutable"),
            )
            if expected_kind is AuditDatabaseKind.CONTROL
            else (
                ("agent_events", "agent_events_idempotency"),
                ("agent_events", "agent_events_immutable"),
                ("agent_events", "agent_events_immutable"),
                ("tool_events", "tool_events_idempotency"),
                ("tool_events", "tool_events_immutable"),
                ("tool_events", "tool_events_immutable"),
            )
        )
        if tuple(triggers) != expected_triggers:
            raise AuditStorageUnavailable("audit storage triggers are unsafe")
        if expected_kind is AuditDatabaseKind.CUSTOMER:
            policies = await (
                await connection.execute(
                    "SELECT tablename,policyname,cmd FROM pg_policies "
                    "WHERE schemaname='erp_ai_audit' ORDER BY tablename,policyname"
                )
            ).fetchall()
            if tuple(policies) != (
                ("agent_events", "agent_customer_digest", "SELECT"),
                ("agent_events", "agent_customer_insert", "INSERT"),
                ("tool_events", "tool_customer_digest", "SELECT"),
                ("tool_events", "tool_customer_insert", "INSERT"),
            ):
                raise AuditStorageUnavailable("audit storage policies are unsafe")
    except asyncio.CancelledError:
        raise
    except AuditStorageUnavailable:
        raise
    except Exception:
        raise AuditStorageUnavailable("audit storage verification failed") from None
