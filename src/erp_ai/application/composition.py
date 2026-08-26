"""Explicit dependency validation without concrete provider construction."""

from dataclasses import dataclass
from datetime import timedelta

from erp_ai.application.protocols import (
    ApplicationAuditSink,
    AuthorizationSnapshotVerifier,
    TrustedClock,
    TrustedRequestResolver,
)
from erp_ai.application.routing import TrustedRouteCatalog
from erp_ai.application.service import TrustedChatApplication
from erp_ai.capabilities import CapabilityRegistry
from erp_ai.orchestration import AgentOrchestrator


@dataclass(frozen=True, slots=True)
class ApplicationComposition:
    application: TrustedChatApplication


def compose_application(
    *,
    registry: CapabilityRegistry,
    orchestrator: AgentOrchestrator,
    resolver: TrustedRequestResolver,
    snapshot_verifier: AuthorizationSnapshotVerifier,
    route_catalog: TrustedRouteCatalog,
    audit_sink: ApplicationAuditSink,
    clock: TrustedClock,
    maximum_intent_lifetime: timedelta,
) -> ApplicationComposition:
    if orchestrator.registry is not registry:
        raise ValueError("composition registry must match the orchestrator")
    route_catalog.validate_startup(registry, orchestrator.tool_gateway)
    return ApplicationComposition(
        application=TrustedChatApplication(
            resolver,
            snapshot_verifier,
            route_catalog,
            orchestrator,
            audit_sink,
            clock,
            maximum_intent_lifetime,
        )
    )
