"""Strict immutable embedding contracts and canonical float32 hashing."""

import hashlib
import json
import math
import struct
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from erp_ai.capabilities import DataClassification
from erp_ai.capabilities.models import Code
from erp_ai.context.models import Identifier
from erp_ai.knowledge.indexing import KnowledgeIndexScope
from erp_ai.knowledge.ingestion.models import Digest
from erp_ai.knowledge.models import KnowledgeText


class EmbeddingDistanceMetric(str, Enum):
    COSINE = "cosine"


class EmbeddingStorageRepresentation(str, Enum):
    FLOAT32 = "float32"


def _canonical_json_digest(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _float32(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("embedding values must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("embedding values must be finite")
    try:
        converted = float(struct.unpack("!f", struct.pack("!f", number))[0])
    except OverflowError:
        raise ValueError("embedding value is outside float32 range") from None
    if not math.isfinite(converted):  # pragma: no cover - defensive struct invariant
        raise ValueError("embedding float32 values must be finite")
    return converted


class EmbeddingProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    contract_version: Literal[1]
    profile_id: Code
    provider_id: Code = Field(repr=False)
    model_id: Identifier = Field(repr=False)
    model_revision: Identifier = Field(repr=False)
    dimensions: int = Field(strict=True, ge=1, le=4096)
    distance_metric: Literal[EmbeddingDistanceMetric.COSINE]
    storage_representation: Literal[EmbeddingStorageRepresentation.FLOAT32]
    input_normalization_version: int = Field(strict=True, ge=1)
    allowed_data_classifications: tuple[DataClassification, ...] = Field(min_length=1, repr=False)

    @field_validator("allowed_data_classifications", mode="before")
    @classmethod
    def immutable_classifications(cls, value: Any) -> Any:
        if not isinstance(value, (list, tuple)):
            return value
        normalized = tuple(DataClassification(item) for item in value)
        if len(set(normalized)) != len(normalized):
            raise ValueError("duplicate data classifications are forbidden")
        return tuple(sorted(normalized, key=lambda item: item.value))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def profile_sha256(self) -> str:
        return _canonical_json_digest(
            {
                "allowed_data_classifications": [
                    item.value for item in self.allowed_data_classifications
                ],
                "contract_version": self.contract_version,
                "dimensions": self.dimensions,
                "distance_metric": self.distance_metric.value,
                "input_normalization_version": self.input_normalization_version,
                "model_id": self.model_id,
                "model_revision": self.model_revision,
                "profile_id": self.profile_id,
                "provider_id": self.provider_id,
                "storage_representation": self.storage_representation.value,
            }
        )


class EmbeddingInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    input_id: Identifier
    text: KnowledgeText = Field(repr=False)
    content_sha256: Digest
    data_classification: DataClassification


class EmbeddingVector(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    input_id: Identifier
    values: tuple[float, ...] = Field(min_length=1, repr=False)

    @field_validator("values", mode="before")
    @classmethod
    def canonical_float32_values(cls, value: Any) -> Any:
        if not isinstance(value, (list, tuple)):
            return value
        converted = tuple(_float32(item) for item in value)
        if not any(item != 0.0 for item in converted):
            raise ValueError("cosine embeddings must not be zero vectors")
        return converted

    @computed_field  # type: ignore[prop-decorator]
    @property
    def vector_sha256(self) -> str:
        return hashlib.sha256(b"".join(struct.pack("!f", item) for item in self.values)).hexdigest()


class EmbeddingBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    profile: EmbeddingProfile = Field(repr=False)
    inputs: tuple[EmbeddingInput, ...] = Field(min_length=1, repr=False)

    @field_validator("inputs", mode="before")
    @classmethod
    def immutable_inputs(cls, value: Any) -> Any:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("inputs")
    @classmethod
    def unique_inputs(cls, value: tuple[EmbeddingInput, ...]) -> tuple[EmbeddingInput, ...]:
        if len({item.input_id for item in value}) != len(value):
            raise ValueError("duplicate embedding input IDs are forbidden")
        return value


class EmbeddingBatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    profile_sha256: Digest
    vectors: tuple[EmbeddingVector, ...] = Field(repr=False)

    @field_validator("vectors", mode="before")
    @classmethod
    def immutable_vectors(cls, value: Any) -> Any:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("vectors")
    @classmethod
    def unique_vectors(cls, value: tuple[EmbeddingVector, ...]) -> tuple[EmbeddingVector, ...]:
        if len({item.input_id for item in value}) != len(value):
            raise ValueError("duplicate embedding result IDs are forbidden")
        return value


class PreparedEmbedding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    chunk_id: Identifier
    content_sha256: Digest
    values: tuple[float, ...] = Field(repr=False)
    vector_sha256: Digest

    @model_validator(mode="after")
    def validate_vector_hash(self) -> "PreparedEmbedding":
        vector = EmbeddingVector(input_id=self.chunk_id, values=self.values)
        if vector.vector_sha256 != self.vector_sha256:
            raise ValueError("prepared embedding hash mismatch")
        return self


class PreparedEmbeddingSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    scope: KnowledgeIndexScope
    generation_id: UUID
    generation_digest: Digest
    profile: EmbeddingProfile = Field(repr=False)
    embeddings: tuple[PreparedEmbedding, ...] = Field(min_length=1, repr=False)
    embedding_set_sha256: Digest

    @field_validator("embeddings", mode="before")
    @classmethod
    def immutable_embeddings(cls, value: Any) -> Any:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_complete_set(self) -> "PreparedEmbeddingSet":
        ordered = tuple(sorted(self.embeddings, key=lambda item: item.chunk_id))
        if ordered != self.embeddings or len({item.chunk_id for item in ordered}) != len(ordered):
            raise ValueError("prepared embeddings must be unique and canonically ordered")
        if any(len(item.values) != self.profile.dimensions for item in ordered):
            raise ValueError("prepared embedding dimensions mismatch")
        expected = _canonical_json_digest(
            {
                "customer_environment_id": self.scope.customer_environment_id,
                "embedding_profile_sha256": self.profile.profile_sha256,
                "embeddings": [
                    {
                        "chunk_id": item.chunk_id,
                        "content_sha256": item.content_sha256,
                        "vector_sha256": item.vector_sha256,
                    }
                    for item in ordered
                ],
                "generation_digest": self.generation_digest,
                "generation_id": str(self.generation_id),
                "namespace": self.scope.namespace,
            }
        )
        if expected != self.embedding_set_sha256:
            raise ValueError("embedding-set digest mismatch")
        return self


class EmbeddingMaterializationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    operation_id: Identifier
    scope: KnowledgeIndexScope
    generation_id: UUID
    generation_digest: Digest
    profile_id: Code
    profile_sha256: Digest
    embedding_set_sha256: Digest
    embedding_count: int = Field(strict=True, ge=1)
    disposition: Literal["materialized", "idempotent"]
