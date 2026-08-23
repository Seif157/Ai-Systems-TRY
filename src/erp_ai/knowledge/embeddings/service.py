"""Bounded deterministic materialization of one immutable generation."""

import asyncio
import hashlib
import json
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from erp_ai.knowledge.embeddings.models import (
    EmbeddingBatchRequest,
    EmbeddingInput,
    EmbeddingProfile,
    PreparedEmbedding,
    PreparedEmbeddingSet,
)
from erp_ai.knowledge.embeddings.provider import EmbeddingProvider
from erp_ai.knowledge.indexing import KnowledgeIndexScope
from erp_ai.knowledge.ingestion.models import Digest


class EmbeddingMaterializationError(RuntimeError):
    pass


class EmbeddingGenerationSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    scope: KnowledgeIndexScope
    generation_id: UUID
    generation_digest: Digest
    chunks: tuple[EmbeddingInput, ...] = Field(min_length=1, repr=False)

    @field_validator("chunks", mode="before")
    @classmethod
    def immutable_chunks(cls, value: Any) -> Any:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("chunks")
    @classmethod
    def unique_ordered_chunks(cls, value: tuple[EmbeddingInput, ...]) -> tuple[EmbeddingInput, ...]:
        ordered = tuple(sorted(value, key=lambda item: item.input_id))
        if len({item.input_id for item in ordered}) != len(ordered):
            raise ValueError("duplicate generation chunks are forbidden")
        return ordered


class EmbeddingMaterializer:
    __slots__ = ("_batch_size", "_provider")

    def __init__(self, provider: EmbeddingProvider, *, batch_size: int = 64) -> None:
        if isinstance(batch_size, bool) or not 1 <= batch_size <= 512:
            raise ValueError("batch_size must be between 1 and 512")
        self._provider = provider
        self._batch_size = batch_size

    async def materialize(
        self, source: EmbeddingGenerationSource, profile: EmbeddingProfile
    ) -> PreparedEmbeddingSet:
        try:
            source = EmbeddingGenerationSource.model_validate(source.model_dump())
            profile = EmbeddingProfile.model_validate(
                profile.model_dump(exclude={"profile_sha256"})
            )
        except ValidationError:
            raise EmbeddingMaterializationError("invalid materialization contract") from None
        allowed = set(profile.allowed_data_classifications)
        if any(chunk.data_classification not in allowed for chunk in source.chunks):
            raise EmbeddingMaterializationError("embedding profile classification mismatch")
        prepared: list[PreparedEmbedding] = []
        try:
            for offset in range(0, len(source.chunks), self._batch_size):
                inputs = source.chunks[offset : offset + self._batch_size]
                result = await self._provider.embed(
                    EmbeddingBatchRequest(profile=profile, inputs=inputs)
                )
                expected = {item.input_id: item for item in inputs}
                returned = {item.input_id: item for item in result.vectors}
                if (
                    result.profile_sha256 != profile.profile_sha256
                    or returned.keys() != expected.keys()
                ):
                    raise EmbeddingMaterializationError("embedding provider result mismatch")
                for input_id in sorted(expected):
                    vector = returned[input_id]
                    if len(vector.values) != profile.dimensions:
                        raise EmbeddingMaterializationError("embedding provider dimension mismatch")
                    prepared.append(
                        PreparedEmbedding.model_validate(
                            {
                                "chunk_id": input_id,
                                "content_sha256": expected[input_id].content_sha256,
                                "values": vector.values,
                                "vector_sha256": vector.vector_sha256,
                            }
                        )
                    )
        except asyncio.CancelledError:
            raise
        except EmbeddingMaterializationError:
            raise
        except Exception:
            raise EmbeddingMaterializationError("embedding materialization failed") from None
        ordered = tuple(sorted(prepared, key=lambda item: item.chunk_id))
        digest = hashlib.sha256(
            json.dumps(
                {
                    "customer_environment_id": source.scope.customer_environment_id,
                    "embedding_profile_sha256": profile.profile_sha256,
                    "embeddings": [
                        {
                            "chunk_id": item.chunk_id,
                            "content_sha256": item.content_sha256,
                            "vector_sha256": item.vector_sha256,
                        }
                        for item in ordered
                    ],
                    "generation_digest": source.generation_digest,
                    "generation_id": str(source.generation_id),
                    "namespace": source.scope.namespace,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        return PreparedEmbeddingSet.model_validate(
            {
                "scope": source.scope.model_dump(),
                "generation_id": source.generation_id,
                "generation_digest": source.generation_digest,
                "profile": profile.model_dump(exclude={"profile_sha256"}),
                "embeddings": [item.model_dump() for item in ordered],
                "embedding_set_sha256": digest,
            }
        )
