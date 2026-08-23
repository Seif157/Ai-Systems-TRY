"""Strict immutable public and model-facing orchestration contracts."""

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
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

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
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    policy_instructions: tuple[str, ...]
    user_message: str
    response_language: LanguageCode
    tools: tuple[ModelToolDefinition, ...]
    tool_results: tuple[ToolResultMessage, ...]
    turn_number: int = Field(strict=True, ge=1)


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
        extra="forbid", frozen=True, strict=True, arbitrary_types_allowed=True
    )

    response_type: Literal["tool_call"] = "tool_call"
    call_id: CallId
    tool_name: Code
    version: Version
    arguments: Mapping[str, object] = Field(repr=False)

    @field_validator("arguments", mode="after")
    @classmethod
    def freeze_arguments(cls, value: Mapping[str, object]) -> Mapping[str, object]:
        frozen = _freeze_json(value)
        assert isinstance(frozen, Mapping)
        return frozen

    @field_serializer("arguments")
    def serialize_arguments(self, value: Mapping[str, object]) -> dict[str, object]:
        serialized = to_mutable_json(value)
        assert isinstance(serialized, dict)
        return serialized


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
