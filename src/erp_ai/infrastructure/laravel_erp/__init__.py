"""Strict internal Laravel ERP read-provider boundary."""

from .bundle import LaravelErpReadProviderBundle, LaravelProviderLifecycle
from .client import LaravelErpReadClient
from .config import LaravelErpReadConfig, validate_laravel_ssl_context
from .contracts import (
    LARAVEL_ERP_READ_CONTRACT_BYTES,
    LARAVEL_ERP_READ_CONTRACT_DIGEST,
    LARAVEL_ERP_READ_CONTRACT_VERSION,
    LARAVEL_ERP_READ_SERVICE_IDENTITY,
    LaravelContractMetadata,
)
from .errors import LaravelErpReadUnavailable
from .providers import LaravelHrCoreReadProvider, LaravelLeaveReadProvider

__all__ = [
    "LARAVEL_ERP_READ_CONTRACT_BYTES",
    "LARAVEL_ERP_READ_CONTRACT_DIGEST",
    "LARAVEL_ERP_READ_CONTRACT_VERSION",
    "LARAVEL_ERP_READ_SERVICE_IDENTITY",
    "LaravelContractMetadata",
    "LaravelErpReadClient",
    "LaravelErpReadConfig",
    "LaravelErpReadProviderBundle",
    "LaravelErpReadUnavailable",
    "LaravelHrCoreReadProvider",
    "LaravelLeaveReadProvider",
    "LaravelProviderLifecycle",
    "validate_laravel_ssl_context",
]
