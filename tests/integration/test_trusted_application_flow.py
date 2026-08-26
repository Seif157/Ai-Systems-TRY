import asyncio
from datetime import timedelta

from pydantic import SecretStr

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
)
from erp_ai.orchestration import (
    AgentRouteMode,
    AgentRoutingPolicy,
    AnswerBasis,
    ModelFinalAnswer,
    PublicChatFailure,
    PublicChatSuccess,
)
from tests.integration.test_agent_orchestration_flow import (
    NOW,
    ScriptedModel,
    build,
    call,
    context,
)


class Resolver:
    def __init__(
        self, intent_code: str, *, customer: str = "customer_a", resolved_context=None
    ) -> None:  # type: ignore[no-untyped-def]
        self.intent_code = intent_code
        self.customer = customer
        self.resolved_context = resolved_context

    async def resolve(self, reference: TrustedRequestReference) -> TrustedResolution:
        ctx = (self.resolved_context or context()).model_copy(
            update={"customer_environment_id": self.customer}
        )
        return TrustedResolution(
            context=ctx,
            intent=TrustedRouteIntent(
                intent_contract_version=1,
                intent_code=self.intent_code,
                issued_at=NOW - timedelta(seconds=1),
                expires_at=NOW + timedelta(minutes=1),
                request_id=ctx.request_id,
                customer_environment_id=ctx.customer_environment_id,
                user_id=ctx.user_id,
                authorization_snapshot_id=ctx.authorization_snapshot_id,
            ),
        )


class Verifier:
    async def verify(self, context: object) -> AuthorizationSnapshotDecision:
        return AuthorizationSnapshotDecision(status="current")


class Clock:
    def now(self):  # type: ignore[no-untyped-def]
        return NOW


class Audit:
    def __init__(self, fails: bool = False) -> None:
        self.attempts: list[ApplicationAuditEvent] = []
        self.fails = fails

    async def record(self, event: ApplicationAuditEvent) -> None:
        self.attempts.append(event)
        if self.fails:
            raise RuntimeError("private application audit failure")


def routes() -> TrustedRouteCatalog:
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
                    tool_name="get_my_employee_profile",
                    version="1.0.0",
                ),
            ),
            TrustedRouteEntry(
                intent_code="knowledge_search",
                route=AgentRoutingPolicy(
                    mode=AgentRouteMode.EXACT_READ_THEN_FINAL,
                    tool_name="search_hr_knowledge",
                    version="1.0.0",
                ),
            ),
        )
    )


def run(
    intent_code: str,
    responses: list[object],
    *,
    customer: str = "customer_a",
    resolved_context=None,
):  # type: ignore[no-untyped-def]
    orchestrator, tool_audit, agent_audit, _ = build(ScriptedModel(responses))
    application_audit = Audit()
    app = TrustedChatApplication(
        Resolver(intent_code, customer=customer, resolved_context=resolved_context),
        Verifier(),
        routes(),
        orchestrator,
        application_audit,
        Clock(),
        timedelta(minutes=5),
    )
    result = asyncio.run(
        app.execute(
            PublicChatRequest(message="The same free-form text never selects the route."),
            TrustedRequestReference(
                request_id="request_agent_1", resolver_handle=SecretStr("opaque")
            ),
        )
    )
    return result, application_audit, agent_audit, tool_audit


def test_general_application_flow_has_application_and_agent_audit_only() -> None:
    result, application_audit, agent_audit, tool_audit = run(
        "general_help",
        [
            ModelFinalAnswer(
                answer="General", answer_basis="general", evidence_call_ids=(), citation_ids=()
            )
        ],
    )
    assert isinstance(result, PublicChatSuccess)
    assert (
        len(application_audit.attempts),
        len(agent_audit.attempts),
        len(tool_audit.attempts),
    ) == (1, 1, 0)


def test_structured_and_knowledge_routes_are_grounded_and_audited_once() -> None:
    structured = [
        call("profile", "get_my_employee_profile", {}),
        ModelFinalAnswer(
            answer="Profile",
            answer_basis=AnswerBasis.ERP_DATA,
            evidence_call_ids=("profile",),
            citation_ids=(),
        ),
    ]
    result, app_audit, agent_audit, tool_audit = run("employee_profile", structured)
    assert isinstance(result, PublicChatSuccess)
    assert (len(app_audit.attempts), len(agent_audit.attempts), len(tool_audit.attempts)) == (
        1,
        1,
        1,
    )

    knowledge = [
        call("knowledge", "search_hr_knowledge", {"query": "first"}),
        ModelFinalAnswer(
            answer="Knowledge",
            answer_basis=AnswerBasis.KNOWLEDGE,
            evidence_call_ids=("knowledge",),
            citation_ids=("cite_1",),
        ),
    ]
    result, app_audit, agent_audit, tool_audit = run("knowledge_search", knowledge)
    assert isinstance(result, PublicChatSuccess)
    assert result.citations[0].citation_id == "cite_1"
    assert (len(app_audit.attempts), len(agent_audit.attempts), len(tool_audit.attempts)) == (
        1,
        1,
        1,
    )


def test_customer_identity_does_not_change_route_and_audit_stays_minimal() -> None:
    response = [
        ModelFinalAnswer(
            answer="General", answer_basis="general", evidence_call_ids=(), citation_ids=()
        )
    ]
    first = run("general_help", list(response), customer="customer_a")
    second = run("general_help", list(response), customer="customer_b")
    assert isinstance(first[0], PublicChatSuccess) and isinstance(second[0], PublicChatSuccess)
    for audit in (first[1], second[1]):
        serialized = repr(audit.attempts[0].model_dump())
        assert "customer_a" not in serialized and "customer_b" not in serialized


def test_unknown_intent_fails_before_agent_and_tool_audits() -> None:
    result, application_audit, agent_audit, tool_audit = run("unknown", [])
    assert isinstance(result, PublicChatFailure)
    assert (
        len(application_audit.attempts),
        len(agent_audit.attempts),
        len(tool_audit.attempts),
    ) == (1, 0, 0)


def test_disabled_module_and_missing_permission_do_not_reach_gateway() -> None:
    for denied_context in (
        context(modules=(), permissions=("hr.profile.read_self",)),
        context(modules=("hr_core",), permissions=()),
    ):
        result, application_audit, agent_audit, tool_audit = run(
            "employee_profile", [], resolved_context=denied_context
        )
        assert isinstance(result, PublicChatFailure)
        assert (
            len(application_audit.attempts),
            len(agent_audit.attempts),
            len(tool_audit.attempts),
        ) == (1, 1, 0)
