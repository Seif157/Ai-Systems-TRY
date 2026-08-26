import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from erp_ai.api import PublicChatRequest
from erp_ai.application import (
    ApplicationAuditEvent,
    AuthorizationSnapshotDecision,
    TrustedChatApplication,
    TrustedRequestReference,
    TrustedResolution,
    TrustedRouteCatalog,
    TrustedRouteEntry,
    TrustedRouteIntent,
    compose_application,
)
from erp_ai.capabilities import (
    CapabilityManifest,
    CapabilityRegistry,
    DataClassification,
    ToolDescriptor,
)
from erp_ai.context import TrustedRequestContext
from erp_ai.orchestration import (
    AgentRouteMode,
    AgentRoutingPolicy,
    PublicChatFailure,
    PublicChatSuccess,
)
from erp_ai.tools import ReadToolGateway

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=ZoneInfo("Africa/Cairo"))


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class EmptyOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Handler:
    tool_name = "read_profile"
    version = "1.0.0"
    input_model = EmptyInput
    output_model = EmptyOutput

    async def execute(self, context: TrustedRequestContext, arguments: BaseModel) -> object:
        return EmptyOutput()


class ToolSink:
    async def record(self, event: object) -> None:
        return None


def registry(operation: str = "read") -> CapabilityRegistry:
    return CapabilityRegistry(
        (
            CapabilityManifest(
                capability_code="profile",
                version="1.0.0",
                required_modules=("hr_core",),
                tools=(
                    ToolDescriptor(
                        tool_name="read_profile",
                        version="1.0.0",
                        operation=operation,
                        required_permissions_all=(),
                        required_roles_any=(),
                        allowed_purposes=("employee_self_service",),
                        data_classification=DataClassification.RESTRICTED,
                        audit_action="profile.read",
                    ),
                ),
            ),
        )
    )


def gateway(actual_registry: CapabilityRegistry | None = None) -> ReadToolGateway:
    selected = actual_registry or registry()
    handlers = (Handler(),) if selected.manifests[0].tools[0].operation == "read" else ()
    return ReadToolGateway(selected, handlers, ToolSink())


def context(**changes: object) -> TrustedRequestContext:
    values: dict[str, object] = {
        "context_version": 1,
        "request_id": "request_1",
        "customer_environment_id": "customer_a",
        "user_id": "user_a",
        "employee_id": "employee_1",
        "roles": ("employee",),
        "permission_codes": (),
        "legal_entity_ids": ("entity_1",),
        "enabled_modules": ("hr_core",),
        "locale": "en",
        "timezone": "Africa/Cairo",
        "purpose": "employee_self_service",
        "issued_at": NOW,
        "authorization_snapshot_id": "snapshot_1",
    }
    values.update(changes)
    return TrustedRequestContext.model_validate(values)


def intent(**changes: object) -> TrustedRouteIntent:
    values: dict[str, object] = {
        "intent_contract_version": 1,
        "intent_code": "general_help",
        "issued_at": NOW - timedelta(seconds=1),
        "expires_at": NOW + timedelta(minutes=1),
        "request_id": "request_1",
        "customer_environment_id": "customer_a",
        "user_id": "user_a",
        "authorization_snapshot_id": "snapshot_1",
    }
    values.update(changes)
    return TrustedRouteIntent.model_validate(values)


def reference() -> TrustedRequestReference:
    return TrustedRequestReference(
        request_id="request_1", resolver_handle=SecretStr("opaque-private-handle")
    )


class Resolver:
    def __init__(self, value: object) -> None:
        self.value = value
        self.calls = 0

    async def resolve(self, supplied: TrustedRequestReference) -> TrustedResolution:
        self.calls += 1
        if isinstance(self.value, BaseException):
            raise self.value
        return self.value  # type: ignore[return-value]


class Verifier:
    def __init__(self, value: object = AuthorizationSnapshotDecision(status="current")) -> None:
        self.value = value
        self.calls = 0

    async def verify(self, supplied: TrustedRequestContext) -> AuthorizationSnapshotDecision:
        self.calls += 1
        if isinstance(self.value, BaseException):
            raise self.value
        return self.value  # type: ignore[return-value]


class Clock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return self.value


class AuditSink:
    def __init__(self, fails: bool = False) -> None:
        self.events: list[ApplicationAuditEvent] = []
        self.attempts = 0
        self.fails = fails

    async def record(self, event: ApplicationAuditEvent) -> None:
        self.attempts += 1
        if self.fails:
            raise RuntimeError("private audit failure")
        self.events.append(event)


class Orchestrator:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls = 0

    async def execute(self, *args: object) -> object:
        self.calls += 1
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def catalog() -> TrustedRouteCatalog:
    return TrustedRouteCatalog(
        (
            TrustedRouteEntry(
                intent_code="general_help",
                route=AgentRoutingPolicy(mode=AgentRouteMode.GENERAL_ONLY),
            ),
            TrustedRouteEntry(
                intent_code="employee_profile",
                route=AgentRoutingPolicy(
                    mode=AgentRouteMode.EXACT_READ_THEN_FINAL,
                    tool_name="read_profile",
                    version="1.0.0",
                ),
            ),
        )
    )


def application(
    *,
    resolved: object | None = None,
    verification: object = AuthorizationSnapshotDecision(status="current"),
    result: object | None = None,
    clock: Clock | None = None,
    audit: AuditSink | None = None,
) -> tuple[TrustedChatApplication, Resolver, Verifier, Orchestrator, AuditSink]:
    resolver = Resolver(resolved or TrustedResolution(context=context(), intent=intent()))
    verifier = Verifier(verification)
    orchestrator = Orchestrator(
        result or PublicChatSuccess(answer="Synthetic", response_language="en", citations=())
    )
    sink = audit or AuditSink()
    app = TrustedChatApplication(
        resolver, verifier, catalog(), orchestrator, sink, clock or Clock(), timedelta(minutes=5)
    )
    return app, resolver, verifier, orchestrator, sink


def execute(app: TrustedChatApplication, ref: TrustedRequestReference | None = None) -> object:
    return asyncio.run(app.execute(PublicChatRequest(message="Synthetic help"), ref or reference()))


def test_reference_intent_and_audit_models_are_strict_private_and_revalidated() -> None:
    ref = reference()
    assert "opaque-private-handle" not in repr(ref)
    assert set(ApplicationAuditEvent.model_fields) == {
        "request_id",
        "stage",
        "outcome",
        "internal_reason",
    }
    for model in (ref, intent()):
        with pytest.raises(ValidationError):
            model.__class__.model_validate({**model.model_dump(), "unknown": True}, strict=True)
    with pytest.raises(ValidationError):
        TrustedRouteIntent.model_validate(
            intent().model_copy(update={"issued_at": NOW.replace(tzinfo=None)}), strict=True
        )
    constructed = TrustedRequestReference.model_construct(request_id="", resolver_handle="private")
    with pytest.raises(ValidationError):
        TrustedRequestReference.model_validate(constructed, strict=True)
    with pytest.raises(ValidationError):
        TrustedRouteIntent(
            intent_contract_version=2, **intent().model_dump(exclude={"intent_contract_version"})
        )
    marker = "distinctive-customer-user-snapshot-marker"
    private_intent = intent().model_copy(
        update={
            "request_id": marker,
            "customer_environment_id": marker,
            "user_id": marker,
            "authorization_snapshot_id": marker,
        }
    )
    assert marker not in repr(private_intent)
    invalid_payload = private_intent.model_dump()
    invalid_payload["expires_at"] = "not-a-datetime"
    with pytest.raises(ValidationError) as caught:
        TrustedRouteIntent.model_validate(invalid_payload, strict=True)
    assert marker not in str(caught.value)


def test_catalog_is_deterministic_immutable_and_validates_installed_reads() -> None:
    routes = catalog()
    assert tuple(item.intent_code for item in routes.entries) == (
        "employee_profile",
        "general_help",
    )
    routes.validate_startup(registry(), gateway())
    assert routes.resolve("general_help").mode is AgentRouteMode.GENERAL_ONLY
    with pytest.raises(KeyError):
        routes.resolve("missing")
    with pytest.raises(ValueError):
        TrustedRouteCatalog((routes.entries[0], routes.entries[0]))
    for route in (
        AgentRoutingPolicy(
            mode=AgentRouteMode.EXACT_READ_THEN_FINAL, tool_name="missing", version="1.0.0"
        ),
        AgentRoutingPolicy(
            mode=AgentRouteMode.EXACT_READ_THEN_FINAL, tool_name="read_profile", version="2.0.0"
        ),
    ):
        invalid = TrustedRouteCatalog((TrustedRouteEntry(intent_code="bad", route=route),))
        with pytest.raises(ValueError):
            invalid.validate_startup(registry(), gateway())
    command_registry = registry("command")
    invalid = TrustedRouteCatalog(
        (
            TrustedRouteEntry(
                intent_code="bad",
                route=AgentRoutingPolicy(
                    mode=AgentRouteMode.EXACT_READ_THEN_FINAL,
                    tool_name="read_profile",
                    version="1.0.0",
                ),
            ),
        )
    )
    with pytest.raises(ValueError):
        invalid.validate_startup(command_registry, gateway(command_registry))

    caller_entries = [routes.entries[0]]
    copied = TrustedRouteCatalog(caller_entries)
    caller_entries.clear()
    assert len(copied.entries) == 1


def test_success_calls_each_boundary_once_and_audits_minimal_event() -> None:
    app, resolver, verifier, orchestrator, audit = application()
    result = execute(app)
    assert isinstance(result, PublicChatSuccess)
    assert (resolver.calls, verifier.calls, orchestrator.calls, audit.attempts) == (1, 1, 1, 1)
    assert audit.events[0].model_dump() == {
        "request_id": "request_1",
        "stage": "orchestration",
        "outcome": "success",
        "internal_reason": "completed",
    }
    assert "opaque-private-handle" not in repr(app)


def test_clock_is_read_once_and_maximum_lifetime_boundary_is_accepted() -> None:
    exact = intent(issued_at=NOW, expires_at=NOW + timedelta(minutes=5))
    server_clock = Clock(NOW)
    app, _, _, _, audit = application(
        resolved=TrustedResolution(context=context(), intent=exact), clock=server_clock
    )
    assert isinstance(execute(app), PublicChatSuccess)
    assert server_clock.calls == 1
    assert audit.events[0].outcome == "success"


@pytest.mark.parametrize(
    ("intent_changes", "clock_value", "reason"),
    (
        ({"issued_at": NOW + timedelta(seconds=1)}, NOW, "intent_future_issued"),
        ({"expires_at": NOW}, NOW, "intent_expired"),
        (
            {
                "issued_at": NOW - timedelta(minutes=2),
                "expires_at": NOW - timedelta(minutes=3),
            },
            NOW,
            "intent_lifetime_invalid",
        ),
        ({"expires_at": NOW + timedelta(minutes=10)}, NOW, "intent_lifetime_invalid"),
        ({"customer_environment_id": "other"}, NOW, "intent_context_binding_mismatch"),
        ({"user_id": "other"}, NOW, "intent_context_binding_mismatch"),
        ({"request_id": "other"}, NOW, "intent_context_binding_mismatch"),
        ({"authorization_snapshot_id": "other"}, NOW, "intent_context_binding_mismatch"),
    ),
)
def test_intent_freshness_and_binding_fail_before_authorization(
    intent_changes: dict[str, object], clock_value: datetime, reason: str
) -> None:
    resolved = TrustedResolution(context=context(), intent=intent(**intent_changes))
    app, _, verifier, orchestrator, audit = application(resolved=resolved, clock=Clock(clock_value))
    result = execute(app)
    assert isinstance(result, PublicChatFailure)
    assert verifier.calls == orchestrator.calls == 0
    assert audit.events[0].internal_reason == reason


def test_context_and_reference_binding_and_invalid_clock_fail_closed() -> None:
    resolved = TrustedResolution(context=context(request_id="other"), intent=intent())
    app, _, verifier, _, audit = application(resolved=resolved)
    assert isinstance(execute(app), PublicChatFailure)
    assert verifier.calls == 0
    assert audit.events[0].internal_reason == "intent_context_binding_mismatch"
    app, _, verifier, _, audit = application(clock=Clock(NOW.replace(tzinfo=None)))
    assert isinstance(execute(app), PublicChatFailure)
    assert verifier.calls == 0
    assert audit.events[0].internal_reason == "trusted_clock_invalid"


@pytest.mark.parametrize("status", ("stale", "revoked", "mismatched"))
def test_snapshot_denials_fail_before_routing(status: str) -> None:
    app, _, verifier, orchestrator, audit = application(
        verification=AuthorizationSnapshotDecision.model_validate({"status": status})
    )
    assert isinstance(execute(app), PublicChatFailure)
    assert verifier.calls == 1 and orchestrator.calls == 0
    assert audit.events[0].internal_reason == "authorization_snapshot_rejected"


def test_verifier_result_is_strict_and_optional_bindings_must_match() -> None:
    for invalid in ("current", True, AuthorizationSnapshotDecision.model_construct(status=True)):
        app, _, verifier, orchestrator, audit = application(verification=invalid)
        assert isinstance(execute(app), PublicChatFailure)
        assert verifier.calls == 1 and orchestrator.calls == 0
        assert audit.events[0].internal_reason == "authorization_snapshot_unavailable"

    with pytest.raises(ValidationError):
        AuthorizationSnapshotDecision(status="current", request_id="request_1")
    valid = AuthorizationSnapshotDecision(
        status="current",
        request_id="request_1",
        customer_environment_id="customer_a",
        user_id="user_a",
        authorization_snapshot_id="snapshot_1",
    )
    app, _, _, orchestrator, _ = application(verification=valid)
    assert isinstance(execute(app), PublicChatSuccess)
    assert orchestrator.calls == 1
    mismatched = valid.model_copy(update={"customer_environment_id": "other"})
    app, _, _, orchestrator, audit = application(verification=mismatched)
    assert isinstance(execute(app), PublicChatFailure)
    assert orchestrator.calls == 0
    assert audit.events[0].internal_reason == "authorization_snapshot_binding_mismatch"


def test_resolution_verifier_route_and_orchestrator_exceptions_are_generic() -> None:
    cases = (
        (
            RuntimeError("private resolution"),
            AuthorizationSnapshotDecision(status="current"),
            None,
            "trusted_resolution_failed",
        ),
        (None, RuntimeError("private verifier"), None, "authorization_snapshot_unavailable"),
        (
            None,
            AuthorizationSnapshotDecision.model_construct(status="unknown"),
            None,
            "authorization_snapshot_unavailable",
        ),
        (
            TrustedResolution(context=context(), intent=intent(intent_code="unknown")),
            AuthorizationSnapshotDecision(status="current"),
            None,
            "trusted_route_unavailable",
        ),
        (
            None,
            AuthorizationSnapshotDecision(status="current"),
            RuntimeError("private model"),
            "orchestrator_failed",
        ),
        (
            None,
            AuthorizationSnapshotDecision(status="current"),
            PublicChatSuccess.model_construct(answer="", response_language="en", citations=()),
            "orchestrator_failed",
        ),
        (
            None,
            AuthorizationSnapshotDecision(status="current"),
            object(),
            "orchestrator_failed",
        ),
    )
    for resolved, verification, result, reason in cases:
        app, _, _, _, audit = application(
            resolved=resolved, verification=verification, result=result
        )
        public = execute(app)
        assert isinstance(public, PublicChatFailure)
        assert "private" not in public.safe_message
        assert audit.events[0].internal_reason == reason


def test_application_audit_failure_withholds_success() -> None:
    app, _, _, _, audit = application(audit=AuditSink(fails=True))
    result = execute(app)
    assert isinstance(result, PublicChatFailure)
    assert result.safe_error_code.value == "AUDIT_UNAVAILABLE"
    assert audit.attempts == 1


def test_invalid_inputs_and_constructor_dependencies_fail_closed() -> None:
    app, resolver, _, _, audit = application()
    invalid = reference().model_copy(update={"request_id": ""})
    assert isinstance(execute(app, invalid), PublicChatFailure)
    assert resolver.calls == 0 and audit.attempts == 1
    dependencies = application()
    args = [
        dependencies[1],
        dependencies[2],
        catalog(),
        dependencies[3],
        dependencies[4],
        Clock(),
        timedelta(minutes=5),
    ]
    for index in (0, 1, 4, 5):
        invalid_args = list(args)
        invalid_args[index] = object()
        with pytest.raises(TypeError):
            TrustedChatApplication(*invalid_args)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        TrustedChatApplication(*args[:-1], timedelta(0))  # type: ignore[arg-type]


def test_cancellation_propagates_from_security_boundaries() -> None:
    for resolved, verification, result in (
        (asyncio.CancelledError(), AuthorizationSnapshotDecision(status="current"), None),
        (None, asyncio.CancelledError(), None),
        (None, AuthorizationSnapshotDecision(status="current"), asyncio.CancelledError()),
    ):
        app, *_ = application(resolved=resolved, verification=verification, result=result)
        with pytest.raises(asyncio.CancelledError):
            execute(app)

    class CancellingAudit:
        async def record(self, event: ApplicationAuditEvent) -> None:
            raise asyncio.CancelledError

    app, *_ = application(audit=CancellingAudit())  # type: ignore[arg-type]
    with pytest.raises(asyncio.CancelledError):
        execute(app)


def test_explicit_composition_validates_registry_identity_and_routes() -> None:
    actual_registry = registry()
    actual_gateway = gateway(actual_registry)
    dependencies = application()

    class ComposedOrchestrator:
        registry = actual_registry
        tool_gateway = actual_gateway

    composed = compose_application(
        registry=actual_registry,
        orchestrator=ComposedOrchestrator(),  # type: ignore[arg-type]
        resolver=dependencies[1],
        snapshot_verifier=dependencies[2],
        route_catalog=catalog(),
        audit_sink=dependencies[4],
        clock=Clock(),
        maximum_intent_lifetime=timedelta(minutes=5),
    )
    assert isinstance(composed.application, TrustedChatApplication)

    class MismatchedOrchestrator:
        registry = registry()
        tool_gateway = actual_gateway

    with pytest.raises(ValueError):
        compose_application(
            registry=actual_registry,
            orchestrator=MismatchedOrchestrator(),  # type: ignore[arg-type]
            resolver=dependencies[1],
            snapshot_verifier=dependencies[2],
            route_catalog=catalog(),
            audit_sink=dependencies[4],
            clock=Clock(),
            maximum_intent_lifetime=timedelta(minutes=5),
        )
