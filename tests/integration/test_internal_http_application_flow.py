from datetime import timedelta

from fastapi.testclient import TestClient

from erp_ai.application import (
    AuthorizationSnapshotDecision,
    TrustedChatApplication,
    TrustedRequestReference,
    TrustedResolution,
    TrustedRouteIntent,
)
from erp_ai.orchestration import AnswerBasis, ModelFinalAnswer
from erp_ai.transport.http import (
    InternalHttpTransportConfig,
    TrustedIngressAuthenticationRequest,
    create_internal_http_app,
)
from tests.integration.test_agent_orchestration_flow import (
    NOW,
    ScriptedModel,
    call,
    context,
)
from tests.integration.test_agent_orchestration_flow import (
    build as build_orchestrator,
)
from tests.integration.test_trusted_application_flow import Audit, Clock, routes

REQUEST_ID = "123e4567-e89b-42d3-a456-426614174000"


class Authenticator:
    async def authenticate(
        self, request: TrustedIngressAuthenticationRequest
    ) -> TrustedRequestReference:
        return TrustedRequestReference(request_id=request.request_id, resolver_handle="opaque")


class Ids:
    def create(self) -> str:
        return REQUEST_ID


class Lifecycle:
    async def startup(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None


class Resolver:
    def __init__(self, intent_code: str, *, customer: str = "customer_a", resolved=None) -> None:  # type: ignore[no-untyped-def]
        self.intent_code = intent_code
        self.customer = customer
        self.resolved = resolved

    async def resolve(self, reference: TrustedRequestReference) -> TrustedResolution:
        trusted = (self.resolved or context()).model_copy(
            update={"request_id": reference.request_id, "customer_environment_id": self.customer}
        )
        return TrustedResolution(
            context=trusted,
            intent=TrustedRouteIntent(
                intent_contract_version=1,
                intent_code=self.intent_code,
                issued_at=NOW - timedelta(seconds=1),
                expires_at=NOW + timedelta(minutes=1),
                request_id=trusted.request_id,
                customer_environment_id=trusted.customer_environment_id,
                user_id=trusted.user_id,
                authorization_snapshot_id=trusted.authorization_snapshot_id,
            ),
        )


class Verifier:
    def __init__(self, status: str = "current") -> None:
        self.status = status

    async def verify(self, _: object) -> AuthorizationSnapshotDecision:
        return AuthorizationSnapshotDecision(status=self.status)  # type: ignore[arg-type]


def execute(
    intent: str,
    responses: list[object],
    *,
    resolved=None,  # type: ignore[no-untyped-def]
    customer: str = "customer_a",
    snapshot_status: str = "current",
    message: str = "Synthetic request",
):  # type: ignore[no-untyped-def]
    orchestrator, tool_audit, agent_audit, _ = build_orchestrator(ScriptedModel(responses))
    application_audit = Audit()
    application = TrustedChatApplication(
        Resolver(intent, customer=customer, resolved=resolved),
        Verifier(snapshot_status),
        routes(),
        orchestrator,
        application_audit,
        Clock(),
        timedelta(minutes=5),
    )
    app = create_internal_http_app(
        config=InternalHttpTransportConfig(allowed_hosts=("erp.internal",)),
        authenticator=Authenticator(),
        request_id_factory=Ids(),
        application=application,
        application_audit_sink=application_audit,
        lifecycle=Lifecycle(),
    )
    with TestClient(app) as client:
        response = client.post(
            "https://erp.internal/v1/chat",
            headers={
                "Authorization": "Bearer synthetic_assertion",
                "Content-Type": "application/json",
            },
            json={"message": message},
        )
    return response, application_audit, agent_audit, tool_audit


def test_http_general_route_preserves_single_application_and_agent_audit() -> None:
    response, application_audit, agent_audit, tool_audit = execute(
        "general_help",
        [
            ModelFinalAnswer(
                answer="General", answer_basis="general", evidence_call_ids=(), citation_ids=()
            )
        ],
        message="get_my_employee_profile must not select a tool",
    )
    assert response.status_code == 200
    assert (
        len(application_audit.attempts),
        len(agent_audit.attempts),
        len(tool_audit.attempts),
    ) == (
        1,
        1,
        0,
    )


def test_http_exact_erp_and_knowledge_routes_preserve_grounding_and_audit_counts() -> None:
    profile = execute(
        "employee_profile",
        [
            call("profile", "get_my_employee_profile", {}),
            ModelFinalAnswer(
                answer="Profile",
                answer_basis=AnswerBasis.ERP_DATA,
                evidence_call_ids=("profile",),
                citation_ids=(),
            ),
        ],
    )
    knowledge = execute(
        "knowledge_search",
        [
            call("knowledge", "search_hr_knowledge", {"query": "first"}),
            ModelFinalAnswer(
                answer="Knowledge",
                answer_basis=AnswerBasis.KNOWLEDGE,
                evidence_call_ids=("knowledge",),
                citation_ids=("cite_1",),
            ),
        ],
    )
    for response, application_audit, agent_audit, tool_audit in (profile, knowledge):
        assert response.status_code == 200
        assert (
            len(application_audit.attempts),
            len(agent_audit.attempts),
            len(tool_audit.attempts),
        ) == (1, 1, 1)
    assert knowledge[0].json()["citations"][0]["citation_id"] == "cite_1"


def test_http_disabled_module_missing_permission_and_stale_snapshot_fail_closed() -> None:
    cases = (
        ({"resolved": context(modules=(), permissions=("hr.profile.read_self",))}, 500),
        ({"resolved": context(modules=("hr_core",), permissions=())}, 500),
        ({"snapshot_status": "stale"}, 503),
    )
    for settings, expected_status in cases:
        response, application_audit, _, tool_audit = execute(
            "employee_profile",
            [],
            **settings,  # type: ignore[arg-type]
        )
        assert response.status_code == expected_status
        assert len(application_audit.attempts) == 1
        assert tool_audit.attempts == []


def test_http_customer_contexts_with_identical_employee_id_remain_independent() -> None:
    responses = [
        ModelFinalAnswer(
            answer="General", answer_basis="general", evidence_call_ids=(), citation_ids=()
        )
    ]
    first = execute("general_help", list(responses), customer="customer_a")
    second = execute("general_help", list(responses), customer="customer_b")
    assert first[0].status_code == second[0].status_code == 200
    assert len(first[1].attempts) == len(second[1].attempts) == 1
