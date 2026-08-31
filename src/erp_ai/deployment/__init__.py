"""Explicit production deployment boundary; importing this package performs no I/O."""

from .config import (
    DEPLOYMENT_CONFIG_CONTRACT_DIGEST,
    DEPLOYMENT_CONFIG_CONTRACT_VERSION,
    ProductionDeploymentConfig,
    load_production_config,
)
from .secrets import FileSecretProvider

__all__ = [
    "DEPLOYMENT_CONFIG_CONTRACT_DIGEST",
    "DEPLOYMENT_CONFIG_CONTRACT_VERSION",
    "FileSecretProvider",
    "ProductionDeploymentConfig",
    "load_production_config",
]
