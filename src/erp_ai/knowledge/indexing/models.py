"""Strict immutable contracts for atomic full-generation knowledge publication."""

from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from erp_ai.capabilities.models import Code
from erp_ai.context.models import Identifier
from erp_ai.knowledge.ingestion.models import Digest, PreparedKnowledgeBundle


def _tuple_unique(value: Any) -> Any:
    value = tuple(value) if isinstance(value, list) else value
    if isinstance(value, tuple) and len(set(value)) != len(value):
        raise ValueError("duplicate values are not allowed")
    return tuple(sorted(value)) if isinstance(value, tuple) else value


class PublicationDisposition(str, Enum):
    PUBLISHED = "published"
    IDEMPOTENT = "idempotent"
    ROLLED_BACK = "rolled_back"


class GenerationStatus(str, Enum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    RETIRED = "retired"


class KnowledgeIndexScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    namespace: Code
    customer_environment_id: Identifier


class KnowledgePublicationContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    operation_id: Identifier
    request_id: Identifier
    customer_environment_id: Identifier
    actor_id: Identifier = Field(repr=False)
    namespace: Code
    installed_modules: tuple[Code, ...] = Field(repr=False)
    authorization_snapshot_id: Identifier = Field(repr=False)
    issued_at: datetime

    @field_validator("installed_modules", mode="before")
    @classmethod
    def immutable_modules(cls, value: Any) -> Any:
        return _tuple_unique(value)

    @field_validator("issued_at")
    @classmethod
    def aware_issued_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("issued_at must be timezone-aware")
        return value


class KnowledgeGenerationManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    generation_id: UUID
    scope: KnowledgeIndexScope
    generation_digest: Digest
    publication_contract_version: Literal[1]
    document_count: int = Field(strict=True, ge=1)
    chunk_count: int = Field(strict=True, ge=1)
    total_normalized_bytes: int = Field(strict=True, ge=1)
    status: GenerationStatus


class KnowledgePublicationAuditOutboxEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    outbox_id: UUID
    operation_id: Identifier
    request_id: Identifier
    customer_environment_id: Identifier
    actor_id: Identifier = Field(repr=False)
    namespace: Code
    action: Literal["knowledge.publish", "knowledge.rollback"]
    previous_generation_id: UUID | None
    activated_generation_id: UUID
    generation_digest: Digest
    outcome: Literal["succeeded"]


class KnowledgePublicationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    context: KnowledgePublicationContext = Field(repr=False)
    manifest: KnowledgeGenerationManifest
    bundles: tuple[PreparedKnowledgeBundle, ...] = Field(min_length=1, repr=False)
    operation_digest: Digest
    outbox_event: KnowledgePublicationAuditOutboxEvent

    @field_validator("bundles", mode="before")
    @classmethod
    def immutable_bundles(cls, value: Any) -> Any:
        return tuple(value) if isinstance(value, list) else value


class KnowledgePublicationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    operation_id: Identifier
    scope: KnowledgeIndexScope
    generation_id: UUID
    previous_generation_id: UUID | None
    generation_digest: Digest
    operation_digest: Digest = Field(repr=False)
    disposition: PublicationDisposition


class KnowledgeIndexSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    scope: KnowledgeIndexScope
    active_generation_id: UUID
    generation_digest: Digest
    publication_contract_version: Literal[1]


class KnowledgeRollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    context: KnowledgePublicationContext = Field(repr=False)
    scope: KnowledgeIndexScope
    target_generation_id: UUID
    operation_digest: Digest
    outbox_id: UUID


class KnowledgeRollbackResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    operation_id: Identifier
    scope: KnowledgeIndexScope
    activated_generation_id: UUID
    previous_generation_id: UUID
    generation_digest: Digest
    operation_digest: Digest = Field(repr=False)
    disposition: PublicationDisposition


KnowledgeOperationResult = KnowledgePublicationResult | KnowledgeRollbackResult


class IndexPublicationLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    maximum_documents: int = Field(default=10_000, strict=True, ge=1)
    maximum_chunks: int = Field(default=500_000, strict=True, ge=1)
    maximum_normalized_bytes: int = Field(default=2_147_483_648, strict=True, ge=1)
    maximum_bundles_per_call: int = Field(default=10_000, strict=True, ge=1)
