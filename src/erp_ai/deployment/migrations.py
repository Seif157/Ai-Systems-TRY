"""One-target-at-a-time administrative migration boundary."""

import asyncio
from enum import Enum
from typing import Protocol, runtime_checkable


class MigrationTarget(str, Enum):
    CONTROL_AUDIT = "control_audit"
    CUSTOMER_AUDIT = "customer_audit"
    CUSTOMER_KNOWLEDGE = "customer_knowledge"


@runtime_checkable
class AdministrativeMigration(Protocol):
    async def migrate_one(self, target: MigrationTarget, route_reference: str) -> None: ...


async def run_one_migration(
    migration: AdministrativeMigration, target: MigrationTarget, route_reference: str
) -> None:
    if not route_reference or route_reference == "*":
        raise ValueError("one explicit migration target is required")
    try:
        await migration.migrate_one(target, route_reference)
    except asyncio.CancelledError:
        raise
    except Exception:
        raise RuntimeError("migration failed") from None
