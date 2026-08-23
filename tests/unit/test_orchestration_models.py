from types import MappingProxyType

import pytest
from pydantic import ValidationError

from erp_ai.knowledge import KnowledgeSourceType
from erp_ai.orchestration import (
    AgentErrorCode,
    AgentLimits,
    ModelFinalAnswer,
    ModelToolCall,
    ModelToolDefinition,
    PublicChatFailure,
    PublicChatSuccess,
    PublicCitation,
)


def citation(citation_id: str = "cite_1") -> PublicCitation:
    return PublicCitation(
        citation_id=citation_id,
        title="Policy",
        section="Leave",
        language="en",
        source_type=KnowledgeSourceType.CUSTOMER_POLICY,
        document_version=1,
    )


def test_public_models_are_strict_frozen_and_allowlisted() -> None:
    success = PublicChatSuccess(answer="Answer", response_language="en", citations=(citation(),))
    PublicChatFailure(
        safe_error_code=AgentErrorCode.AGENT_UNAVAILABLE,
        safe_message="Unavailable.",
    )
    assert set(PublicChatSuccess.model_fields) == {"answer", "response_language", "citations"}
    assert set(PublicChatFailure.model_fields) == {"safe_error_code", "safe_message"}
    assert set(PublicCitation.model_fields) == {
        "citation_id",
        "title",
        "section",
        "language",
        "source_type",
        "document_version",
    }
    with pytest.raises(ValidationError):
        success.answer = "changed"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        PublicChatSuccess(
            answer="Answer", response_language="en", citations=(citation(), citation())
        )


def test_model_tool_arguments_and_schema_are_recursively_immutable_json() -> None:
    call = ModelToolCall(
        call_id=" call_1 ",
        tool_name="get_profile",
        version="1.0.0",
        arguments={"nested": {"values": [1, True, None]}},
    )
    definition = ModelToolDefinition(
        tool_name="get_profile",
        version="1.0.0",
        input_schema={"type": "object", "required": ["detail"]},
    )
    assert call.call_id == "call_1"
    assert isinstance(call.arguments, MappingProxyType)
    assert isinstance(call.arguments["nested"], MappingProxyType)
    assert isinstance(definition.input_schema, MappingProxyType)
    assert call.model_dump(mode="json")["arguments"] == {"nested": {"values": [1, True, None]}}
    assert definition.model_dump(mode="json")["input_schema"] == {
        "type": "object",
        "required": ["detail"],
    }
    with pytest.raises(ValidationError):
        ModelToolCall(
            call_id="call",
            tool_name="get_profile",
            version="1.0.0",
            arguments={"bad": object()},
        )


def test_answers_limits_and_unknown_fields_are_validated() -> None:
    with pytest.raises(ValidationError):
        ModelFinalAnswer(
            answer="",
            answer_basis="general",
            evidence_call_ids=(),
            citation_ids=(),
        )
    with pytest.raises(ValidationError):
        PublicChatFailure.model_validate(
            {"safe_error_code": "AGENT_UNAVAILABLE", "safe_message": "", "extra": True}
        )
    with pytest.raises(ValidationError):
        AgentLimits(maximum_model_turns=0)
    for invalid_basis in ("unsupported", 1):
        with pytest.raises(ValidationError):
            ModelFinalAnswer(
                answer="Answer",
                answer_basis=invalid_basis,  # type: ignore[arg-type]
                evidence_call_ids=(),
                citation_ids=(),
            )
    with pytest.raises(ValidationError):
        ModelFinalAnswer(
            answer="Answer",
            answer_basis="general",
            evidence_call_ids=("same", "same"),
            citation_ids=(),
        )
    with pytest.raises(ValidationError):
        ModelFinalAnswer(
            answer="Answer",
            answer_basis="knowledge",
            evidence_call_ids=tuple(f"call_{index}" for index in range(5)),
            citation_ids=(),
        )
    with pytest.raises(ValidationError):
        ModelFinalAnswer(
            answer="Answer",
            answer_basis="knowledge",
            evidence_call_ids=("call_1",),
            citation_ids=tuple(f"cite_{index}" for index in range(21)),
        )
    with pytest.raises(ValidationError):
        PublicCitation(
            citation_id=" ",
            title="Policy",
            section="Leave",
            language="en",
            source_type=KnowledgeSourceType.CUSTOMER_POLICY,
            document_version=1,
        )
