import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from erp_ai.api import PublicChatRequest
from erp_ai.capabilities import (
    CapabilityManifest,
    CapabilityRegistry,
    DataClassification,
    ToolDescriptor,
)
from erp_ai.context import TrustedRequestContext
from erp_ai.orchestration import (
    AgentAuditEvent,
    AgentErrorCode,
    AgentOrchestrator,
    AnswerBasis,
    ModelFinalAnswer,
    ModelTurnRequest,
    PublicChatFailure,
    PublicChatSuccess,
)
from erp_ai.tools import ReadToolGateway, ToolAuditEvent


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class EmptyOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class SyntheticHandler:
    version = "1.0.0"
    input_model = EmptyInput
    output_model = EmptyOutput

    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name

    async def execute(self, context: TrustedRequestContext, arguments: BaseModel) -> object:
        return EmptyOutput()


class FinalModel:
    def __init__(self) -> None:
        self.requests: list[ModelTurnRequest] = []

    async def complete_turn(self, request: ModelTurnRequest) -> ModelFinalAnswer:
        self.requests.append(request)
        return ModelFinalAnswer(
            answer="Done",
            answer_basis=AnswerBasis.GENERAL,
            evidence_call_ids=(),
            citation_ids=(),
        )


class ToolSink:
    def __init__(self) -> None:
        self.events: list[ToolAuditEvent] = []

    async def record(self, event: ToolAuditEvent) -> None:
        self.events.append(event)


class AgentSink:
    def __init__(self) -> None:
        self.events: list[AgentAuditEvent] = []

    async def record(self, event: AgentAuditEvent) -> None:
        self.events.append(event)


def context() -> TrustedRequestContext:
    return TrustedRequestContext(
        context_version=1,
        request_id="catalog_request",
        customer_environment_id="customer_a",
        user_id="user_a",
        employee_id=None,
        roles=("user",),
        permission_codes=(),
        legal_entity_ids=("entity_1",),
        enabled_modules=("hr_core",),
        locale="en",
        timezone="Africa/Cairo",
        purpose="employee_self_service",
        issued_at=datetime(2026, 8, 23, tzinfo=ZoneInfo("Africa/Cairo")),
        authorization_snapshot_id="snapshot_a",
    )


def build(tool_count: int) -> tuple[AgentOrchestrator, FinalModel, ToolSink, AgentSink]:
    descriptors = tuple(
        ToolDescriptor(
            tool_name=f"read_item_{index:02d}",
            version="1.0.0",
            operation="read",
            required_permissions_all=(),
            required_roles_any=(),
            allowed_purposes=("employee_self_service",),
            data_classification=DataClassification.INTERNAL,
            audit_action=f"catalog.item_{index:02d}.read",
        )
        for index in range(tool_count)
    )
    registry = CapabilityRegistry(
        (
            CapabilityManifest(
                capability_code="synthetic_catalog",
                version="1.0.0",
                required_modules=("hr_core",),
                tools=descriptors,
            ),
        )
    )
    tool_sink = ToolSink()
    gateway = ReadToolGateway(
        registry,
        tuple(SyntheticHandler(descriptor.tool_name) for descriptor in descriptors),
        tool_sink,
    )
    model = FinalModel()
    agent_sink = AgentSink()
    return AgentOrchestrator(registry, gateway, model, agent_sink), model, tool_sink, agent_sink


def test_exactly_32_tools_are_accepted_in_deterministic_order() -> None:
    orchestrator, model, tool_sink, agent_sink = build(32)
    result = asyncio.run(orchestrator.execute(context(), PublicChatRequest(message="Help")))
    assert isinstance(result, PublicChatSuccess)
    names = tuple(tool.tool_name for tool in model.requests[0].tools)
    assert len(names) == 32
    assert names == tuple(sorted(names))
    assert tool_sink.events == []
    assert len(agent_sink.events) == 1


def test_more_than_32_tools_fail_without_truncation_or_model_invocation() -> None:
    orchestrator, model, tool_sink, agent_sink = build(33)
    result = asyncio.run(orchestrator.execute(context(), PublicChatRequest(message="Help")))
    assert isinstance(result, PublicChatFailure)
    assert result.safe_error_code is AgentErrorCode.AGENT_CATALOG_LIMIT
    assert model.requests == []
    assert tool_sink.events == []
    assert len(agent_sink.events) == 1
