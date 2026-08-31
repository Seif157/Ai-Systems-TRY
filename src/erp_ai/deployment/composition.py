"""Deployment composition entry with defensive validation and no import-time construction."""

from erp_ai.runtime import ComposedRuntime, compose_production_runtime

from .config import ProductionDeploymentConfig
from .providers import ProductionDependencyFactory
from .secrets import FileSecretProvider


def compose_deployed_runtime(
    config: ProductionDeploymentConfig,
    secrets: FileSecretProvider,
    factory: ProductionDependencyFactory,
) -> ComposedRuntime:
    if not isinstance(factory, ProductionDependencyFactory):
        raise TypeError("production dependency factory is required")
    copied = ProductionDeploymentConfig.model_validate(
        config.model_dump(mode="python"), strict=True
    )
    bundle = factory.build(copied, secrets)
    return compose_production_runtime(bundle)
