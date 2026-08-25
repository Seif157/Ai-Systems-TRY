"""Customer-isolated PostgreSQL adapters for structured ERP reads."""

from erp_ai.infrastructure.postgres_erp.config import (
    ErpCursorKey,
    ErpCursorKeyring,
    ErpDatabaseRouteConfig,
    StaticErpDatabaseConfig,
)
from erp_ai.infrastructure.postgres_erp.contract import (
    CONTRACT_VERSION,
    VIEW_SIGNATURES,
    contract_digest,
)
from erp_ai.infrastructure.postgres_erp.cursor import SignedLeaveRequestCursor
from erp_ai.infrastructure.postgres_erp.providers import (
    PostgresHrCoreReadProvider,
    PostgresLeaveReadProvider,
)
from erp_ai.infrastructure.postgres_erp.routing import StaticErpDatabaseRouter

__all__ = [
    "CONTRACT_VERSION",
    "VIEW_SIGNATURES",
    "ErpCursorKey",
    "ErpCursorKeyring",
    "ErpDatabaseRouteConfig",
    "PostgresHrCoreReadProvider",
    "PostgresLeaveReadProvider",
    "SignedLeaveRequestCursor",
    "StaticErpDatabaseConfig",
    "StaticErpDatabaseRouter",
    "contract_digest",
]
