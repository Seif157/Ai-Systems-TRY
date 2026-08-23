"""Strict internal contracts for pre-filtered knowledge retrieval."""

from datetime import datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from erp_ai.capabilities import DataClassification
from erp_ai.context.models import Code, Identifier, PolicyCode
from erp_ai.types import CanonicalSemVer


def _strip_text(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


def _reject_blank_text(value: Any) -> Any:
    if isinstance(value, str) and not value.strip():
        raise ValueError("knowledge content must not be blank")
    return value


KnowledgeText = Annotated[
    str,
    BeforeValidator(_reject_blank_text),
    StringConstraints(strict=True, min_length=1, max_length=4000),
]
DisplayText = Annotated[
    str,
    BeforeValidator(_strip_text),
    StringConstraints(strict=True, min_length=1, max_length=300),
]
LanguageCode = Annotated[
    str,
    StringConstraints(
        strict=True, min_length=2, max_length=35, pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$"
    ),
]


class KnowledgeSourceType(str, Enum):
    """Approved knowledge-source ownership categories."""

    PRODUCT_DOCUMENTATION = "product_documentation"
    CUSTOMER_POLICY = "customer_policy"


def _immutable_tuple(value: Any) -> Any:
    return tuple(value) if isinstance(value, list) else value


def _unique_tuple(value: Any) -> Any:
    value = _immutable_tuple(value)
    if isinstance(value, tuple) and len(set(value)) != len(value):
        raise ValueError("duplicate scope values are not allowed")
    return value


class KnowledgeRetrievalRequest(BaseModel):
    """Complete trusted request supplied to an authorization-filtering provider."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    namespace: Code
    query: KnowledgeText = Field(repr=False)
    maximum_results: int = Field(strict=True, ge=1, le=5)
    customer_environment_id: Identifier = Field(repr=False)
    enabled_modules: tuple[Code, ...] = Field(repr=False)
    permission_codes: tuple[PolicyCode, ...] = Field(repr=False)
    roles: tuple[Code, ...] = Field(repr=False)
    authorized_legal_entity_ids: tuple[Identifier, ...] = Field(repr=False)
    purpose: Code
    locale: LanguageCode
    effective_at: datetime

    @field_validator(
        "enabled_modules", "permission_codes", "roles", "authorized_legal_entity_ids", mode="before"
    )
    @classmethod
    def freeze_collections(cls, value: Any) -> Any:
        return _unique_tuple(value)

    @field_validator("effective_at")
    @classmethod
    def require_aware_effective_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("effective_at must be timezone-aware")
        return value


class KnowledgeMatch(BaseModel):
    """Internal provider match containing all metadata needed for post-validation."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    chunk_id: Identifier
    document_id: Identifier
    citation_id: Identifier
    namespace: Code
    source_type: KnowledgeSourceType
    customer_environment_id: Identifier | None
    required_modules_all: tuple[Code, ...]
    required_permissions_all: tuple[PolicyCode, ...]
    allowed_purposes: tuple[Code, ...] = Field(min_length=1)
    legal_entity_ids: tuple[Identifier, ...]
    data_classification: DataClassification
    language: LanguageCode
    title: DisplayText
    section: DisplayText
    document_version: CanonicalSemVer
    effective_from: datetime
    effective_to: datetime | None = None
    content: KnowledgeText = Field(repr=False)
    relevance_score: float = Field(strict=True, ge=0, le=1, repr=False)

    @field_validator(
        "required_modules_all",
        "required_permissions_all",
        "allowed_purposes",
        "legal_entity_ids",
        mode="before",
    )
    @classmethod
    def freeze_collections(cls, value: Any) -> Any:
        return _unique_tuple(value)

    @field_validator("source_type", mode="before")
    @classmethod
    def parse_source_type(cls, value: Any) -> Any:
        try:
            return KnowledgeSourceType(value)
        except (TypeError, ValueError) as error:
            raise ValueError("invalid knowledge source type") from error

    @field_validator("data_classification", mode="before")
    @classmethod
    def parse_classification(cls, value: Any) -> Any:
        try:
            return DataClassification(value)
        except (TypeError, ValueError) as error:
            raise ValueError("invalid data classification") from error

    @field_validator("effective_from", "effective_to")
    @classmethod
    def require_aware_dates(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("knowledge effective timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_effective_range(self) -> "KnowledgeMatch":
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to must not precede effective_from")
        return self
