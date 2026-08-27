"""Externally provisioned, immutable production dependency bundle."""

import ssl
from dataclasses import dataclass, field
from datetime import timedelta

from erp_ai.application import TrustedClock, TrustedRouteCatalog, TrustedRouteEntry
from erp_ai.capabilities import CapabilityManifest, CapabilityRegistry
from erp_ai.infrastructure.erp_trust import ErpAssertionVerifierConfig, ErpTrustHttpConfig
from erp_ai.infrastructure.postgres_audit import RuntimeAuditDatabaseConfig
from erp_ai.orchestration import AgentLimits, AgentModelProvider
from erp_ai.tools import ReadToolHandler
from erp_ai.transport.http import InternalHttpTransportConfig, RequestIdFactory

from .lifecycle import ProviderLifecycleLease


@dataclass(frozen=True, slots=True, init=False)
class ExternalRuntimeBundle:
    transport_config: InternalHttpTransportConfig = field(repr=False)
    assertion_config: ErpAssertionVerifierConfig = field(repr=False)
    erp_trust_config: ErpTrustHttpConfig = field(repr=False)
    erp_ssl_context: ssl.SSLContext = field(repr=False)
    audit_config: RuntimeAuditDatabaseConfig = field(repr=False)
    route_catalog: TrustedRouteCatalog = field(repr=False)
    registry: CapabilityRegistry = field(repr=False)
    handlers: tuple[ReadToolHandler, ...] = field(repr=False)
    model_provider: AgentModelProvider = field(repr=False)
    provider_lifecycle_lease: ProviderLifecycleLease = field(repr=False)
    agent_limits: AgentLimits
    maximum_intent_lifetime: timedelta
    request_id_factory: RequestIdFactory = field(repr=False)
    clock: TrustedClock = field(repr=False)

    def __init__(
        self,
        *,
        transport_config: InternalHttpTransportConfig,
        assertion_config: ErpAssertionVerifierConfig,
        erp_trust_config: ErpTrustHttpConfig,
        erp_ssl_context: ssl.SSLContext,
        audit_config: RuntimeAuditDatabaseConfig,
        route_catalog: TrustedRouteCatalog,
        registry: CapabilityRegistry,
        handlers: tuple[ReadToolHandler, ...],
        model_provider: AgentModelProvider,
        provider_lifecycle_lease: ProviderLifecycleLease,
        agent_limits: AgentLimits,
        maximum_intent_lifetime: timedelta,
        request_id_factory: RequestIdFactory,
        clock: TrustedClock,
    ) -> None:
        values = {
            "transport_config": InternalHttpTransportConfig.model_validate(
                transport_config.model_dump(mode="python"), strict=True
            ),
            "assertion_config": ErpAssertionVerifierConfig.model_validate(
                assertion_config.model_dump(mode="python"), strict=True
            ),
            "erp_trust_config": ErpTrustHttpConfig.model_validate(
                erp_trust_config.model_dump(mode="python"), strict=True
            ),
            "audit_config": RuntimeAuditDatabaseConfig.model_validate(
                audit_config.model_dump(mode="python"), strict=True
            ),
            "agent_limits": AgentLimits.model_validate(
                agent_limits.model_dump(mode="python"), strict=True
            ),
        }
        if not isinstance(erp_ssl_context, ssl.SSLContext):
            raise TypeError("ERP trust SSL context is required")
        for dependency, protocol, label in (
            (model_provider, AgentModelProvider, "model provider"),
            (request_id_factory, RequestIdFactory, "request ID factory"),
            (clock, TrustedClock, "clock"),
        ):
            if not isinstance(dependency, protocol):
                raise TypeError(f"{label} is required")
        if not isinstance(provider_lifecycle_lease, ProviderLifecycleLease):
            raise TypeError("provider lifecycle lease is required")
        rebuilt_registry = CapabilityRegistry(
            CapabilityManifest.model_validate(item.model_dump(mode="python"), strict=True)
            for item in registry.manifests
        )
        rebuilt_catalog = TrustedRouteCatalog(
            TrustedRouteEntry.model_validate(item.model_dump(mode="python"), strict=True)
            for item in route_catalog.entries
        )
        frozen_handlers = tuple(handlers)
        if maximum_intent_lifetime <= timedelta(0):
            raise ValueError("maximum intent lifetime must be positive")
        for name, value in values.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "erp_ssl_context", erp_ssl_context)
        object.__setattr__(self, "route_catalog", rebuilt_catalog)
        object.__setattr__(self, "registry", rebuilt_registry)
        object.__setattr__(self, "handlers", frozen_handlers)
        object.__setattr__(self, "model_provider", model_provider)
        object.__setattr__(self, "provider_lifecycle_lease", provider_lifecycle_lease)
        object.__setattr__(self, "maximum_intent_lifetime", maximum_intent_lifetime)
        object.__setattr__(self, "request_id_factory", request_id_factory)
        object.__setattr__(self, "clock", clock)
