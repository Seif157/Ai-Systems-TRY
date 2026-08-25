import json
import math
from types import MappingProxyType

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from erp_ai.knowledge import KnowledgeSourceType
from erp_ai.orchestration import (
    AgentErrorCode,
    AgentLimits,
    ModelFinalAnswer,
    ModelToolCall,
    ModelToolDefinition,
    ModelToolInteraction,
    ModelTurnRequest,
    PublicChatFailure,
    PublicChatSuccess,
    PublicCitation,
    ToolResultMessage,
)
from erp_ai.orchestration.models import _validate_safe_numbers
from erp_ai.tools import PublicToolFailure, PublicToolSuccess, ToolErrorCode


def citation(citation_id: str = "cite_1") -> PublicCitation:
    return PublicCitation(
        citation_id=citation_id,
        title="Policy",
        section="Leave",
        language="en",
        source_type=KnowledgeSourceType.CUSTOMER_POLICY,
        document_version="1.0.0",
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
    with pytest.raises((ValidationError, ValueError)):
        success.answer = "changed"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        PublicChatSuccess(
            answer="Answer", response_language="en", citations=(citation(), citation())
        )


@pytest.mark.parametrize("version", ("1", "1.0", "01.0.0", "1.0.0-alpha", "1.0.0+build", " 1.0.0 "))
def test_public_citation_rejects_noncanonical_document_versions(version: str) -> None:
    with pytest.raises(ValidationError):
        PublicCitation(
            citation_id="cite_1",
            title="Policy",
            section="Leave",
            language="en",
            source_type=KnowledgeSourceType.CUSTOMER_POLICY,
            document_version=version,
        )


def test_public_citation_preserves_exact_document_version() -> None:
    assert citation().document_version == "1.0.0"
    assert citation().model_copy(update={"document_version": "12.34.567"}).document_version == (
        "12.34.567"
    )


def test_model_tool_arguments_and_schema_are_recursively_immutable_json() -> None:
    call = ModelToolCall.from_arguments(
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
    with pytest.raises((ValidationError, ValueError)):
        ModelToolCall.from_arguments(
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
            document_version="1.0.0",
        )


def failure_result(tool_name: str = "get_profile") -> PublicToolFailure:
    return PublicToolFailure(
        tool_name=tool_name,
        version="1.0.0",
        safe_error_code=ToolErrorCode.TOOL_UNAVAILABLE,
        safe_message="Unavailable.",
    )


def interaction(call_id: str = "call_1", tool_name: str = "get_profile") -> ModelToolInteraction:
    assistant_call = ModelToolCall.from_arguments(
        call_id=call_id,
        tool_name=tool_name,
        version="1.0.0",
        arguments={"language": "العربية", "query": "English"},
    )
    return ModelToolInteraction(
        assistant_call=assistant_call,
        tool_result=ToolResultMessage(
            call_id=call_id,
            tool_name=tool_name,
            result=failure_result(tool_name),
        ),
    )


def turn(*interactions: ModelToolInteraction) -> ModelTurnRequest:
    return ModelTurnRequest(
        policy_instructions=("policy",),
        user_message="synthetic",
        response_language="en",
        tools=(),
        interactions=interactions,
        turn_number=2,
    )


def test_exact_argument_json_is_preserved_without_normalization() -> None:
    raw = '{ "z" : "العربية", "a": ["English", 1] }'
    call = ModelToolCall.from_arguments_json(
        call_id="call_1", tool_name="get_profile", version="1.0.0", arguments_json=raw
    )
    assert call.arguments_json == raw
    assert call.arguments["z"] == "العربية"
    assert call.arguments["a"] == ("English", 1)
    assert raw not in repr(call)


def test_nested_typed_equivalence_and_unicode_escape_preserve_raw_json() -> None:
    raw = (
        '{ "nested" : [{"truth":true,"falsehood":false,"integer":1,'
        '"float":1.0,"negative_zero":-0.0,"text":"\\u0627"}] }'
    )
    call = ModelToolCall.from_arguments_json(
        call_id="call_1", tool_name="get_profile", version="1.0.0", arguments_json=raw
    )
    nested = call.arguments["nested"][0]  # type: ignore[index]
    assert nested["truth"] is True  # type: ignore[index]
    assert nested["falsehood"] is False  # type: ignore[index]
    assert type(nested["integer"]) is int  # type: ignore[index]
    assert type(nested["float"]) is float  # type: ignore[index]
    assert math.copysign(1.0, nested["negative_zero"]) == -1.0  # type: ignore[index,arg-type]
    assert nested["text"] == "\N{ARABIC LETTER ALEF}"  # type: ignore[index]
    assert call.arguments_json == raw


def test_fake_provider_constructor_is_deterministic_compact_sorted_utf8() -> None:
    call = ModelToolCall.from_arguments(
        call_id="call_1",
        tool_name="get_profile",
        version="1.0.0",
        arguments={"z": "العربية", "a": [1, "English"]},
    )
    assert call.arguments_json == '{"a":[1,"English"],"z":"العربية"}'
    assert call.arguments_json.encode("utf-8") == json.dumps(
        {"a": [1, "English"], "z": "العربية"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


@pytest.mark.parametrize(
    "raw",
    (
        '{"outer":{"same":1,"same":2}}',
        '{"same":1,"same":2}',
        "[]",
        "null",
        '{"unsafe":NaN}',
        '{"unsafe":9007199254740992}',
        "not-json",
        "{" + '"x":' * 11 + "0" + "}" * 11,
        '{"oversized":"' + "x" * 16_384 + '"}',
    ),
)
def test_raw_argument_json_rejects_ambiguous_or_unsafe_values(raw: str) -> None:
    with pytest.raises((ValidationError, ValueError)):
        ModelToolCall.from_arguments_json(
            call_id="call_1", tool_name="get_profile", version="1.0.0", arguments_json=raw
        )


def test_raw_and_parsed_arguments_cannot_diverge() -> None:
    with pytest.raises(ValidationError):
        ModelToolCall(
            call_id="call_1",
            tool_name="get_profile",
            version="1.0.0",
            arguments_json='{"value":1}',
            arguments={"value": 2},
        )
    with pytest.raises(ValidationError):
        ModelToolCall(
            call_id="call_1",
            tool_name="get_profile",
            version="1.0.0",
            arguments_json='{"value":1}',
            arguments={"value": True},
        )
    for raw, parsed in (
        ('{"nested":{"value":true}}', {"nested": {"value": 1}}),
        ('{"nested":{"value":false}}', {"nested": {"value": 0}}),
        ('{"nested":[{"value":1}]}', {"nested": [{"value": 1.0}]}),
        ('{"nested":{"value":-0.0}}', {"nested": {"value": 0.0}}),
    ):
        with pytest.raises(ValidationError):
            ModelToolCall(
                call_id="call_1",
                tool_name="get_profile",
                version="1.0.0",
                arguments_json=raw,
                arguments=parsed,
            )


def test_numeric_and_structural_argument_limits_are_fully_enforced() -> None:
    valid = ModelToolCall.from_arguments_json(
        call_id="call_1",
        tool_name="get_profile",
        version="1.0.0",
        arguments_json='{"finite":1.5}',
    )
    assert valid.arguments["finite"] == 1.5
    with pytest.raises(ValueError):
        ModelToolCall.from_arguments_json(
            call_id="call_1",
            tool_name="get_profile",
            version="1.0.0",
            arguments_json='{"overflow":1e400}',
        )
    nested: object = 0
    for _ in range(10):
        nested = {"child": nested}
    with pytest.raises(ValueError):
        ModelToolCall.from_arguments_json(
            call_id="call_1",
            tool_name="get_profile",
            version="1.0.0",
            arguments_json=json.dumps(nested),
        )
    with pytest.raises(ValueError):
        ModelToolCall.from_arguments_json(
            call_id="call_1",
            tool_name="get_profile",
            version="1.0.0",
            arguments_json=json.dumps({"items": list(range(512))}),
        )
    with pytest.raises(ValueError):
        _validate_safe_numbers(object())
    recursion_bomb = '{"nested":' + "[" * 2_000 + "0" + "]" * 2_000 + "}"
    with pytest.raises(ValueError):
        ModelToolCall.from_arguments_json(
            call_id="call_1",
            tool_name="get_profile",
            version="1.0.0",
            arguments_json=recursion_bomb,
        )


@pytest.mark.parametrize("constant", ("NaN", "Infinity", "-Infinity"))
def test_nonstandard_json_number_constants_are_rejected(constant: str) -> None:
    with pytest.raises(ValueError):
        ModelToolCall.from_arguments_json(
            call_id="call_1",
            tool_name="get_profile",
            version="1.0.0",
            arguments_json=f'{{"nested":{{"value":{constant}}}}}',
        )


def test_sensitive_validation_errors_hide_inputs() -> None:
    sensitive = "private-query-and-record-selector"
    with pytest.raises(ValidationError) as captured:
        ModelToolCall(
            call_id="private-call-id",
            tool_name="get_profile",
            version="1.0.0",
            arguments_json=f'{{"query":"{sensitive}"',
            arguments={"query": sensitive},
        )
    rendered = str(captured.value)
    assert sensitive not in rendered
    assert "private-call-id" not in rendered
    call = ModelToolCall.from_arguments(
        call_id="call_1", tool_name="get_profile", version="1.0.0", arguments={}
    )
    with pytest.raises(ValidationError) as interaction_error:
        ModelToolInteraction.model_validate(
            {
                "assistant_call": call,
                "tool_result": {
                    "call_id": "call_1",
                    "tool_name": "get_profile",
                    "result": {"private_payload": sensitive},
                },
            },
            strict=True,
        )
    assert sensitive not in str(interaction_error.value)


def test_interactions_are_paired_ordered_immutable_and_repr_hidden() -> None:
    first = interaction("call_1")
    second = interaction("call_2")
    request = turn(first, second)
    assert request.interactions == (first, second)
    assert "العربية" not in repr(request)
    with pytest.raises(ValidationError):
        request.interactions = ()  # type: ignore[misc]
    with pytest.raises(ValidationError):
        turn(first, first)


@pytest.mark.parametrize(
    ("result_call_id", "result_tool", "public_tool", "public_version"),
    (
        ("other", "get_profile", "get_profile", "1.0.0"),
        ("call_1", "other_tool", "other_tool", "1.0.0"),
        ("call_1", "get_profile", "other_tool", "1.0.0"),
        ("call_1", "get_profile", "get_profile", "2.0.0"),
    ),
)
def test_interaction_rejects_mismatched_call_result_pairing(
    result_call_id: str, result_tool: str, public_tool: str, public_version: str
) -> None:
    call = ModelToolCall.from_arguments(
        call_id="call_1", tool_name="get_profile", version="1.0.0", arguments={}
    )
    result = failure_result(public_tool).model_copy(update={"version": public_version})
    with pytest.raises(ValidationError):
        ModelToolInteraction(
            assistant_call=call,
            tool_result=ToolResultMessage(
                call_id=result_call_id, tool_name=result_tool, result=result
            ),
        )


def test_constructed_invalid_interaction_is_defensively_revalidated() -> None:
    valid = interaction()
    invalid_call = ModelToolCall.model_construct(
        response_type="tool_call",
        call_id="call_1",
        tool_name="get_profile",
        version="1.0.0",
        arguments_json='{"value":1,"value":2}',
        arguments=MappingProxyType({"value": 2}),
    )
    constructed = ModelToolInteraction.model_construct(
        assistant_call=invalid_call, tool_result=valid.tool_result
    )
    with pytest.raises(ValidationError):
        turn(constructed)


def test_constructed_raw_parsed_divergence_and_invalid_result_type_are_rejected() -> None:
    valid = interaction()
    divergent_call = ModelToolCall.model_construct(
        response_type="tool_call",
        call_id="call_1",
        tool_name="get_profile",
        version="1.0.0",
        arguments_json='{"value":1}',
        arguments=MappingProxyType({"value": 2}),
    )
    with pytest.raises(ValidationError):
        ModelToolInteraction(assistant_call=divergent_call, tool_result=valid.tool_result)
    invalid_message = ToolResultMessage.model_construct(
        call_id="call_1",
        tool_name="get_profile",
        result=PublicChatFailure(
            safe_error_code=AgentErrorCode.AGENT_UNAVAILABLE,
            safe_message="Unavailable.",
        ),
        content_trust="untrusted_tool_result",
    )
    with pytest.raises(ValidationError):
        ModelToolInteraction(assistant_call=valid.assistant_call, tool_result=invalid_message)


class SyntheticSafeResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    value: str


def test_interaction_supports_success_results() -> None:
    call = ModelToolCall.from_arguments(
        call_id="call_1", tool_name="get_profile", version="1.0.0", arguments={}
    )
    result = PublicToolSuccess(
        tool_name="get_profile",
        version="1.0.0",
        result=SyntheticSafeResult(value="synthetic"),
    )
    paired = ModelToolInteraction(
        assistant_call=call,
        tool_result=ToolResultMessage(call_id="call_1", tool_name="get_profile", result=result),
    )
    assert paired.tool_result.result is result
