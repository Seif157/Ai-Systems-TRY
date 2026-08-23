"""Strict public contracts for HR knowledge search."""

import unicodedata
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from erp_ai.context.models import Identifier
from erp_ai.knowledge import KnowledgeSourceType
from erp_ai.knowledge.models import DisplayText, KnowledgeText, LanguageCode
from erp_ai.types import CanonicalSemVer


def _validate_query(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    value = value.strip()
    if not value:
        raise ValueError("query must not be blank")
    if any(character == "\x00" or unicodedata.category(character) == "Cc" for character in value):
        raise ValueError("query contains unsafe control characters")
    return value


QueryText = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=1000),
]


class SearchHrKnowledgeInput(BaseModel):
    """The only model-provided knowledge-search argument."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    query: QueryText = Field(repr=False)

    @field_validator("query", mode="before")
    @classmethod
    def validate_query(cls, value: Any) -> Any:
        return _validate_query(value)


class KnowledgeExcerpt(BaseModel):
    """Safe public excerpt; content remains untrusted knowledge data."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    citation_id: Identifier
    title: DisplayText
    section: DisplayText
    language: LanguageCode
    source_type: KnowledgeSourceType
    document_version: CanonicalSemVer
    content: KnowledgeText = Field(repr=False)
    content_trust: Literal["untrusted_knowledge_excerpt"] = "untrusted_knowledge_excerpt"


class SearchHrKnowledgeOutput(BaseModel):
    """Immutable safe search result preserving provider order."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    excerpts: tuple[KnowledgeExcerpt, ...]

    @field_validator("excerpts", mode="before")
    @classmethod
    def freeze_excerpts(cls, value: Any) -> Any:
        return tuple(value) if isinstance(value, list) else value
