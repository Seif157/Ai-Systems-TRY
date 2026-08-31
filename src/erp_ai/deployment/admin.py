"""Explicit one-target administrative entry points; never imported by runtime startup."""

import asyncio
from pathlib import Path
from typing import Literal

import psycopg
from pydantic import BaseModel, ConfigDict, Field

from erp_ai.infrastructure.postgres.migrations import (
    grant_runtime_roles,
    provision_database_identity,
)
from erp_ai.infrastructure.postgres.migrations import (
    run_migrations as run_knowledge_migrations,
)
from erp_ai.infrastructure.postgres_audit import AuditDatabaseKind
from erp_ai.infrastructure.postgres_audit.migrations import (
    grant_writer_role,
    provision_identity,
)
from erp_ai.infrastructure.postgres_audit.migrations import (
    run_migrations as run_audit_migrations,
)

from .composition import compose_deployed_runtime
from .config import (
    MAXIMUM_CONFIG_BYTES,
    MAXIMUM_CONFIG_DEPTH,
    ProductionDeploymentConfig,
    _depth,
    _strict_json,
    load_production_config,
)
from .factory import ConfiguredProductionDependencyFactory
from .secrets import FileSecretProvider

ADMIN_CONFIG_PATH = Path("/etc/erp-ai/admin.json")
ADMIN_SECRET_ROOT = Path("/run/secrets/erp-ai-admin")


class AdministrativeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)

    contract_version: Literal["1.0.0"]
    target: Literal["control_audit", "customer_audit", "customer_knowledge"]
    migration_dsn_reference: str = Field(repr=False)
    expected_database_name: str = Field(repr=False)
    expected_migration_owner: str = Field(repr=False)
    database_identity: str = Field(repr=False)
    customer_environment_id: str | None = Field(default=None, repr=False)
    writer_role: str | None = Field(default=None, repr=False)
    reader_role: str | None = Field(default=None, repr=False)
    publisher_role: str | None = Field(default=None, repr=False)


def load_administrative_config(path: Path = ADMIN_CONFIG_PATH) -> AdministrativeConfig:
    try:
        raw = path.read_bytes()
        if not raw or len(raw) > MAXIMUM_CONFIG_BYTES:
            raise ValueError
        value = _strict_json(raw)
        if _depth(value) > MAXIMUM_CONFIG_DEPTH:
            raise ValueError
        return AdministrativeConfig.model_validate(value, strict=True)
    except Exception:
        raise ValueError("invalid administrative configuration") from None


async def _audit(  # pragma: no cover - live administrative PostgreSQL boundary
    target: Literal["control_audit", "customer_audit"],
) -> None:
    config = load_administrative_config()
    if config.target != target or not config.writer_role:
        raise ValueError("administrative target is unavailable")
    if (target == "control_audit") != (config.customer_environment_id is None):
        raise ValueError("administrative target is unavailable")
    dsn = (
        FileSecretProvider(ADMIN_SECRET_ROOT)
        .read_text(config.migration_dsn_reference)
        .get_secret_value()
    )
    kind = AuditDatabaseKind.CONTROL if target == "control_audit" else AuditDatabaseKind.CUSTOMER
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        await run_audit_migrations(
            connection,
            kind=kind,
            expected_database_name=config.expected_database_name,
            expected_migration_owner=config.expected_migration_owner,
        )
        await provision_identity(
            connection,
            kind=kind,
            database_identity=config.database_identity,
            customer_environment_id=config.customer_environment_id,
        )
        await grant_writer_role(connection, kind=kind, writer_role=config.writer_role)


async def _knowledge() -> None:  # pragma: no cover - live administrative PostgreSQL boundary
    config = load_administrative_config()
    if (
        config.target != "customer_knowledge"
        or not config.customer_environment_id
        or not config.reader_role
        or not config.publisher_role
    ):
        raise ValueError("administrative target is unavailable")
    dsn = (
        FileSecretProvider(ADMIN_SECRET_ROOT)
        .read_text(config.migration_dsn_reference)
        .get_secret_value()
    )
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        await run_knowledge_migrations(connection)
        await provision_database_identity(connection, config.customer_environment_id)
        await grant_runtime_roles(
            connection, reader_role=config.reader_role, publisher_role=config.publisher_role
        )


def _run(operation) -> None:  # type: ignore[no-untyped-def]
    try:
        asyncio.run(operation())
    except (KeyboardInterrupt, asyncio.CancelledError):
        raise
    except BaseException:
        raise SystemExit(1) from None


def migrate_control_audit() -> None:
    _run(lambda: _audit("control_audit"))


def migrate_customer_audit() -> None:
    _run(lambda: _audit("customer_audit"))


def migrate_customer_knowledge() -> None:
    _run(_knowledge)


async def _preflight() -> None:  # pragma: no cover - installed deployment boundary
    config: ProductionDeploymentConfig = load_production_config()
    runtime = compose_deployed_runtime(
        config, FileSecretProvider(), ConfiguredProductionDependencyFactory()
    )
    async with runtime.application.router.lifespan_context(runtime.application):
        if runtime.state.value != "ready":
            raise RuntimeError("production preflight failed")


def production_preflight() -> None:
    _run(_preflight)
