"""Provider-neutral trusted application composition contracts."""

from erp_ai.application.audit import ApplicationAuditEvent
from erp_ai.application.composition import ApplicationComposition, compose_application
from erp_ai.application.models import (
    AuthorizationSnapshotDecision,
    TrustedRequestReference,
    TrustedResolution,
    TrustedRouteIntent,
)
from erp_ai.application.protocols import (
    ApplicationAuditSink,
    AuthorizationSnapshotVerifier,
    TrustedClock,
    TrustedRequestResolver,
)
from erp_ai.application.routing import TrustedRouteCatalog, TrustedRouteEntry
from erp_ai.application.service import TrustedChatApplication

__all__ = [
    "ApplicationAuditEvent",
    "ApplicationAuditSink",
    "ApplicationComposition",
    "AuthorizationSnapshotDecision",
    "AuthorizationSnapshotVerifier",
    "TrustedChatApplication",
    "TrustedClock",
    "TrustedRequestReference",
    "TrustedRequestResolver",
    "TrustedResolution",
    "TrustedRouteCatalog",
    "TrustedRouteEntry",
    "TrustedRouteIntent",
    "compose_application",
]
