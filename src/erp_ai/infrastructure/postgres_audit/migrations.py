"""Checksum-pinned explicit audit database administration."""
# ruff: noqa: E501

import asyncio
import hashlib
from importlib.resources import files
from typing import Any

from psycopg import AsyncConnection, sql

from erp_ai.infrastructure.postgres_audit.contracts import (
    CONTRACT_VERSION,
    CONTROL_DESCRIPTOR,
    CUSTOMER_DESCRIPTOR,
    AuditDatabaseKind,
    contract_digest,
)
from erp_ai.infrastructure.postgres_audit.errors import AuditMigrationError

CONTROL_MIGRATIONS = ("0001_control_audit.sql",)
CUSTOMER_MIGRATIONS = ("0001_customer_audit.sql",)
_MIGRATION_LOCK_ID = 7_301_230_023


def migration_bytes(kind: AuditDatabaseKind, name: str) -> bytes:
    allowed = CONTROL_MIGRATIONS if kind is AuditDatabaseKind.CONTROL else CUSTOMER_MIGRATIONS
    if name not in allowed:
        raise AuditMigrationError("unknown audit migration resource")
    package = f"erp_ai.infrastructure.postgres_audit.sql.{kind.value}"
    return files(package).joinpath(name).read_bytes()


def migration_checksums(kind: AuditDatabaseKind) -> tuple[tuple[str, str], ...]:
    names = CONTROL_MIGRATIONS if kind is AuditDatabaseKind.CONTROL else CUSTOMER_MIGRATIONS
    return tuple((name, hashlib.sha256(migration_bytes(kind, name)).hexdigest()) for name in names)


async def run_migrations(  # pragma: no cover - opt-in PostgreSQL boundary
    connection: AsyncConnection[tuple[Any, ...]],
    *,
    kind: AuditDatabaseKind,
    expected_database_name: str,
    expected_migration_owner: str,
) -> None:
    try:
        if not 15 <= connection.info.server_version // 10_000 <= 18:
            raise AuditMigrationError("unsupported PostgreSQL major version")
        async with connection.transaction():
            authority = await (
                await connection.execute(
                    "SELECT current_database(),current_user,role.rolsuper,role.rolbypassrls,"
                    "role.rolcreatedb,role.rolcreaterole,role.rolreplication,owner.rolname "
                    "FROM pg_roles role JOIN pg_database database ON database.datname=current_database() "
                    "JOIN pg_roles owner ON owner.oid=database.datdba WHERE role.rolname=current_user"
                )
            ).fetchone()
            if authority != (
                expected_database_name,
                expected_migration_owner,
                False,
                False,
                False,
                False,
                False,
                expected_migration_owner,
            ):
                raise AuditMigrationError("audit migration authority is invalid")
            await connection.execute("SELECT pg_advisory_xact_lock(%s)", (_MIGRATION_LOCK_ID,))
            await connection.execute("CREATE SCHEMA IF NOT EXISTS erp_ai_audit_admin")
            await connection.execute(
                "CREATE TABLE IF NOT EXISTS erp_ai_audit_admin.schema_migrations (migration_name text PRIMARY KEY,sha256 text NOT NULL,applied_at timestamptz NOT NULL DEFAULT clock_timestamp())"
            )
            manifest = migration_checksums(kind)
            history = await (
                await connection.execute(
                    "SELECT migration_name,sha256 FROM erp_ai_audit_admin.schema_migrations "
                    "ORDER BY applied_at,migration_name"
                )
            ).fetchall()
            if tuple(history) not in tuple(manifest[:index] for index in range(len(manifest) + 1)):
                raise AuditMigrationError("audit migration history drift detected")
            for name, digest in manifest[len(history) :]:
                await connection.execute(migration_bytes(kind, name).decode())
                await connection.execute(
                    "INSERT INTO erp_ai_audit_admin.schema_migrations(migration_name,sha256) VALUES (%s,%s)",
                    (name, digest),
                )
    except asyncio.CancelledError:
        raise
    except AuditMigrationError:
        raise
    except Exception:
        raise AuditMigrationError("audit migrations failed") from None


async def provision_identity(  # pragma: no cover - opt-in PostgreSQL boundary
    connection: AsyncConnection[tuple[Any, ...]],
    *,
    kind: AuditDatabaseKind,
    database_identity: str,
    customer_environment_id: str | None,
) -> None:
    if (kind is AuditDatabaseKind.CONTROL) != (customer_environment_id is None):
        raise AuditMigrationError("audit identity kind mismatch")
    descriptor = CONTROL_DESCRIPTOR if kind is AuditDatabaseKind.CONTROL else CUSTOMER_DESCRIPTOR
    try:
        async with connection.transaction():
            existing = await (
                await connection.execute(
                    "SELECT database_kind,database_identity,customer_environment_id FROM erp_ai_audit.database_identity FOR UPDATE"
                )
            ).fetchone()
            expected = (kind.value, database_identity, customer_environment_id)
            if existing is not None and existing != expected:
                raise AuditMigrationError("audit database is already bound")
            if existing is None:
                await connection.execute(
                    "INSERT INTO erp_ai_audit.database_identity(singleton,database_kind,database_identity,customer_environment_id) VALUES (true,%s,%s,%s)",
                    expected,
                )
                await connection.execute(
                    "INSERT INTO erp_ai_audit.contract_metadata(singleton,contract_version,contract_sha256) VALUES (true,%s,%s)",
                    (CONTRACT_VERSION, contract_digest(descriptor)),
                )
    except asyncio.CancelledError:
        raise
    except AuditMigrationError:
        raise
    except Exception:
        raise AuditMigrationError("audit identity provisioning failed") from None


async def grant_writer_role(  # pragma: no cover - opt-in PostgreSQL boundary
    connection: AsyncConnection[tuple[Any, ...]],
    *,
    kind: AuditDatabaseKind,
    writer_role: str,
) -> None:
    try:
        async with connection.transaction():
            role = sql.Identifier(writer_role)
            await connection.execute(
                sql.SQL("REVOKE CREATE,TEMP ON DATABASE {} FROM PUBLIC").format(
                    sql.Identifier(connection.info.dbname)
                )
            )
            await connection.execute(
                sql.SQL("REVOKE ALL ON DATABASE {} FROM {}").format(
                    sql.Identifier(connection.info.dbname), role
                )
            )
            await connection.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(connection.info.dbname), role
                )
            )
            await connection.execute(
                sql.SQL("GRANT USAGE ON SCHEMA erp_ai_audit TO {}").format(role)
            )
            if kind is AuditDatabaseKind.CONTROL:
                await connection.execute(
                    sql.SQL(
                        "GRANT INSERT(request_id,stage,outcome,internal_reason,event_digest) "
                        "ON erp_ai_audit.application_events TO {}"
                    ).format(role)
                )
            else:
                await connection.execute(
                    sql.SQL(
                        "GRANT INSERT(request_id,customer_environment_id,user_id,purpose,action,"
                        "outcome,internal_reason,event_digest) ON erp_ai_audit.agent_events TO {}"
                    ).format(role)
                )
                await connection.execute(
                    sql.SQL(
                        "GRANT INSERT(request_id,customer_environment_id,user_id,tool_name,"
                        "tool_version,audit_action,data_classification,outcome,internal_reason,"
                        "purpose,event_digest) ON erp_ai_audit.tool_events TO {}"
                    ).format(role)
                )
            await connection.execute(
                sql.SQL(
                    "GRANT SELECT ON erp_ai_audit.database_identity, erp_ai_audit.contract_metadata TO {}"
                ).format(role)
            )
    except asyncio.CancelledError:
        raise
    except Exception:
        raise AuditMigrationError("audit writer grants failed") from None
