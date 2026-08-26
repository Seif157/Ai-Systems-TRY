"""Provider-neutral trusted application execution boundary."""

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta

from erp_ai.api import PublicChatRequest
from erp_ai.application.audit import ApplicationAuditEvent, ApplicationStage
from erp_ai.application.models import (
    AuthorizationSnapshotDecision,
    TrustedRequestReference,
    TrustedResolution,
)
from erp_ai.application.protocols import (
    ApplicationAuditSink,
    AuthorizationSnapshotVerifier,
    TrustedClock,
    TrustedRequestResolver,
)
from erp_ai.application.routing import TrustedRouteCatalog
from erp_ai.context import TrustedRequestContext
from erp_ai.orchestration import (
    AgentErrorCode,
    AgentOrchestrator,
    AgentRoutingPolicy,
    PublicChatFailure,
    PublicChatSuccess,
)
from erp_ai.orchestration.models import PublicChatResult

_UNAVAILABLE = "The assistant is temporarily unavailable."
_AUDIT_UNAVAILABLE = "The assistant response could not be safely recorded."


@dataclass(frozen=True, slots=True, init=False)
class TrustedChatApplication:
    resolver: TrustedRequestResolver = field(repr=False)
    snapshot_verifier: AuthorizationSnapshotVerifier = field(repr=False)
    route_catalog: TrustedRouteCatalog = field(repr=False)
    orchestrator: AgentOrchestrator = field(repr=False)
    audit_sink: ApplicationAuditSink = field(repr=False)
    clock: TrustedClock = field(repr=False)
    maximum_intent_lifetime: timedelta

    def __init__(
        self,
        resolver: TrustedRequestResolver,
        snapshot_verifier: AuthorizationSnapshotVerifier,
        route_catalog: TrustedRouteCatalog,
        orchestrator: AgentOrchestrator,
        audit_sink: ApplicationAuditSink,
        clock: TrustedClock,
        maximum_intent_lifetime: timedelta,
    ) -> None:
        if not isinstance(resolver, TrustedRequestResolver):
            raise TypeError("resolver must implement TrustedRequestResolver")
        if not isinstance(snapshot_verifier, AuthorizationSnapshotVerifier):
            raise TypeError("snapshot_verifier must implement AuthorizationSnapshotVerifier")
        if not isinstance(audit_sink, ApplicationAuditSink):
            raise TypeError("audit_sink must implement ApplicationAuditSink")
        if not isinstance(clock, TrustedClock):
            raise TypeError("clock must implement TrustedClock")
        if maximum_intent_lifetime <= timedelta(0):
            raise ValueError("maximum intent lifetime must be positive")
        object.__setattr__(self, "resolver", resolver)
        object.__setattr__(self, "snapshot_verifier", snapshot_verifier)
        object.__setattr__(self, "route_catalog", route_catalog)
        object.__setattr__(self, "orchestrator", orchestrator)
        object.__setattr__(self, "audit_sink", audit_sink)
        object.__setattr__(self, "clock", clock)
        object.__setattr__(self, "maximum_intent_lifetime", maximum_intent_lifetime)

    async def execute(
        self, request: PublicChatRequest, reference: TrustedRequestReference
    ) -> PublicChatResult:
        request_id = "unavailable"
        try:
            request = PublicChatRequest.model_validate(request.model_dump(), strict=True)
            reference = TrustedRequestReference.model_validate(reference, strict=True)
            request_id = reference.request_id
        except Exception:
            return await self._failure(request_id, "validation", "invalid_application_input")

        try:
            resolved = await self.resolver.resolve(reference)
            resolved = TrustedResolution.model_validate(resolved, strict=True)
            context = TrustedRequestContext.model_validate(
                resolved.context.model_dump(mode="python"), strict=True
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return await self._failure(request_id, "resolution", "trusted_resolution_failed")

        reason = self._resolution_reason(reference, resolved, context)
        if reason is not None:
            return await self._failure(request_id, "resolution", reason)

        try:
            decision = await self.snapshot_verifier.verify(context)
            decision = AuthorizationSnapshotDecision.model_validate(decision, strict=True)
            if decision.status != "current":
                return await self._failure(
                    request_id, "authorization", "authorization_snapshot_rejected"
                )
            if decision.request_id is not None and (
                decision.request_id != context.request_id
                or decision.customer_environment_id != context.customer_environment_id
                or decision.user_id != context.user_id
                or decision.authorization_snapshot_id != context.authorization_snapshot_id
            ):
                return await self._failure(
                    request_id, "authorization", "authorization_snapshot_binding_mismatch"
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            return await self._failure(
                request_id, "authorization", "authorization_snapshot_unavailable"
            )

        try:
            route = self.route_catalog.resolve(resolved.intent.intent_code)
            route = AgentRoutingPolicy.model_validate(route, strict=True)
        except Exception:
            return await self._failure(request_id, "routing", "trusted_route_unavailable")

        try:
            result = await self.orchestrator.execute(context, request, route)
            result_type = type(result)
            if result_type not in (PublicChatSuccess, PublicChatFailure):
                raise ValueError("orchestrator returned an invalid public result")
            result = result_type.model_validate(result.model_dump(mode="python"), strict=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            return await self._failure(request_id, "orchestration", "orchestrator_failed")
        return await self._finish(request_id, "orchestration", result, "completed")

    def _resolution_reason(
        self,
        reference: TrustedRequestReference,
        resolved: TrustedResolution,
        context: TrustedRequestContext,
    ) -> str | None:
        intent = resolved.intent
        now = self.clock.now()
        if now.tzinfo is None or now.utcoffset() is None:
            return "trusted_clock_invalid"
        if intent.expires_at <= intent.issued_at:
            return "intent_lifetime_invalid"
        if intent.issued_at > now:
            return "intent_future_issued"
        if intent.expires_at <= now:
            return "intent_expired"
        if intent.expires_at - intent.issued_at > self.maximum_intent_lifetime:
            return "intent_lifetime_invalid"
        bindings = (
            (intent.request_id, reference.request_id),
            (intent.request_id, context.request_id),
            (intent.customer_environment_id, context.customer_environment_id),
            (intent.user_id, context.user_id),
            (intent.authorization_snapshot_id, context.authorization_snapshot_id),
        )
        if any(left != right for left, right in bindings):
            return "intent_context_binding_mismatch"
        return None

    async def _failure(
        self, request_id: str, stage: ApplicationStage, reason: str
    ) -> PublicChatResult:
        result = PublicChatFailure(
            safe_error_code=AgentErrorCode.AGENT_UNAVAILABLE,
            safe_message=_UNAVAILABLE,
        )
        return await self._finish(request_id, stage, result, reason)

    async def _finish(
        self, request_id: str, stage: ApplicationStage, result: PublicChatResult, reason: str
    ) -> PublicChatResult:
        event = ApplicationAuditEvent(
            request_id=request_id,
            stage=stage,
            outcome="success" if not isinstance(result, PublicChatFailure) else "failure",
            internal_reason=reason,
        )
        try:
            await self.audit_sink.record(event)
        except asyncio.CancelledError:
            raise
        except Exception:
            return PublicChatFailure(
                safe_error_code=AgentErrorCode.AUDIT_UNAVAILABLE,
                safe_message=_AUDIT_UNAVAILABLE,
            )
        return result
