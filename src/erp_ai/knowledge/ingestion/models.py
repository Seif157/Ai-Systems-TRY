"""Strict immutable ingestion-preparation contracts."""

from datetime import datetime
from enum import Enum
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
from erp_ai.knowledge.ingestion.normalization import normalize_text
from erp_ai.knowledge.models import LanguageCode

SectionKey = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_]*$"),
]
Digest = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]
OpaquePreparedId = Annotated[
    str, StringConstraints(strict=True, pattern=r"^(?:chk|cite)_[0-9a-f]{32}$")
]


class SourceProvenance(BaseModel):
    """Internal, path-free provenance that makes adapter behavior fingerprint-visible."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    catalog_version: Literal[1]
    raw_source_sha256: Digest
    parser_name: Literal["markdown-it-py"]
    parser_major_version: int = Field(strict=True, ge=1)
    adapter_contract_version: Literal[1]


def _tuple(value: Any) -> Any:
    return tuple(value) if isinstance(value, list) else value


def _unique(value: Any) -> Any:
    value = _tuple(value)
    if isinstance(value, tuple) and len(set(value)) != len(value):
        raise ValueError("duplicate scope values are not allowed")
    return value


class KnowledgeSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    section_key: SectionKey
    heading: str
    text_blocks: tuple[str, ...] = Field(min_length=1)

    @field_validator("text_blocks", mode="before")
    @classmethod
    def freeze_blocks(cls, value: Any) -> Any:
        return _tuple(value)

    @field_validator("heading")
    @classmethod
    def normalize_heading(cls, value: str) -> str:
        return normalize_text(value)

    @field_validator("text_blocks")
    @classmethod
    def normalize_blocks(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(normalize_text(block) for block in value)


class KnowledgeDocumentDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    document_id: UUID
    document_version: Version
    namespace: Code
    source_type: KnowledgeSourceType
    customer_environment_id: Identifier | None
    title: str
    language: LanguageCode
    required_modules_all: tuple[Code, ...]
    required_permissions_all: tuple[PolicyCode, ...]
    allowed_purposes: tuple[Code, ...] = Field(min_length=1)
    legal_entity_ids: tuple[Identifier, ...]
    data_classification: DataClassification
    effective_from: datetime
    effective_to: datetime | None = None
    approval_reference: Identifier
    approved_at: datetime
    source_provenance: SourceProvenance | None = None
    sections: tuple[KnowledgeSection, ...] = Field(min_length=1)

    @field_validator(
        "required_modules_all",
        "required_permissions_all",
        "allowed_purposes",
        "legal_entity_ids",
        mode="before",
    )
    @classmethod
    def freeze_unique_scope(cls, value: Any) -> Any:
        return _unique(value)

    @field_validator("sections", mode="before")
    @classmethod
    def freeze_sections(cls, value: Any) -> Any:
        return _tuple(value)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return normalize_text(value)

    @field_validator("source_type", mode="before")
    @classmethod
    def parse_source_type(cls, value: Any) -> Any:
        return KnowledgeSourceType(value) if isinstance(value, str) else value

    @field_validator("data_classification", mode="before")
    @classmethod
    def parse_classification(cls, value: Any) -> Any:
        return DataClassification(value) if isinstance(value, str) else value

    @field_validator("effective_from", "effective_to", "approved_at")
    @classmethod
    def aware_timestamps(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_governance(self) -> "KnowledgeDocumentDraft":
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must be later than effective_from")
        section_keys = tuple(section.section_key for section in self.sections)
        if len(set(section_keys)) != len(section_keys):
            raise ValueError("duplicate section keys are not allowed")
        return self


class ExistingDocumentManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    document_id: UUID
    document_version: Version
    document_fingerprint: Digest


class PreparationDisposition(str, Enum):
    NEW_DOCUMENT = "new_document"
    IDEMPOTENT = "idempotent"
    SUPERSEDING_VERSION = "superseding_version"


class PreparedDocumentManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    document_id: UUID
    document_version: Version
    namespace: Code
    source_type: KnowledgeSourceType
    customer_environment_id: Identifier | None
    source_provenance: SourceProvenance | None
    normalized_content_sha256: Digest
    governance_sha256: Digest
    document_fingerprint: Digest
    supersedes_version: Version | None


class PreparedKnowledgeChunk(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    chunk_id: OpaquePreparedId
    citation_id: OpaquePreparedId
    document_id: UUID
    document_version: Version
    chunk_ordinal: int = Field(strict=True, ge=0)
    namespace: Code
    section_key: SectionKey
    heading: str
    source_type: KnowledgeSourceType
    customer_environment_id: Identifier | None
    required_modules_all: tuple[Code, ...]
    required_permissions_all: tuple[PolicyCode, ...]
    allowed_purposes: tuple[Code, ...]
    legal_entity_ids: tuple[Identifier, ...]
    data_classification: DataClassification
    language: LanguageCode
    title: str
    effective_from: datetime
    effective_to: datetime | None
    content: str = Field(repr=False)


class PreparedKnowledgeBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    manifest: PreparedDocumentManifest
    chunks: tuple[PreparedKnowledgeChunk, ...]
    disposition: PreparationDisposition
    total_normalized_utf8_bytes: int = Field(strict=True, ge=1)
    total_chunk_count: int = Field(strict=True, ge=1)


class IngestionLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    maximum_document_bytes: int = Field(default=1_048_576, strict=True, ge=1)
    maximum_sections: int = Field(default=500, strict=True, ge=1)
    maximum_blocks: int = Field(default=5_000, strict=True, ge=1)
    maximum_chunks: int = Field(default=2_000, strict=True, ge=1)
    maximum_block_bytes: int = Field(default=16_384, strict=True, ge=1)
    maximum_chunk_characters: int = Field(default=2_000, strict=True, ge=1)
    maximum_chunk_bytes: int = Field(default=8_192, strict=True, ge=1)
    overlap_characters: int = Field(default=200, strict=True, ge=0)
