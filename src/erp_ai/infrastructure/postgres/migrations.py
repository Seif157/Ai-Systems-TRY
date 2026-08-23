"""Explicit, checksum-pinned administrative migrations and identity provisioning."""

import asyncio
import hashlib
from importlib.resources import files
from typing import Any

from psycopg import AsyncConnection, sql

from erp_ai.context.models import Identifier
from erp_ai.infrastructure.postgres.errors import KnowledgeMigrationError

MIGRATIONS = (
    "0001_knowledge_schema.sql",
    "0002_knowledge_security.sql",
    "0003_knowledge_embeddings.sql",
)
SCHEMA_CONTRACT_VERSION = 1
_MIGRATION_LOCK_ID = 7_301_130_013


def _migration_bytes(name: str) -> bytes:
    if name not in MIGRATIONS:
        raise KnowledgeMigrationError("unknown migration resource")
    return files("erp_ai.infrastructure.postgres.sql").joinpath(name).read_bytes()


def validate_postgres_major(server_version: int) -> None:
    major = server_version // 10_000
    if not 15 <= major <= 18:
        raise KnowledgeMigrationError("unsupported PostgreSQL major version")


def validate_pgvector_version(value: str | None) -> None:
    if value is None:
        raise KnowledgeMigrationError("required vector extension is unavailable")
    try:
        parts = tuple(int(part) for part in value.split("."))
    except ValueError:
        raise KnowledgeMigrationError("required vector extension version is invalid") from None
    if parts < (0, 8, 6):
        raise KnowledgeMigrationError("required vector extension is too old")


async def run_migrations(  # pragma: no cover - opt-in PostgreSQL integration boundary
    connection: AsyncConnection[tuple[Any, ...]],
) -> None:
    """Run only packaged migrations; callers invoke this administrative boundary explicitly."""

    try:
        validate_postgres_major(connection.info.server_version)
        async with connection.transaction():
            await connection.execute("SELECT pg_advisory_xact_lock(%s)", (_MIGRATION_LOCK_ID,))
            await connection.execute("CREATE SCHEMA IF NOT EXISTS erp_ai_knowledge")
            await connection.execute(
                """CREATE TABLE IF NOT EXISTS erp_ai_knowledge.schema_migrations (
                migration_name text PRIMARY KEY,
                sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
                applied_at timestamptz NOT NULL DEFAULT clock_timestamp())"""
            )
            for name in MIGRATIONS:
                raw = _migration_bytes(name)
                digest = hashlib.sha256(raw).hexdigest()
                row = await (
                    await connection.execute(
                        """SELECT sha256 FROM erp_ai_knowledge.schema_migrations
                        WHERE migration_name=%s""",
                        (name,),
                    )
                ).fetchone()
                if row is not None:
                    if row[0] != digest:
                        raise KnowledgeMigrationError("migration checksum drift detected")
                    continue
                await connection.execute(raw.decode("utf-8"))
                await connection.execute(
                    """INSERT INTO erp_ai_knowledge.schema_migrations(migration_name, sha256)
                    VALUES (%s,%s)""",
                    (name, digest),
                )
            row = await (
                await connection.execute(
                    "SELECT extversion FROM pg_extension WHERE extname='vector'"
                )
            ).fetchone()
            validate_pgvector_version(None if row is None else str(row[0]))
    except asyncio.CancelledError:
        raise
    except KnowledgeMigrationError:
        raise
    except Exception:
        raise KnowledgeMigrationError("knowledge migrations failed") from None


async def provision_database_identity(  # pragma: no cover - integration boundary
    connection: AsyncConnection[tuple[Any, ...]], customer_environment_id: Identifier
) -> None:
    try:
        async with connection.transaction():
            row = await (
                await connection.execute(
                    """SELECT customer_environment_id
                    FROM erp_ai_knowledge.database_identity FOR UPDATE"""
                )
            ).fetchone()
            if row is None:
                await connection.execute(
                    """INSERT INTO erp_ai_knowledge.database_identity
                    (singleton, customer_environment_id, schema_contract_version)
                    VALUES (true,%s,%s)""",
                    (customer_environment_id, SCHEMA_CONTRACT_VERSION),
                )
            elif row[0] != customer_environment_id:
                raise KnowledgeMigrationError("knowledge database is already bound")
    except asyncio.CancelledError:
        raise
    except KnowledgeMigrationError:
        raise
    except Exception:
        raise KnowledgeMigrationError("database identity provisioning failed") from None


async def grant_runtime_roles(  # pragma: no cover - integration boundary
    connection: AsyncConnection[tuple[Any, ...]], *, reader_role: str, publisher_role: str
) -> None:
    """Grant fixed privilege templates; role identifiers are trusted deployment configuration."""

    try:
        async with connection.transaction():
            for role in (reader_role, publisher_role):
                await connection.execute(
                    sql.SQL("ALTER ROLE {} SET search_path = pg_catalog").format(
                        sql.Identifier(role)
                    )
                )
                await connection.execute(
                    sql.SQL("GRANT USAGE ON SCHEMA erp_ai_knowledge TO {}").format(
                        sql.Identifier(role)
                    )
                )
                await connection.execute(
                    sql.SQL(
                        "GRANT EXECUTE ON FUNCTION erp_ai_knowledge.runtime_customer_id() TO {}"
                    ).format(sql.Identifier(role))
                )
            await connection.execute(
                sql.SQL(
                    "GRANT SELECT ON erp_ai_knowledge.database_identity, "
                    "erp_ai_knowledge.active_generations, erp_ai_knowledge.generations, "
                    "erp_ai_knowledge.documents, erp_ai_knowledge.chunks, "
                    "erp_ai_knowledge.embedding_profiles, erp_ai_knowledge.embedding_sets, "
                    "erp_ai_knowledge.chunk_embeddings TO {}"
                ).format(sql.Identifier(reader_role))
            )
            await connection.execute(
                sql.SQL(
                    "GRANT SELECT ON erp_ai_knowledge.database_identity, "
                    "erp_ai_knowledge.generations, erp_ai_knowledge.active_generations, "
                    "erp_ai_knowledge.documents, erp_ai_knowledge.chunks, "
                    "erp_ai_knowledge.operations, erp_ai_knowledge.embedding_profiles, "
                    "erp_ai_knowledge.embedding_sets, erp_ai_knowledge.chunk_embeddings, "
                    "erp_ai_knowledge.embedding_operations TO {}"
                ).format(sql.Identifier(publisher_role))
            )
            await connection.execute(
                sql.SQL(
                    "GRANT INSERT ON erp_ai_knowledge.generations, "
                    "erp_ai_knowledge.active_generations, erp_ai_knowledge.documents, "
                    "erp_ai_knowledge.chunks, erp_ai_knowledge.operations, "
                    "erp_ai_knowledge.publication_audit_outbox, "
                    "erp_ai_knowledge.embedding_profiles, erp_ai_knowledge.embedding_sets, "
                    "erp_ai_knowledge.chunk_embeddings, erp_ai_knowledge.embedding_operations, "
                    "erp_ai_knowledge.embedding_audit_outbox TO {}"
                ).format(sql.Identifier(publisher_role))
            )
            await connection.execute(
                sql.SQL("GRANT UPDATE (status) ON erp_ai_knowledge.generations TO {}").format(
                    sql.Identifier(publisher_role)
                )
            )
            await connection.execute(
                sql.SQL(
                    "GRANT UPDATE (status, ready_at) ON erp_ai_knowledge.embedding_sets TO {}"
                ).format(sql.Identifier(publisher_role))
            )
            await connection.execute(
                sql.SQL(
                    "GRANT EXECUTE ON FUNCTION erp_ai_knowledge.validate_chunk_embedding() TO {}"
                ).format(sql.Identifier(publisher_role))
            )
            await connection.execute(
                sql.SQL(
                    "GRANT UPDATE (generation_id, generation_digest, "
                    "publication_contract_version) ON "
                    "erp_ai_knowledge.active_generations TO {}"
                ).format(sql.Identifier(publisher_role))
            )
    except asyncio.CancelledError:
        raise
    except Exception:
        raise KnowledgeMigrationError("runtime role grants failed") from None
