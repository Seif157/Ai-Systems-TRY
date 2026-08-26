"""Strict immutable public and model-facing orchestration contracts."""

import json
import math
from collections.abc import Mapping
from enum import Enum
from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_serializer,
    field_validator,
    model_validator,
)

from erp_ai.capabilities.models import Code, Version
from erp_ai.context.models import Identifier
from erp_ai.knowledge import KnowledgeSourceType
from erp_ai.knowledge.models import DisplayText, LanguageCode
from erp_ai.tools import PublicToolFailure, PublicToolSuccess
from erp_ai.types import CanonicalSemVer

Answer = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=8_000),
]
CallId = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=128),
]
SafeMessage = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=300)]
MAXIMUM_TOOL_ARGUMENT_BYTES = 16_384
MAXIMUM_ARGUMENT_DEPTH = 10
MAXIMUM_ARGUMENT_NODES = 512
MAXIMUM_SAFE_JSON_INTEGER = 2**53 - 1


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError("value must contain only JSON-compatible data")


def to_mutable_json(value: object) -> object:
    """Project immutable JSON data for serialization without exposing model mutability."""

    if isinstance(value, Mapping):
        return {str(key): to_mutable_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [to_mutable_json(item) for item in value]
    return value


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"unsupported JSON constant: {value}")


def _object_without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object keys are not allowed")
        result[key] = value
    return result


def _json_depth_and_nodes(value: object, depth: int = 1) -> tuple[int, int]:
    if isinstance(value, dict):
        children = tuple(_json_depth_and_nodes(item, depth + 1) for item in value.values())
    elif isinstance(value, list):
        children = tuple(_json_depth_and_nodes(item, depth + 1) for item in value)
    else:
        return depth, 1
    return (
        max((child_depth for child_depth, _ in children), default=depth),
        1 + sum(nodes for _, nodes in children),
    )


def _validate_safe_numbers(value: object) -> None:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return
    if isinstance(value, int):
        if abs(value) > MAXIMUM_SAFE_JSON_INTEGER:
            raise ValueError("JSON integer exceeds the interoperable safe range")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return
    if isinstance(value, dict):
        for item in value.values():
            _validate_safe_numbers(item)
        return
    if isinstance(value, list):
        for item in value:
            _validate_safe_numbers(item)
        return
    raise ValueError("arguments must contain only JSON-compatible values")


def _parse_arguments_json(value: str) -> dict[str, object]:
    if len(value.encode("utf-8")) > MAXIMUM_TOOL_ARGUMENT_BYTES:
        raise ValueError("serialized tool arguments exceed the byte limit")
    try:
        parsed = json.loads(
            value,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (RecursionError, json.JSONDecodeError) as error:
        raise ValueError("tool arguments must be one valid JSON object") from error
    if not isinstance(parsed, dict):
        raise ValueError("tool arguments must contain exactly one JSON object")
    try:
        _validate_safe_numbers(parsed)
        depth, nodes = _json_depth_and_nodes(parsed)
    except RecursionError as error:
        raise ValueError("tool arguments exceed structural limits") from error
    if depth > MAXIMUM_ARGUMENT_DEPTH or nodes > MAXIMUM_ARGUMENT_NODES:
        raise ValueError("tool arguments exceed structural limits")
    return parsed


def _json_values_equivalent(left: object, right: object) -> bool:
    return json.dumps(
        left,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ) == json.dumps(
        right,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


class AgentErrorCode(str, Enum):
    AGENT_UNAVAILABLE = "AGENT_UNAVAILABLE"
    AGENT_LIMIT_REACHED = "AGENT_LIMIT_REACHED"
    AGENT_CATALOG_LIMIT = "AGENT_CATALOG_LIMIT"
    INVALID_MODEL_RESPONSE = "INVALID_MODEL_RESPONSE"
    AUDIT_UNAVAILABLE = "AUDIT_UNAVAILABLE"


class AnswerBasis(str, Enum):
    GENERAL = "general"
    KNOWLEDGE = "knowledge"
    ERP_DATA = "erp_data"
    MIXED = "mixed"


class ToolSelectionMode(str, Enum):
    NO_TOOLS = "no_tools"
    REQUIRED_EXACT_TOOL = "required_exact_tool"
    FINAL_ONLY = "final_only"


class ModelToolSelection(BaseModel):
    """Server-owned provider-neutral tool selection for one model turn."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    mode: ToolSelectionMode
    tool_name: Code | None = Field(default=None, repr=False)
    version: Version | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def validate_selection(self) -> "ModelToolSelection":
        exact = self.mode is ToolSelectionMode.REQUIRED_EXACT_TOOL
        has_both = self.tool_name is not None and self.version is not None
        has_either = self.tool_name is not None or self.version is not None
        if (exact and not has_both) or (not exact and has_either):
            raise ValueError("tool selection is inconsistent")
        return self


class PublicCitation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    citation_id: Identifier
    title: DisplayText
    section: DisplayText
    language: LanguageCode
    source_type: KnowledgeSourceType
    document_version: CanonicalSemVer


class PublicChatSuccess(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    answer: Answer
    response_language: LanguageCode
    citations: tuple[PublicCitation, ...]

    @field_validator("citations")
    @classmethod
    def unique_citations(cls, value: tuple[PublicCitation, ...]) -> tuple[PublicCitation, ...]:
        ids = tuple(item.citation_id for item in value)
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate public citations are not allowed")
        return value


class PublicChatFailure(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    safe_error_code: AgentErrorCode
    safe_message: SafeMessage


class ModelToolDefinition(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, arbitrary_types_allowed=True
    )

    tool_name: Code
    version: Version
    input_schema: Mapping[str, object]

    @field_validator("input_schema", mode="after")
    @classmethod
    def freeze_schema(cls, value: Mapping[str, object]) -> Mapping[str, object]:
        frozen = _freeze_json(value)
        assert isinstance(frozen, Mapping)
        return frozen

    @field_serializer("input_schema")
    def serialize_schema(self, value: Mapping[str, object]) -> dict[str, object]:
        serialized = to_mutable_json(value)
        assert isinstance(serialized, dict)
        return serialized


class ToolResultMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)

    call_id: CallId
    tool_name: Code
    result: PublicToolSuccess | PublicToolFailure
    content_trust: Literal["untrusted_tool_result"] = "untrusted_tool_result"

    @field_serializer("result")
    def serialize_public_result(
        self, value: PublicToolSuccess | PublicToolFailure
    ) -> dict[str, object]:
        return value.model_dump(mode="json", serialize_as_any=True)


class ModelTurnRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    policy_instructions: tuple[str, ...]
    user_message: str
    response_language: LanguageCode
    tools: tuple[ModelToolDefinition, ...]
    tool_selection: ModelToolSelection = Field(repr=False)
    interactions: tuple["ModelToolInteraction", ...] = Field(repr=False)
    turn_number: int = Field(strict=True, ge=1)

    @model_validator(mode="after")
    def validate_interactions(self) -> "ModelTurnRequest":
        call_ids = tuple(item.assistant_call.call_id for item in self.interactions)
        if len(set(call_ids)) != len(call_ids):
            raise ValueError("duplicate interaction call IDs are not allowed")
        for interaction in self.interactions:
            ModelToolInteraction.model_validate(
                {
                    "assistant_call": interaction.assistant_call,
                    "tool_result": interaction.tool_result,
                },
                strict=True,
            )
        selection = self.tool_selection
        if selection.mode is ToolSelectionMode.NO_TOOLS:
            if self.tools or self.interactions:
                raise ValueError("no-tools turns cannot expose tools or interactions")
        elif selection.mode is ToolSelectionMode.REQUIRED_EXACT_TOOL:
            if self.interactions or len(self.tools) != 1:
                raise ValueError("required-tool turns expose exactly one tool and no interaction")
            exposed = self.tools[0]
            if exposed.tool_name != selection.tool_name or exposed.version != selection.version:
                raise ValueError("required tool does not match the exposed catalog")
        else:
            if self.tools or len(self.interactions) != 1:
                raise ValueError(
                    "final-only turns follow exactly one interaction and expose no tools"
                )
            result = self.interactions[0].tool_result.result
            if not isinstance(result, PublicToolSuccess):
                raise ValueError("final-only turns require one successful tool result")
        return self


class ModelFinalAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    response_type: Literal["final_answer"] = "final_answer"
    answer: Answer
    answer_basis: AnswerBasis
    evidence_call_ids: tuple[CallId, ...] = Field(max_length=4)
    citation_ids: tuple[Identifier, ...] = Field(max_length=20)

    @field_validator("answer_basis", mode="before")
    @classmethod
    def parse_answer_basis(cls, value: object) -> object:
        if isinstance(value, str):
            try:
                return AnswerBasis(value)
            except ValueError as error:
                raise ValueError("invalid answer basis") from error
        return value

    @field_validator("evidence_call_ids", "citation_ids", mode="before")
    @classmethod
    def freeze_identifier_collections(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("evidence_call_ids", "citation_ids")
    @classmethod
    def reject_duplicate_identifiers(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("duplicate identifiers are not allowed")
        return value


class ModelToolCall(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        arbitrary_types_allowed=True,
        hide_input_in_errors=True,
    )

    response_type: Literal["tool_call"] = "tool_call"
    call_id: CallId
    tool_name: Code
    version: Version
    arguments_json: str = Field(strict=True, repr=False)
    arguments: Mapping[str, object] = Field(repr=False)

    @field_validator("arguments", mode="after")
    @classmethod
    def freeze_arguments(cls, value: Mapping[str, object]) -> Mapping[str, object]:
        frozen = _freeze_json(value)
        assert isinstance(frozen, Mapping)
        return frozen

    @model_validator(mode="after")
    def raw_and_parsed_arguments_match(self) -> "ModelToolCall":
        parsed = _parse_arguments_json(self.arguments_json)
        if not _json_values_equivalent(parsed, to_mutable_json(self.arguments)):
            raise ValueError("raw and parsed tool arguments do not match")
        return self

    @classmethod
    def from_arguments_json(
        cls, *, call_id: str, tool_name: str, version: str, arguments_json: str
    ) -> "ModelToolCall":
        """Preserve provider JSON exactly while deriving its immutable parsed projection."""

        parsed = _parse_arguments_json(arguments_json)
        return cls(
            call_id=call_id,
            tool_name=tool_name,
            version=version,
            arguments_json=arguments_json,
            arguments=parsed,
        )

    @classmethod
    def from_arguments(
        cls, *, call_id: str, tool_name: str, version: str, arguments: Mapping[str, object]
    ) -> "ModelToolCall":
        """Build deterministic compact sorted JSON for fake and test providers."""

        mutable = to_mutable_json(_freeze_json(arguments))
        arguments_json = json.dumps(
            mutable, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        return cls.from_arguments_json(
            call_id=call_id,
            tool_name=tool_name,
            version=version,
            arguments_json=arguments_json,
        )

    @field_serializer("arguments")
    def serialize_arguments(self, value: Mapping[str, object]) -> dict[str, object]:
        serialized = to_mutable_json(value)
        assert isinstance(serialized, dict)
        return serialized


class ModelToolInteraction(BaseModel):
    """One ordered assistant call immediately paired with its untrusted public result."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)

    assistant_call: ModelToolCall = Field(repr=False)
    tool_result: ToolResultMessage = Field(repr=False)

    @model_validator(mode="after")
    def pair_call_and_result(self) -> "ModelToolInteraction":
        call = self.assistant_call
        message = self.tool_result
        ModelToolCall.from_arguments_json(
            call_id=call.call_id,
            tool_name=call.tool_name,
            version=call.version,
            arguments_json=call.arguments_json,
        )
        result_type = type(message.result)
        if result_type not in (PublicToolSuccess, PublicToolFailure):
            raise ValueError("tool interaction contains an invalid public result")
        validated_result = result_type.model_validate(
            message.result.model_dump(mode="python"), strict=True
        )
        ToolResultMessage.model_validate(
            {
                "call_id": message.call_id,
                "tool_name": message.tool_name,
                "result": validated_result,
                "content_trust": message.content_trust,
            },
            strict=True,
        )
        if call.call_id != message.call_id or call.tool_name != message.tool_name:
            raise ValueError("tool result does not match its assistant call")
        if call.tool_name != message.result.tool_name or call.version != message.result.version:
            raise ValueError("public tool result does not match its assistant call")
        return self


type ModelResponse = Annotated[
    ModelFinalAnswer | ModelToolCall,
    Field(discriminator="response_type"),
]
type PublicChatResult = PublicChatSuccess | PublicChatFailure


class AgentLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    maximum_model_turns: int = Field(default=6, strict=True, ge=1)
    maximum_tool_calls: int = Field(default=4, strict=True, ge=0)
    maximum_tool_result_bytes: int = Field(default=65_536, strict=True, ge=1)
    maximum_user_message_characters: int = Field(default=8_000, strict=True, ge=1)
    maximum_final_answer_characters: int = Field(default=8_000, strict=True, ge=1)
    maximum_tool_argument_bytes: int = Field(default=16_384, strict=True, ge=1)
    maximum_argument_depth: int = Field(default=10, strict=True, ge=1)
    maximum_argument_nodes: int = Field(default=512, strict=True, ge=1)
    maximum_model_tools: int = Field(default=32, strict=True, ge=1)
    maximum_tool_catalog_bytes: int = Field(default=131_072, strict=True, ge=1)
