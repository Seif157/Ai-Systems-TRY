"""Strict immutable contracts for explicitly cataloged knowledge sources."""

from datetime import datetime
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from erp_ai.capabilities import DataClassification
from erp_ai.capabilities.models import Code, PolicyCode, Version
from erp_ai.context.models import Identifier
from erp_ai.knowledge import KnowledgeSourceType
from erp_ai.knowledge.ingestion.models import Digest
from erp_ai.knowledge.models import LanguageCode

RelativeMarkdownPath = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=500)]


def _freeze_unique(value: Any) -> Any:
    value = tuple(value) if isinstance(value, list) else value
    if isinstance(value, tuple) and len(set(value)) != len(value):
        raise ValueError("duplicate scope values are not allowed")
    return value


class MarkdownSourceEntry(BaseModel):
    """Trusted catalog metadata for one explicitly enumerated Markdown file."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    path: RelativeMarkdownPath
    raw_sha256: Digest
    document_id: UUID
    document_version: Version
    namespace: Code
    source_type: KnowledgeSourceType
    customer_environment_id: Identifier | None = None
    title: str = Field(strict=True, min_length=1, max_length=300)
    language: LanguageCode
    modules: tuple[Code, ...]
    permissions: tuple[PolicyCode, ...]
    allowed_purposes: tuple[Code, ...] = Field(min_length=1)
    legal_entities: tuple[Identifier, ...]
    classification: DataClassification
    effective_from: datetime
    effective_to: datetime | None = None
    approval_reference: Identifier
    approved_at: datetime

    @field_validator("path")
    @classmethod
    def relative_markdown_path(cls, value: str) -> str:
        if "\\" in value or value.startswith("./"):
            raise ValueError("source path must use normalized relative POSIX syntax")
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or ":" in path.parts[0]:
            raise ValueError("source path must be relative and confined")
        if any(part in {"", "."} for part in path.parts) or path.suffix.lower() != ".md":
            raise ValueError("source path must identify a relative Markdown file")
        return value.replace("\\", "/")

    @field_validator("modules", "permissions", "allowed_purposes", "legal_entities", mode="before")
    @classmethod
    def immutable_unique_scope(cls, value: Any) -> Any:
        return _freeze_unique(value)

    @field_validator("source_type", mode="before")
    @classmethod
    def source_type_enum(cls, value: Any) -> Any:
        return KnowledgeSourceType(value) if isinstance(value, str) else value

    @field_validator("classification", mode="before")
    @classmethod
    def classification_enum(cls, value: Any) -> Any:
        return DataClassification(value) if isinstance(value, str) else value

    @field_validator("effective_from", "effective_to", "approved_at")
    @classmethod
    def aware_dates(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("catalog timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def valid_effective_range(self) -> "MarkdownSourceEntry":
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must be later than effective_from")
        return self


class MarkdownSourceCatalog(BaseModel):
    """Versioned allowlist; every readable source must be enumerated here."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    catalog_version: Literal[1]
    entries: tuple[MarkdownSourceEntry, ...] = Field(min_length=1)

    @field_validator("entries", mode="before")
    @classmethod
    def freeze_entries(cls, value: Any) -> Any:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def unique_entries(self) -> "MarkdownSourceCatalog":
        paths = tuple(entry.path.casefold() for entry in self.entries)
        document_ids = tuple(entry.document_id for entry in self.entries)
        if len(set(paths)) != len(paths):
            raise ValueError("duplicate catalog paths are not allowed")
        if len(set(document_ids)) != len(document_ids):
            raise ValueError("duplicate document IDs are not allowed")
        return self
