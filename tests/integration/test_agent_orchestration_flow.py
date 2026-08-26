import asyncio
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from erp_ai.api import PublicChatRequest
from erp_ai.capabilities import CapabilityRegistry
from erp_ai.capabilities.hr_core import (
    HR_CORE_MANIFEST,
    EmployeeProfileRecord,
    GetMyEmployeeProfileHandler,
)
from erp_ai.capabilities.hr_knowledge import (
    HR_KNOWLEDGE_MANIFEST,
    KnowledgeExcerpt,
    SearchHrKnowledgeHandler,
    SearchHrKnowledgeOutput,
)
from erp_ai.capabilities.leave import (
    LEAVE_MANIFEST,
    GetMyLeaveBalancesHandler,
    LeaveBalanceRecord,
)
from erp_ai.context import TrustedRequestContext
from erp_ai.knowledge import KnowledgeMatch, KnowledgeRetrievalRequest, KnowledgeSourceType
from erp_ai.orchestration import (
    AgentAuditEvent,
    AgentErrorCode,
    AgentLimits,
    AgentOrchestrator,
    AgentRouteMode,
    AgentRoutingPolicy,
    AnswerBasis,
    ModelFinalAnswer,
    ModelToolCall,
    ModelToolInteraction,
    ModelTurnRequest,
    PublicChatFailure,
    PublicChatSuccess,
    PublicCitation,
)
from erp_ai.orchestration.service import _SuccessfulEvidenceCall
from erp_ai.tools import PublicToolSuccess, ReadToolGateway, ToolAuditEvent

NOW = datetime(2026, 8, 23, 10, 0, tzinfo=ZoneInfo("Africa/Cairo"))


class ScriptedModel:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.requests: list[ModelTurnRequest] = []

    async def complete_turn(self, request: ModelTurnRequest) -> object:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class RecordingToolAuditSink:
    def __init__(self, *, fails: bool = False) -> None:
        self.events: list[ToolAuditEvent] = []
        self.attempts: list[ToolAuditEvent] = []
        self.fails = fails

    async def record(self, event: ToolAuditEvent) -> None:
        self.attempts.append(event)
        if self.fails:
            raise RuntimeError("private tool audit failure")
        self.events.append(event)


class RecordingAgentAuditSink:
    def __init__(self, *, fails: bool = False) -> None:
        self.events: list[AgentAuditEvent] = []
        self.attempts: list[AgentAuditEvent] = []
        self.fails = fails

    async def record(self, event: AgentAuditEvent) -> None:
        self.attempts.append(event)
        if self.fails:
            raise RuntimeError("private agent audit failure")
        self.events.append(event)


class FakeHrProvider:
    async def get_my_employee_profile(
        self,
        *,
        customer_environment_id: str,
        employee_id: str,
        authorized_legal_entity_ids: tuple[str, ...],
    ) -> EmployeeProfileRecord | None:
        return EmployeeProfileRecord(
            employee_id=employee_id,
            legal_entity_id="entity_1",
            employee_number="EMP-1",
            display_name="Synthetic Employee",
            work_email="employee@example.test",
            job_title=None,
            department_name=None,
            branch_name=None,
            legal_entity_name="Example",
            employment_status="active",
            hire_date=date(2024, 1, 1),
            manager_display_name=None,
            freshness_at=NOW,
        )


class FakeLeaveProvider:
    async def get_my_leave_balances(self, **kwargs: object) -> tuple[LeaveBalanceRecord, ...]:
        return (
            LeaveBalanceRecord(
                employee_id="employee_1",
                legal_entity_id="entity_1",
                leave_type_id="annual_id",
                leave_type_code="annual",
                leave_type_name="Annual",
                leave_type_name_local="سنوية",
                fiscal_year=2026,
                opening_days=Decimal("10"),
                accrued_days=Decimal("5"),
                used_days=Decimal("2"),
                pending_days=Decimal("1"),
                available_days=Decimal("12"),
                calculated_at=NOW,
                source_watermark="watermark_1",
                calculation_version="1.0.0",
            ),
        )

    async def list_my_leave_requests(self, **kwargs: object) -> object:
        raise AssertionError(kwargs)

    async def get_my_leave_request(self, **kwargs: object) -> object:
        raise AssertionError(kwargs)


class FakeKnowledgeProvider:
    def __init__(self) -> None:
        self.requests: list[KnowledgeRetrievalRequest] = []

    async def retrieve(self, request: KnowledgeRetrievalRequest) -> tuple[KnowledgeMatch, ...]:
        self.requests.append(request)
        if request.query == "third":
            return (
                knowledge_match("cite_4", "chunk_4", title="Third policy", score=0.9),
                knowledge_match("cite_3", "chunk_3", title="Third handbook", score=0.8),
            )
        suffix = "b" if request.query == "second" else "a"
        return (
            knowledge_match("cite_2", "chunk_2", title=f"Policy {suffix}", score=0.9),
            knowledge_match("cite_1", "chunk_1", title="Handbook", score=0.8),
        )


def knowledge_match(citation_id: str, chunk_id: str, *, title: str, score: float) -> KnowledgeMatch:
    return KnowledgeMatch(
        chunk_id=chunk_id,
        document_id=f"document_{chunk_id}",
        citation_id=citation_id,
        namespace="hr",
        source_type="customer_policy",
        customer_environment_id="customer_a",
        required_modules_all=("hr_core",),
        required_permissions_all=("hr.knowledge.read",),
        allowed_purposes=("employee_self_service",),
        legal_entity_ids=("entity_1",),
        data_classification="restricted",
        language="en",
        title=title,
        section="Leave",
        document_version="1.0.0",
        effective_from=NOW - timedelta(days=1),
        content="Untrusted retrieved policy content.",
        relevance_score=score,
    )


def context(
    *,
    modules: tuple[str, ...] = ("hr_core", "leave"),
    permissions: tuple[str, ...] = (
        "hr.profile.read_self",
        "hr.knowledge.read",
        "leave.balance.read_self",
    ),
    locale: str = "en",
) -> TrustedRequestContext:
    return TrustedRequestContext(
        context_version=1,
        request_id="request_agent_1",
        customer_environment_id="customer_a",
        user_id="user_a",
        employee_id="employee_1",
        roles=("employee",),
        permission_codes=permissions,
        legal_entity_ids=("entity_1",),
        enabled_modules=modules,
        locale=locale,
        timezone="Africa/Cairo",
        purpose="employee_self_service",
        issued_at=NOW,
        authorization_snapshot_id="snapshot_a",
    )


def call(call_id: str, tool: str, arguments: dict[str, object]) -> ModelToolCall:
    return ModelToolCall.from_arguments(
        call_id=call_id,
        tool_name=tool,
        version="1.0.0",
        arguments=arguments,
    )


def build(
    model: ScriptedModel,
    *,
    tool_sink: RecordingToolAuditSink | None = None,
    agent_sink: RecordingAgentAuditSink | None = None,
    limits: AgentLimits | None = None,
) -> tuple[
    AgentOrchestrator, RecordingToolAuditSink, RecordingAgentAuditSink, FakeKnowledgeProvider
]:
    registry = CapabilityRegistry((HR_CORE_MANIFEST, HR_KNOWLEDGE_MANIFEST, LEAVE_MANIFEST))
    actual_tool_sink = tool_sink or RecordingToolAuditSink()
    knowledge = FakeKnowledgeProvider()
    gateway = ReadToolGateway(
        registry,
        (
            GetMyEmployeeProfileHandler(FakeHrProvider()),
            GetMyLeaveBalancesHandler(FakeLeaveProvider()),
            SearchHrKnowledgeHandler(knowledge),
        ),
        actual_tool_sink,
    )
    actual_agent_sink = agent_sink or RecordingAgentAuditSink()
    return (
        AgentOrchestrator(registry, gateway, model, actual_agent_sink, limits),
        actual_tool_sink,
        actual_agent_sink,
        knowledge,
    )


def execute(
    orchestrator: AgentOrchestrator,
    *,
    ctx: TrustedRequestContext | None = None,
    language: str | None = None,
    route: AgentRoutingPolicy | None = None,
) -> PublicChatSuccess | PublicChatFailure:
    responses = orchestrator.model_provider.responses  # type: ignore[attr-defined]
    first = responses[0] if responses else None
    selected_route = route or (
        AgentRoutingPolicy(
            mode=AgentRouteMode.EXACT_READ_THEN_FINAL,
            tool_name=first.tool_name,
            version=first.version,
        )
        if isinstance(first, ModelToolCall)
        else AgentRoutingPolicy(mode=AgentRouteMode.GENERAL_ONLY)
    )
    return asyncio.run(
        orchestrator.execute(
            ctx or context(),
            PublicChatRequest(message="Help me", preferred_response_language=language),
            selected_route,
        )
    )


def assert_one_agent_audit(sink: RecordingAgentAuditSink) -> None:
    assert len(sink.attempts) == 1
    assert len(sink.events) == 1
    assert set(sink.events[0].model_dump()) == {
        "request_id",
        "customer_environment_id",
        "user_id",
        "purpose",
        "action",
        "outcome",
        "internal_reason",
    }


def test_final_answer_without_tools_and_language_separation() -> None:
    model = ScriptedModel(
        [
            ModelFinalAnswer(
                answer="مرحباً",
                answer_basis=AnswerBasis.GENERAL,
                evidence_call_ids=(),
                citation_ids=(),
            )
        ]
    )
    orchestrator, tool_sink, agent_sink, _ = build(model)
    result = execute(orchestrator, ctx=context(locale="en"), language="ar-EG")
    assert isinstance(result, PublicChatSuccess)
    assert result.response_language == "ar-EG"
    assert tool_sink.events == []
    assert model.requests[0].response_language == "ar-EG"
    assert_one_agent_audit(agent_sink)


def test_exact_route_rejects_direct_answer_before_gateway() -> None:
    model = ScriptedModel(
        [
            ModelFinalAnswer(
                answer="No", answer_basis="general", evidence_call_ids=(), citation_ids=()
            )
        ]
    )
    orchestrator, tool_sink, agent_sink, _ = build(model)
    route = AgentRoutingPolicy(
        mode=AgentRouteMode.EXACT_READ_THEN_FINAL,
        tool_name="get_my_employee_profile",
        version="1.0.0",
    )
    result = execute(orchestrator, route=route)
    assert isinstance(result, PublicChatFailure)
    assert tool_sink.attempts == []
    assert agent_sink.events[0].internal_reason == "required_tool_call_missing"


@pytest.mark.parametrize(
    ("tool_name", "version"),
    (("unknown_tool", "1.0.0"), ("get_my_employee_profile", "2.0.0")),
)
def test_unavailable_or_wrong_version_route_stops_before_model(
    tool_name: str, version: str
) -> None:
    model = ScriptedModel([])
    orchestrator, tool_sink, agent_sink, _ = build(model)
    route = AgentRoutingPolicy(
        mode=AgentRouteMode.EXACT_READ_THEN_FINAL,
        tool_name=tool_name,
        version=version,
    )
    result = execute(orchestrator, route=route)
    assert isinstance(result, PublicChatFailure)
    assert model.requests == []
    assert tool_sink.attempts == []
    assert agent_sink.events[0].internal_reason == "route_not_authorized"


def test_wrong_tool_call_is_rejected_before_gateway() -> None:
    model = ScriptedModel([call("wrong", "get_my_leave_balances", {})])
    orchestrator, tool_sink, agent_sink, _ = build(model)
    route = AgentRoutingPolicy(
        mode=AgentRouteMode.EXACT_READ_THEN_FINAL,
        tool_name="get_my_employee_profile",
        version="1.0.0",
    )
    result = execute(orchestrator, route=route)
    assert isinstance(result, PublicChatFailure)
    assert tool_sink.attempts == []
    assert agent_sink.events[0].internal_reason == "routed_tool_mismatch"


def test_constructed_invalid_route_is_audited_without_invocation() -> None:
    model = ScriptedModel([])
    orchestrator, tool_sink, agent_sink, _ = build(model)
    invalid = AgentRoutingPolicy.model_construct(
        mode=AgentRouteMode.EXACT_READ_THEN_FINAL, tool_name=None, version=None
    )
    result = execute(orchestrator, route=invalid)
    assert isinstance(result, PublicChatFailure)
    assert model.requests == []
    assert tool_sink.attempts == []
    assert agent_sink.events[0].internal_reason == "invalid_route"


def test_authorized_catalog_contains_schemas_but_no_governance_or_context() -> None:
    model = ScriptedModel(
        [
            ModelFinalAnswer(
                answer="Done", answer_basis="general", evidence_call_ids=(), citation_ids=()
            )
        ]
    )
    orchestrator, _, _, _ = build(model)
    execute(orchestrator, ctx=context(modules=("hr_core",), permissions=("hr.profile.read_self",)))
    turn = model.requests[0]
    assert turn.tools == ()
    serialized = repr(turn.model_dump())
    for forbidden in (
        "customer_a",
        "user_a",
        "employee_1",
        "snapshot_a",
        "denial",
        "audit_action",
        "data_classification",
        "required_modules",
        "required_permissions",
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("get_my_employee_profile", {}),
        ("get_my_leave_balances", {}),
    ],
)
def test_production_erp_tools_complete_through_gateway(
    tool_name: str, arguments: dict[str, object]
) -> None:
    model = ScriptedModel(
        [
            call("call_1", tool_name, arguments),
            ModelFinalAnswer(
                answer="Safe summary",
                answer_basis="erp_data",
                evidence_call_ids=("call_1",),
                citation_ids=(),
            ),
        ]
    )
    orchestrator, tool_sink, agent_sink, _ = build(model)
    result = execute(orchestrator)
    assert isinstance(result, PublicChatSuccess)
    assert len(tool_sink.events) == 1
    message = model.requests[1].interactions[0].tool_result
    assert message.content_trust == "untrusted_tool_result"
    assert message.call_id == "call_1"
    assert_one_agent_audit(agent_sink)


def test_multiple_turns_receive_exact_ordered_interactions_without_reexecution() -> None:
    raw = '{ "query" : "العربية and English" }'
    first = ModelToolCall.from_arguments_json(
        call_id="call_1",
        tool_name="search_hr_knowledge",
        version="1.0.0",
        arguments_json=raw,
    )
    second = call("call_2", "get_my_employee_profile", {})
    model = ScriptedModel(
        [
            first,
            second,
            ModelFinalAnswer(
                answer="Synthetic mixed answer",
                answer_basis="mixed",
                evidence_call_ids=("call_1", "call_2"),
                citation_ids=("cite_2",),
            ),
        ]
    )
    orchestrator, tool_sink, agent_sink, knowledge = build(model)

    result = execute(orchestrator)

    assert isinstance(result, PublicChatFailure)
    assert tuple(len(request.interactions) for request in model.requests) == (0, 1)
    assert model.requests[1].interactions[0].assistant_call.arguments_json == raw
    assert len(tool_sink.events) == 1
    assert len(knowledge.requests) == 1
    assert len(agent_sink.events) == 1


def test_default_four_call_limit_is_recomputed_from_complete_transcript() -> None:
    model = ScriptedModel(
        [
            call(f"call_{index}", "search_hr_knowledge", {"query": f"query_{index}"})
            for index in range(1, 6)
        ]
    )
    orchestrator, tool_sink, agent_sink, knowledge = build(model)

    result = execute(orchestrator)

    assert isinstance(result, PublicChatFailure)
    assert result.safe_error_code is AgentErrorCode.INVALID_MODEL_RESPONSE
    assert tuple(len(request.interactions) for request in model.requests) == (0, 1)
    assert len(tool_sink.events) == 1
    assert len(knowledge.requests) == 1
    assert agent_sink.events[0].internal_reason == "tool_call_not_allowed"


def test_constructed_transcript_bypasses_are_recomputed_fail_closed() -> None:
    source_model = ScriptedModel(
        [
            call("call_1", "get_my_employee_profile", {}),
            ModelFinalAnswer(
                answer="Synthetic",
                answer_basis="erp_data",
                evidence_call_ids=("call_1",),
                citation_ids=(),
            ),
        ]
    )
    source, _, _, _ = build(source_model)
    assert isinstance(execute(source), PublicChatSuccess)
    observed = source_model.requests[1].interactions[0]
    constructed_call = ModelToolCall.model_construct(
        response_type=observed.assistant_call.response_type,
        call_id=observed.assistant_call.call_id,
        tool_name=observed.assistant_call.tool_name,
        version=observed.assistant_call.version,
        arguments_json=observed.assistant_call.arguments_json,
        arguments=observed.assistant_call.arguments,
    )
    constructed = ModelToolInteraction.model_construct(
        assistant_call=constructed_call,
        tool_result=observed.tool_result,
    )
    limited, _, _, _ = build(
        ScriptedModel([]),
        limits=AgentLimits(
            maximum_tool_argument_bytes=1,
            maximum_tool_result_bytes=1,
        ),
    )

    assert limited._transcript_failure((constructed,)) == (
        AgentErrorCode.AGENT_LIMIT_REACHED,
        "tool_argument_limit_reached",
    )
    result_limited, _, _, _ = build(
        ScriptedModel([]), limits=AgentLimits(maximum_tool_result_bytes=1)
    )
    assert result_limited._transcript_failure((constructed,)) == (
        AgentErrorCode.AGENT_LIMIT_REACHED,
        "tool_result_size_limit_reached",
    )
    zero_limit, _, _, _ = build(ScriptedModel([]), limits=AgentLimits(maximum_tool_calls=0))
    assert zero_limit._transcript_failure((constructed,)) == (
        AgentErrorCode.AGENT_LIMIT_REACHED,
        "tool_call_limit_reached",
    )
    assert source._transcript_failure((constructed, constructed)) == (
        AgentErrorCode.INVALID_MODEL_RESPONSE,
        "duplicate_call_id",
    )
    invalid_call = ModelToolCall.model_construct(
        response_type="tool_call",
        call_id="private-call",
        tool_name="get_my_employee_profile",
        version="1.0.0",
        arguments_json='{"private_query":',
        arguments={},
    )
    invalid_interaction = ModelToolInteraction.model_construct(
        assistant_call=invalid_call,
        tool_result=observed.tool_result,
    )
    assert source._transcript_failure((invalid_interaction,)) == (
        AgentErrorCode.INVALID_MODEL_RESPONSE,
        "invalid_interaction_transcript",
    )


def test_pre_turn_transcript_failure_stops_before_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = ScriptedModel([])
    orchestrator, tool_sink, agent_sink, _ = build(model)
    monkeypatch.setattr(
        AgentOrchestrator,
        "_transcript_failure",
        lambda self, interactions: (
            AgentErrorCode.INVALID_MODEL_RESPONSE,
            "invalid_interaction_transcript",
        ),
    )

    result = execute(orchestrator)

    assert isinstance(result, PublicChatFailure)
    assert result.safe_error_code is AgentErrorCode.INVALID_MODEL_RESPONSE
    assert model.requests == []
    assert tool_sink.attempts == []
    assert agent_sink.events[0].internal_reason == "invalid_interaction_transcript"


def test_constructed_divergent_model_call_fails_before_gateway_invocation() -> None:
    invalid = ModelToolCall.model_construct(
        response_type="tool_call",
        call_id="call_1",
        tool_name="get_my_employee_profile",
        version="1.0.0",
        arguments_json='{"selected_request_id":"private"}',
        arguments={"selected_request_id": "different"},
    )
    model = ScriptedModel([invalid])
    orchestrator, tool_sink, agent_sink, _ = build(model)

    result = execute(orchestrator)

    assert isinstance(result, PublicChatFailure)
    assert result.safe_error_code is AgentErrorCode.INVALID_MODEL_RESPONSE
    assert tool_sink.attempts == []
    assert len(agent_sink.events) == 1
    serialized_public = json.dumps(result.model_dump(mode="json"), sort_keys=True)
    serialized_audit = json.dumps(agent_sink.events[0].model_dump(mode="json"), sort_keys=True)
    for sensitive in ("selected_request_id", "private", "different", "call_1"):
        assert sensitive not in serialized_public
        assert sensitive not in serialized_audit


def test_knowledge_flow_validates_citations_and_keeps_content_out_of_policy() -> None:
    model = ScriptedModel(
        [
            call("knowledge_1", "search_hr_knowledge", {"query": "policy"}),
            ModelFinalAnswer(
                answer="See policy.",
                answer_basis="knowledge",
                evidence_call_ids=("knowledge_1",),
                citation_ids=("cite_2", "cite_1"),
            ),
        ]
    )
    orchestrator, tool_sink, agent_sink, knowledge = build(model)
    result = execute(orchestrator)
    assert isinstance(result, PublicChatSuccess)
    assert tuple(item.citation_id for item in result.citations) == ("cite_2", "cite_1")
    assert len(knowledge.requests) == 1
    assert "Untrusted retrieved policy content." not in repr(model.requests[1].policy_instructions)
    assert "Untrusted retrieved policy content." in repr(
        model.requests[1].interactions[0].tool_result.model_dump()
    )
    assert len(tool_sink.events) == 1
    assert_one_agent_audit(agent_sink)


@pytest.mark.parametrize(
    ("tool_name", "ctx"),
    [
        ("unknown_tool", context()),
        (
            "get_my_leave_balances",
            context(modules=("hr_core",), permissions=("leave.balance.read_self",)),
        ),
    ],
)
def test_unknown_or_unauthorized_tool_failure_can_be_explained_by_model(
    tool_name: str, ctx: TrustedRequestContext
) -> None:
    model = ScriptedModel(
        [
            call("bad_1", tool_name, {}),
            ModelFinalAnswer(
                answer="That is unavailable.",
                answer_basis="general",
                evidence_call_ids=(),
                citation_ids=(),
            ),
        ]
    )
    orchestrator, tool_sink, agent_sink, _ = build(model)
    result = execute(orchestrator, ctx=ctx)
    assert isinstance(result, PublicChatFailure)
    assert model.requests == []
    assert len(tool_sink.events) == 0
    assert_one_agent_audit(agent_sink)


@pytest.mark.parametrize(
    ("responses", "limits", "expected_reason"),
    [
        (
            [
                call("same", "search_hr_knowledge", {"query": "first"}),
                call("same", "search_hr_knowledge", {"query": "second"}),
            ],
            None,
            "duplicate_call_id",
        ),
        (
            [
                call("one", "search_hr_knowledge", {"query": "first"}),
                call("two", "search_hr_knowledge", {"query": "first"}),
            ],
            None,
            "repeated_tool_invocation",
        ),
        (
            [call("one", "get_my_employee_profile", {})],
            AgentLimits(maximum_tool_calls=0),
            "tool_call_limit_reached",
        ),
        (
            [call("one", "get_my_employee_profile", {})],
            AgentLimits(maximum_model_turns=1),
            "model_turn_limit_reached",
        ),
    ],
)
def test_loop_integrity_limits_fail_safely(
    responses: list[object], limits: AgentLimits | None, expected_reason: str
) -> None:
    orchestrator, _, agent_sink, _ = build(ScriptedModel(responses), limits=limits)
    result = execute(orchestrator)
    assert isinstance(result, PublicChatFailure)
    assert result.safe_error_code in {
        AgentErrorCode.INVALID_MODEL_RESPONSE,
        AgentErrorCode.AGENT_LIMIT_REACHED,
    }
    assert agent_sink.events[0].internal_reason in {
        expected_reason,
        "tool_call_not_allowed",
        "route_resource_limit_reached",
    }
    assert_one_agent_audit(agent_sink)


def test_accumulated_tool_result_limit_fails_safely() -> None:
    model = ScriptedModel([call("one", "get_my_employee_profile", {})])
    orchestrator, _, agent_sink, _ = build(model, limits=AgentLimits(maximum_tool_result_bytes=1))
    result = execute(orchestrator)
    assert isinstance(result, PublicChatFailure)
    assert result.safe_error_code is AgentErrorCode.AGENT_LIMIT_REACHED
    assert agent_sink.events[0].internal_reason == "tool_result_size_limit_reached"


@pytest.mark.parametrize(
    "response",
    [RuntimeError("private model failure with query and record selector"), object()],
)
def test_provider_failure_and_malformed_response_are_safe(response: object) -> None:
    orchestrator, _, agent_sink, _ = build(ScriptedModel([response]))
    result = execute(orchestrator)
    assert isinstance(result, PublicChatFailure)
    assert "private" not in result.safe_message
    serialized_public = json.dumps(result.model_dump(mode="json"), sort_keys=True)
    serialized_audit = json.dumps(agent_sink.events[0].model_dump(mode="json"), sort_keys=True)
    for sensitive in ("query", "record selector", "private model failure"):
        assert sensitive not in serialized_public
        assert sensitive not in serialized_audit
    assert_one_agent_audit(agent_sink)


def test_unknown_citation_and_conflicting_metadata_are_rejected() -> None:
    unknown = ScriptedModel(
        [
            ModelFinalAnswer(
                answer="No",
                answer_basis="knowledge",
                evidence_call_ids=("missing_call",),
                citation_ids=("invented",),
            )
        ]
    )
    orchestrator, _, audit, _ = build(unknown)
    result = execute(orchestrator)
    assert isinstance(result, PublicChatFailure)
    assert result.safe_error_code is AgentErrorCode.INVALID_MODEL_RESPONSE
    assert_one_agent_audit(audit)

    conflict = ScriptedModel(
        [
            call("one", "search_hr_knowledge", {"query": "first"}),
            call("two", "search_hr_knowledge", {"query": "second"}),
        ]
    )
    orchestrator, _, audit, _ = build(conflict)
    result = execute(orchestrator)
    assert isinstance(result, PublicChatFailure)
    assert audit.events[0].internal_reason == "tool_call_not_allowed"


def test_tool_audit_unavailable_terminates_agent() -> None:
    tool_sink = RecordingToolAuditSink(fails=True)
    model = ScriptedModel(
        [
            call("one", "get_my_employee_profile", {}),
            ModelFinalAnswer(
                answer="must not run",
                answer_basis="general",
                evidence_call_ids=(),
                citation_ids=(),
            ),
        ]
    )
    orchestrator, _, agent_sink, _ = build(model, tool_sink=tool_sink)
    result = execute(orchestrator)
    assert isinstance(result, PublicChatFailure)
    assert result.safe_error_code is AgentErrorCode.AUDIT_UNAVAILABLE
    assert len(model.requests) == 1
    assert len(tool_sink.attempts) == 1
    assert_one_agent_audit(agent_sink)


def test_agent_audit_failure_withholds_success() -> None:
    sink = RecordingAgentAuditSink(fails=True)
    orchestrator, _, _, _ = build(
        ScriptedModel(
            [
                ModelFinalAnswer(
                    answer="secret successful answer",
                    answer_basis="general",
                    evidence_call_ids=(),
                    citation_ids=(),
                )
            ]
        ),
        agent_sink=sink,
    )
    result = execute(orchestrator)
    assert isinstance(result, PublicChatFailure)
    assert result.safe_error_code is AgentErrorCode.AUDIT_UNAVAILABLE
    assert "secret successful answer" not in repr(result.model_dump())
    assert len(sink.attempts) == 1
    assert sink.events == []


def test_orchestrator_constructor_and_missing_schema_fail_closed() -> None:
    model = ScriptedModel(
        [
            ModelFinalAnswer(
                answer="Done", answer_basis="general", evidence_call_ids=(), citation_ids=()
            )
        ]
    )
    orchestrator, _, agent_sink, _ = build(model)
    other_registry = CapabilityRegistry((HR_CORE_MANIFEST,))
    with pytest.raises(ValueError):
        AgentOrchestrator(
            other_registry,
            orchestrator.tool_gateway,
            model,
            agent_sink,
        )
    with pytest.raises(TypeError):
        AgentOrchestrator(
            orchestrator.registry,
            orchestrator.tool_gateway,
            object(),  # type: ignore[arg-type]
            agent_sink,
        )
    with pytest.raises(TypeError):
        AgentOrchestrator(
            orchestrator.registry,
            orchestrator.tool_gateway,
            model,
            object(),  # type: ignore[arg-type]
        )
    with pytest.raises(KeyError):
        orchestrator.tool_gateway.public_input_schema("not_installed")


def test_authorized_but_uninstalled_tools_are_absent_from_catalog() -> None:
    model = ScriptedModel(
        [
            ModelFinalAnswer(
                answer="Done", answer_basis="general", evidence_call_ids=(), citation_ids=()
            )
        ]
    )
    orchestrator, _, _, _ = build(model)
    rich_permissions = (
        "hr.profile.read_self",
        "hr.knowledge.read",
        "leave.balance.read_self",
        "leave.request.read_self",
    )
    execute(orchestrator, ctx=context(permissions=rich_permissions))
    names = {tool.tool_name for tool in model.requests[0].tools}
    assert names == set()


@pytest.mark.parametrize(
    "final_answer",
    [
        ModelFinalAnswer(
            answer="Unsupported",
            answer_basis="general",
            evidence_call_ids=("call_1",),
            citation_ids=(),
        ),
        ModelFinalAnswer(
            answer="Unsupported",
            answer_basis="general",
            evidence_call_ids=(),
            citation_ids=("cite_1",),
        ),
    ],
)
def test_general_answer_rejects_declared_evidence_or_citations(
    final_answer: ModelFinalAnswer,
) -> None:
    orchestrator, tool_sink, agent_sink, _ = build(ScriptedModel([final_answer]))
    result = execute(orchestrator)
    assert isinstance(result, PublicChatFailure)
    assert result.safe_error_code is AgentErrorCode.INVALID_MODEL_RESPONSE
    assert tool_sink.attempts == []
    assert_one_agent_audit(agent_sink)


def test_constructed_model_response_cannot_bypass_grounding_collection_validation() -> None:
    malformed = ModelFinalAnswer.model_construct(
        response_type="final_answer",
        answer="Malformed",
        answer_basis="not_a_basis",
        evidence_call_ids=("same", "same"),
        citation_ids=(),
    )
    orchestrator, tool_sink, audit, _ = build(ScriptedModel([malformed]))
    result = execute(orchestrator)
    assert isinstance(result, PublicChatFailure)
    assert result.safe_error_code is AgentErrorCode.INVALID_MODEL_RESPONSE
    assert tool_sink.attempts == []
    assert_one_agent_audit(audit)


def test_general_answer_cannot_ignore_a_successful_tool_call() -> None:
    model = ScriptedModel(
        [
            call("profile_1", "get_my_employee_profile", {}),
            ModelFinalAnswer(
                answer="Ignored it",
                answer_basis="general",
                evidence_call_ids=(),
                citation_ids=(),
            ),
        ]
    )
    orchestrator, tool_sink, agent_sink, _ = build(model)
    result = execute(orchestrator)
    assert isinstance(result, PublicChatFailure)
    assert len(tool_sink.events) == 1
    assert_one_agent_audit(agent_sink)


def test_failed_and_unknown_calls_cannot_be_erp_evidence() -> None:
    model = ScriptedModel(
        [
            call("failed_1", "unknown_tool", {}),
            ModelFinalAnswer(
                answer="Invented live data",
                answer_basis="erp_data",
                evidence_call_ids=("failed_1",),
                citation_ids=(),
            ),
        ]
    )
    orchestrator, tool_sink, agent_sink, _ = build(model)
    result = execute(orchestrator)
    assert isinstance(result, PublicChatFailure)
    assert len(tool_sink.events) == 0
    assert_one_agent_audit(agent_sink)


def test_citation_must_come_from_selected_knowledge_call() -> None:
    model = ScriptedModel(
        [
            call("knowledge_1", "search_hr_knowledge", {"query": "first"}),
            call("knowledge_2", "search_hr_knowledge", {"query": "third"}),
            ModelFinalAnswer(
                answer="Wrong citation binding",
                answer_basis="knowledge",
                evidence_call_ids=("knowledge_1",),
                citation_ids=("cite_4",),
            ),
        ]
    )
    orchestrator, _, agent_sink, _ = build(model)
    result = execute(orchestrator)
    assert isinstance(result, PublicChatFailure)
    assert_one_agent_audit(agent_sink)


def test_valid_mixed_grounding_requires_both_source_types() -> None:
    model = ScriptedModel(
        [
            call("profile_1", "get_my_employee_profile", {}),
            call("knowledge_1", "search_hr_knowledge", {"query": "first"}),
            ModelFinalAnswer(
                answer="Combined answer",
                answer_basis="mixed",
                evidence_call_ids=("profile_1", "knowledge_1"),
                citation_ids=("cite_1",),
            ),
        ]
    )
    orchestrator, _, agent_sink, _ = build(model)
    result = execute(orchestrator)
    assert isinstance(result, PublicChatFailure)
    assert "profile_1" not in repr(agent_sink.events[0].model_dump())


@pytest.mark.parametrize(
    ("basis", "evidence", "citations"),
    [
        ("mixed", ("profile_1",), ("cite_1",)),
        ("mixed", ("knowledge_1",), ("cite_1",)),
        ("knowledge", ("profile_1",), ("cite_1",)),
        ("erp_data", ("knowledge_1",), ()),
    ],
)
def test_basis_rejects_wrong_source_composition(
    basis: str, evidence: tuple[str, ...], citations: tuple[str, ...]
) -> None:
    model = ScriptedModel(
        [
            call("profile_1", "get_my_employee_profile", {}),
            call("knowledge_1", "search_hr_knowledge", {"query": "first"}),
            ModelFinalAnswer(
                answer="Wrong basis",
                answer_basis=basis,
                evidence_call_ids=evidence,
                citation_ids=citations,
            ),
        ]
    )
    orchestrator, _, agent_sink, _ = build(model)
    result = execute(orchestrator)
    assert isinstance(result, PublicChatFailure)
    assert_one_agent_audit(agent_sink)


def test_user_and_answer_character_budgets_apply_before_unsafe_output() -> None:
    boundary = "x" * 8_000
    model = ScriptedModel(
        [
            ModelFinalAnswer(
                answer=boundary,
                answer_basis="general",
                evidence_call_ids=(),
                citation_ids=(),
            )
        ]
    )
    orchestrator, _, audit, _ = build(model)
    result = asyncio.run(
        orchestrator.execute(
            context(),
            PublicChatRequest(message=boundary),
            AgentRoutingPolicy(mode=AgentRouteMode.GENERAL_ONLY),
        )
    )
    assert isinstance(result, PublicChatSuccess)
    assert_one_agent_audit(audit)

    overflow_request = PublicChatRequest.model_construct(
        message="x" * 8_001, stream=False, preferred_response_language=None
    )
    model = ScriptedModel([])
    orchestrator, tool_sink, audit, _ = build(model)
    result = asyncio.run(
        orchestrator.execute(
            context(),
            overflow_request,
            AgentRoutingPolicy(mode=AgentRouteMode.GENERAL_ONLY),
        )
    )
    assert isinstance(result, PublicChatFailure)
    assert result.safe_error_code is AgentErrorCode.AGENT_LIMIT_REACHED
    assert model.requests == []
    assert tool_sink.attempts == []
    assert_one_agent_audit(audit)

    overflow_answer = ModelFinalAnswer.model_construct(
        response_type="final_answer",
        answer="x" * 8_001,
        answer_basis=AnswerBasis.GENERAL,
        evidence_call_ids=(),
        citation_ids=(),
    )
    orchestrator, _, audit, _ = build(ScriptedModel([overflow_answer]))
    result = execute(orchestrator)
    assert isinstance(result, PublicChatFailure)
    assert result.safe_error_code is AgentErrorCode.AGENT_LIMIT_REACHED
    assert_one_agent_audit(audit)


def canonical_argument_size(arguments: dict[str, object]) -> int:
    return len(
        json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    )


def test_argument_byte_boundary_and_overflow_precede_gateway() -> None:
    arguments = {"value": "é"}
    exact_size = canonical_argument_size(arguments)
    responses = [
        call("boundary", "get_my_employee_profile", arguments),
        ModelFinalAnswer(
            answer="Unavailable",
            answer_basis="general",
            evidence_call_ids=(),
            citation_ids=(),
        ),
    ]
    orchestrator, tool_sink, audit, _ = build(
        ScriptedModel(responses),
        limits=AgentLimits(maximum_tool_argument_bytes=exact_size),
    )
    assert isinstance(execute(orchestrator), PublicChatFailure)
    assert len(tool_sink.attempts) == 1
    assert_one_agent_audit(audit)

    model = ScriptedModel([call("overflow", "get_my_employee_profile", arguments)])
    orchestrator, tool_sink, audit, _ = build(
        model,
        limits=AgentLimits(maximum_tool_argument_bytes=exact_size - 1),
    )
    result = execute(orchestrator)
    assert isinstance(result, PublicChatFailure)
    assert result.safe_error_code is AgentErrorCode.AGENT_LIMIT_REACHED
    assert tool_sink.attempts == []
    assert_one_agent_audit(audit)


@pytest.mark.parametrize(
    ("arguments", "limits"),
    [
        ({"a": {"b": {"c": 1}}}, AgentLimits(maximum_argument_depth=3)),
        ({"a": [True, None, 1]}, AgentLimits(maximum_argument_nodes=4)),
    ],
)
def test_argument_depth_and_node_overflow_precede_gateway(
    arguments: dict[str, object], limits: AgentLimits
) -> None:
    orchestrator, tool_sink, audit, _ = build(
        ScriptedModel([call("limited", "get_my_employee_profile", arguments)]), limits=limits
    )
    result = execute(orchestrator)
    assert isinstance(result, PublicChatFailure)
    assert result.safe_error_code is AgentErrorCode.AGENT_LIMIT_REACHED
    assert tool_sink.attempts == []
    assert_one_agent_audit(audit)


def test_catalog_serialized_size_overflow_precedes_model_and_gateway() -> None:
    model = ScriptedModel([])
    orchestrator, tool_sink, audit, _ = build(
        model, limits=AgentLimits(maximum_tool_catalog_bytes=1)
    )
    result = execute(orchestrator)
    assert isinstance(result, PublicChatFailure)
    assert result.safe_error_code is AgentErrorCode.AGENT_CATALOG_LIMIT
    assert model.requests == []
    assert tool_sink.attempts == []
    assert_one_agent_audit(audit)


def test_conflicting_citation_metadata_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = ScriptedModel(
        [
            call("knowledge", "search_hr_knowledge", {"query": "first"}),
            ModelFinalAnswer(
                answer="unused",
                answer_basis="knowledge",
                evidence_call_ids=("knowledge",),
                citation_ids=("cite_1",),
            ),
        ]
    )
    orchestrator, _, audit, _ = build(model)
    monkeypatch.setattr(AgentOrchestrator, "_observe_citations", lambda *args: None)
    result = execute(orchestrator)
    assert isinstance(result, PublicChatFailure)
    assert audit.events[0].internal_reason == "citation_metadata_conflict"


def test_citation_conflict_and_grounding_branches_are_fail_closed() -> None:
    excerpt = KnowledgeExcerpt(
        citation_id="cite_1",
        title="Policy",
        section="Leave",
        language="en",
        source_type=KnowledgeSourceType.CUSTOMER_POLICY,
        document_version="1.0.0",
        content="Synthetic text.",
    )
    result = PublicToolSuccess(
        tool_name="search_hr_knowledge",
        version="1.0.0",
        result=SearchHrKnowledgeOutput(excerpts=(excerpt,)),
    )
    observed = {
        "cite_1": PublicCitation(
            citation_id="cite_1",
            title="Different",
            section="Leave",
            language="en",
            source_type=KnowledgeSourceType.CUSTOMER_POLICY,
            document_version="1.0.0",
        )
    }
    assert AgentOrchestrator._observe_citations(result, observed) is None

    knowledge = _SuccessfulEvidenceCall("k", "search_hr_knowledge", "1.0.0", True, ("cite_1",))
    erp = _SuccessfulEvidenceCall("e", "get_my_employee_profile", "1.0.0", False, ())
    citations = {"cite_1": observed["cite_1"]}
    cases = (
        (AnswerBasis.KNOWLEDGE, ("k",), (), {"k": knowledge}),
        (AnswerBasis.ERP_DATA, ("e",), ("cite_1",), {"e": erp}),
        (AnswerBasis.MIXED, ("k", "e"), ("cite_1",), {"k": knowledge, "e": erp}),
        (AnswerBasis.KNOWLEDGE, ("k",), ("other",), {"k": knowledge}),
    )
    for basis, evidence, selected_citations, calls in cases:
        answer = ModelFinalAnswer(
            answer="Synthetic",
            answer_basis=basis,
            evidence_call_ids=evidence,
            citation_ids=selected_citations,
        )
        assert AgentOrchestrator._validate_grounding(answer, calls, citations) is None


def test_exact_route_grounding_requires_the_one_successful_call_and_source_basis() -> None:
    erp = _SuccessfulEvidenceCall("erp", "get_my_employee_profile", "1.0.0", False, ())
    knowledge = _SuccessfulEvidenceCall(
        "knowledge", "search_hr_knowledge", "1.0.0", True, ("cite_1",)
    )
    valid_erp = ModelFinalAnswer(
        answer="Synthetic",
        answer_basis=AnswerBasis.ERP_DATA,
        evidence_call_ids=("erp",),
        citation_ids=(),
    )
    assert AgentOrchestrator._matches_exact_route_grounding(valid_erp, {"erp": erp})
    assert not AgentOrchestrator._matches_exact_route_grounding(valid_erp, {})
    assert not AgentOrchestrator._matches_exact_route_grounding(
        valid_erp.model_copy(update={"evidence_call_ids": ()}), {"erp": erp}
    )
    assert not AgentOrchestrator._matches_exact_route_grounding(
        valid_erp.model_copy(update={"answer_basis": AnswerBasis.GENERAL}), {"erp": erp}
    )
    valid_knowledge = ModelFinalAnswer(
        answer="Synthetic",
        answer_basis=AnswerBasis.KNOWLEDGE,
        evidence_call_ids=("knowledge",),
        citation_ids=("cite_1",),
    )
    assert AgentOrchestrator._matches_exact_route_grounding(
        valid_knowledge, {"knowledge": knowledge}
    )
