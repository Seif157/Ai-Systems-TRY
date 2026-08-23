import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from erp_ai.capabilities import CapabilityRegistry, DataClassification
from erp_ai.capabilities.hr_knowledge import (
    HR_KNOWLEDGE_MANIFEST,
    SearchHrKnowledgeHandler,
)
from erp_ai.context import TrustedRequestContext
from erp_ai.knowledge import KnowledgeMatch, KnowledgeRetrievalRequest
from erp_ai.tools import (
    PublicToolFailure,
    PublicToolSuccess,
    ReadToolGateway,
    ToolAuditEvent,
    ToolErrorCode,
    ToolInvocation,
)

NOW = datetime(2026, 8, 23, 10, 0, tzinfo=ZoneInfo("Africa/Cairo"))
QUERY = "What is the leave policy?"
TOOL_AUDIT_FIELDS = {
    "request_id",
    "customer_environment_id",
    "user_id",
    "tool_name",
    "tool_version",
    "audit_action",
    "data_classification",
    "outcome",
    "internal_reason",
    "purpose",
}
RETRIEVAL_SENSITIVE_FIELDS = {
    "query",
    "content",
    "title",
    "section",
    "citation_id",
    "document_id",
    "chunk_id",
    "relevance_score",
    "storage_location",
    "storage_path",
    "embedding",
    "embeddings",
    "vector_metadata",
    "employee_id",
    "legal_entity_ids",
    "roles",
    "permission_codes",
    "enabled_modules",
}


class FakeProvider:
    def __init__(self, matches: tuple[KnowledgeMatch, ...]) -> None:
        self.matches = matches
        self.requests: list[KnowledgeRetrievalRequest] = []
        self.raises = False

    async def retrieve(self, request: KnowledgeRetrievalRequest) -> tuple[KnowledgeMatch, ...]:
        self.requests.append(request)
        if self.raises:
            raise RuntimeError("secret backend details")
        return self.matches


class RecordingAuditSink:
    def __init__(self, *, fails: bool = False) -> None:
        self.events: list[ToolAuditEvent] = []
        self.attempted_events: list[ToolAuditEvent] = []
        self.fails = fails

    async def record(self, event: ToolAuditEvent) -> None:
        self.attempted_events.append(event)
        if self.fails:
            raise RuntimeError("private audit backend failure")
        self.events.append(event)


def context(
    *,
    modules: tuple[str, ...] = ("hr_core",),
    permissions: tuple[str, ...] = ("hr.knowledge.read",),
    purpose: str = "employee_self_service",
) -> TrustedRequestContext:
    return TrustedRequestContext(
        context_version=1,
        request_id="correlation_knowledge_1",
        customer_environment_id="customer_a",
        user_id="user_a",
        employee_id="employee_secret_knowledge",
        roles=("knowledge_role_secret",),
        permission_codes=permissions,
        legal_entity_ids=("entity_secret_knowledge",),
        enabled_modules=modules,
        locale="en",
        timezone="Africa/Cairo",
        purpose=purpose,
        issued_at=NOW,
        authorization_snapshot_id="snapshot_a",
    )


def match(**overrides: object) -> KnowledgeMatch:
    values: dict[str, object] = {
        "chunk_id": "private_chunk_1",
        "document_id": "private_document_1",
        "citation_id": "citation_public_1",
        "namespace": "hr",
        "source_type": "customer_policy",
        "customer_environment_id": "customer_a",
        "required_modules_all": ("hr_core",),
        "required_permissions_all": ("hr.knowledge.read",),
        "allowed_purposes": ("employee_self_service",),
        "legal_entity_ids": ("entity_secret_knowledge",),
        "data_classification": "restricted",
        "language": "en",
        "title": "Leave policy",
        "section": "Eligibility",
        "document_version": "3.0.0",
        "effective_from": NOW - timedelta(days=1),
        "effective_to": None,
        "content": "Employees may request approved leave.",
        "relevance_score": 0.95,
    }
    values.update(overrides)
    return KnowledgeMatch.model_validate(values)


def invoke(arguments: dict[str, object] | None = None) -> ToolInvocation:
    return ToolInvocation.model_validate(
        {
            "tool_name": "search_hr_knowledge",
            "version": "1.0.0",
            "arguments": {"query": QUERY} if arguments is None else arguments,
        }
    )


def execute(
    provider: FakeProvider,
    sink: RecordingAuditSink,
    *,
    ctx: TrustedRequestContext | None = None,
    invocation: ToolInvocation | None = None,
) -> PublicToolSuccess | PublicToolFailure:
    gateway = ReadToolGateway(
        CapabilityRegistry((HR_KNOWLEDGE_MANIFEST,)),
        (SearchHrKnowledgeHandler(provider),),
        sink,
    )
    return asyncio.run(gateway.execute(ctx or context(), invocation or invoke()))


def assert_safe_audit_event(event: ToolAuditEvent) -> None:
    payload = event.model_dump()
    assert set(payload) == TOOL_AUDIT_FIELDS
    assert RETRIEVAL_SENSITIVE_FIELDS.isdisjoint(payload)
    serialized = repr(payload)
    for forbidden in (
        QUERY,
        "Employees may request approved leave.",
        "Leave policy",
        "Eligibility",
        "citation_public_1",
        "private_document_1",
        "private_chunk_1",
        "0.95",
        "employee_secret_knowledge",
        "entity_secret_knowledge",
        "knowledge_role_secret",
        "hr.knowledge.read",
        "hr_core",
        "secret backend details",
        "private audit backend failure",
    ):
        assert forbidden not in serialized


def assert_public_result_has_no_audit(result: PublicToolSuccess | PublicToolFailure) -> None:
    payload = result.model_dump()
    assert "audit" not in payload
    assert "audit_event" not in payload
    assert {
        "request_id",
        "customer_environment_id",
        "user_id",
        "audit_action",
        "data_classification",
        "outcome",
        "internal_reason",
        "purpose",
    }.isdisjoint(payload)


def test_complete_context_registry_gateway_provider_audit_flow() -> None:
    provider = FakeProvider((match(),))
    sink = RecordingAuditSink()
    result = execute(provider, sink)
    assert isinstance(result, PublicToolSuccess)
    assert result.result.excerpts[0].citation_id == "citation_public_1"  # type: ignore[attr-defined]
    assert len(provider.requests) == 1
    assert len(sink.attempted_events) == 1
    assert len(sink.events) == 1
    event = sink.events[0]
    assert event.audit_action == "hr.knowledge.search"
    assert event.data_classification is DataClassification.RESTRICTED
    assert_safe_audit_event(event)
    assert_public_result_has_no_audit(result)


def test_empty_provider_results_are_successful() -> None:
    sink = RecordingAuditSink()
    result = execute(FakeProvider(()), sink)
    assert isinstance(result, PublicToolSuccess)
    assert result.result.excerpts == ()  # type: ignore[attr-defined]
    assert len(sink.attempted_events) == 1
    assert len(sink.events) == 1
    assert_safe_audit_event(sink.events[0])
    assert_public_result_has_no_audit(result)


def test_provider_exception_and_invalid_scope_fail_safely_and_audit_once() -> None:
    provider = FakeProvider(())
    provider.raises = True
    sink = RecordingAuditSink()
    result = execute(provider, sink)
    assert isinstance(result, PublicToolFailure)
    assert result.safe_error_code is ToolErrorCode.TOOL_EXECUTION_FAILED
    assert "secret" not in result.safe_message
    assert len(sink.attempted_events) == 1
    assert len(sink.events) == 1
    assert_safe_audit_event(sink.events[0])
    assert sink.events[0].internal_reason == "handler_execution_failed"
    assert_public_result_has_no_audit(result)

    sink = RecordingAuditSink()
    result = execute(FakeProvider((match(namespace="payroll"),)), sink)
    assert isinstance(result, PublicToolFailure)
    assert result.safe_error_code is ToolErrorCode.TOOL_EXECUTION_FAILED
    assert len(sink.attempted_events) == 1
    assert len(sink.events) == 1
    assert_safe_audit_event(sink.events[0])
    assert sink.events[0].internal_reason == "handler_execution_failed"
    assert_public_result_has_no_audit(result)


@pytest.mark.parametrize(
    "ctx",
    [context(modules=()), context(permissions=()), context(purpose="manager_service")],
)
def test_manifest_authorization_denies_before_provider(ctx: TrustedRequestContext) -> None:
    provider = FakeProvider((match(),))
    sink = RecordingAuditSink()
    result = execute(provider, sink, ctx=ctx)
    assert isinstance(result, PublicToolFailure)
    assert result.safe_error_code is ToolErrorCode.TOOL_UNAVAILABLE
    assert provider.requests == []
    assert len(sink.attempted_events) == 1
    assert len(sink.events) == 1
    assert_safe_audit_event(sink.events[0])
    assert sink.events[0].internal_reason == "tool_not_authorized_or_installed"
    assert_public_result_has_no_audit(result)


@pytest.mark.parametrize(
    "field",
    [
        "namespace",
        "customer_environment_id",
        "enabled_modules",
        "permissions",
        "purpose",
        "result_count",
        "read_only_mode",
    ],
)
def test_public_request_cannot_inject_scope_or_server_controls(field: str) -> None:
    provider = FakeProvider((match(),))
    result = execute(
        provider,
        RecordingAuditSink(),
        invocation=invoke({"query": QUERY, field: "forged"}),
    )
    assert isinstance(result, PublicToolFailure)
    assert result.safe_error_code is ToolErrorCode.INVALID_TOOL_ARGUMENTS
    assert provider.requests == []


def test_leave_knowledge_requires_leave_entitlement() -> None:
    provider = FakeProvider((match(required_modules_all=("hr_core", "leave")),))
    denied = execute(provider, RecordingAuditSink())
    assert isinstance(denied, PublicToolFailure)
    allowed = execute(
        provider,
        RecordingAuditSink(),
        ctx=context(modules=("hr_core", "leave")),
    )
    assert isinstance(allowed, PublicToolSuccess)


def test_public_serialization_contains_only_safe_allowlisted_fields() -> None:
    result = execute(FakeProvider((match(),)), RecordingAuditSink())
    assert isinstance(result, PublicToolSuccess)
    excerpt = result.result.excerpts[0].model_dump()  # type: ignore[attr-defined]
    assert set(excerpt) == {
        "citation_id",
        "title",
        "section",
        "language",
        "source_type",
        "document_version",
        "content",
        "content_trust",
    }


def test_audit_failure_withholds_knowledge_results_and_fails_closed() -> None:
    sink = RecordingAuditSink(fails=True)
    result = execute(FakeProvider((match(),)), sink)

    assert isinstance(result, PublicToolFailure)
    assert result.safe_error_code is ToolErrorCode.AUDIT_UNAVAILABLE
    assert len(sink.attempted_events) == 1
    assert sink.events == []
    assert_safe_audit_event(sink.attempted_events[0])
    assert "Employees may request approved leave." not in repr(result.model_dump())
    assert "private audit backend failure" not in result.safe_message
    assert_public_result_has_no_audit(result)
