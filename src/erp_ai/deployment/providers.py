"""Exact production dependency construction interface."""

from typing import Protocol, runtime_checkable

from erp_ai.runtime import ExternalRuntimeBundle

from .config import ProductionDeploymentConfig
from .secrets import FileSecretProvider


@runtime_checkable
class ProductionDependencyFactory(Protocol):
    """Deployment implementation must build only the approved concrete provider graph."""

    def build(
        self, config: ProductionDeploymentConfig, secrets: FileSecretProvider
    ) -> ExternalRuntimeBundle: ...
