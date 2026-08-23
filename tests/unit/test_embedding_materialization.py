import asyncio
import hashlib
from uuid import UUID

import pytest
from pydantic import ValidationError

from erp_ai.capabilities import DataClassification
from erp_ai.knowledge.embeddings import (
    EmbeddingBatchRequest,
    EmbeddingBatchResult,
    EmbeddingGenerationSource,
    EmbeddingInput,
    EmbeddingMaterializationError,
    EmbeddingMaterializer,
    EmbeddingVector,
    PreparedEmbeddingSet,
)
from erp_ai.knowledge.indexing import KnowledgeIndexScope
from tests.unit.test_embedding_models import profile


class DeterministicEmbeddingProvider:
    def __init__(self, *, mode: str = "valid") -> None:
        self.mode = mode
        self.requests: list[EmbeddingBatchRequest] = []

    async def embed(self, request: EmbeddingBatchRequest) -> EmbeddingBatchResult:
        self.requests.append(request)
        vectors = tuple(
            EmbeddingVector(
                input_id=item.input_id,
                values=(float(item.input_id.rsplit("_", 1)[-1]) + 1.0, 1.0, -1.0),
            )
            for item in request.inputs
        )
        if self.mode == "missing":
            vectors = vectors[:-1]
        elif self.mode == "additional":
            vectors += (EmbeddingVector(input_id="additional", values=(1.0, 1.0, 1.0)),)
        elif self.mode == "wrong_profile":
            return EmbeddingBatchResult(profile_sha256="f" * 64, vectors=vectors)
        elif self.mode == "wrong_dimensions":
            vectors = tuple(
                EmbeddingVector(input_id=item.input_id, values=(1.0,)) for item in request.inputs
            )
        elif self.mode == "failure":
            raise RuntimeError("provider details")
        return EmbeddingBatchResult(
            profile_sha256=request.profile.profile_sha256,
            vectors=vectors,
        )


def source() -> EmbeddingGenerationSource:
    return EmbeddingGenerationSource(
        scope=KnowledgeIndexScope(namespace="hr", customer_environment_id="customer-a"),
        generation_id=UUID("00000000-0000-0000-0000-000000000001"),
        generation_digest="b" * 64,
        chunks=tuple(
            EmbeddingInput(
                input_id=f"chunk_{index}",
                text=f"Text {index}",
                content_sha256=hashlib.sha256(f"Text {index}".encode()).hexdigest(),
                data_classification=DataClassification.INTERNAL,
            )
            for index in range(3)
        ),
    )


def test_materialization_is_bounded_complete_and_deterministic() -> None:
    provider = DeterministicEmbeddingProvider()
    materializer = EmbeddingMaterializer(provider, batch_size=2)
    first = asyncio.run(materializer.materialize(source(), profile()))
    second = asyncio.run(
        EmbeddingMaterializer(DeterministicEmbeddingProvider(), batch_size=3).materialize(
            source(), profile()
        )
    )
    assert len(provider.requests) == 2
    assert all(len(request.inputs) <= 2 for request in provider.requests)
    assert first.embedding_set_sha256 == second.embedding_set_sha256
    assert tuple(item.chunk_id for item in first.embeddings) == ("chunk_0", "chunk_1", "chunk_2")
    assert first.generation_digest == "b" * 64
    assert "Text" not in repr(first)
    with pytest.raises(ValidationError):
        first.embeddings = ()  # type: ignore[misc]


@pytest.mark.parametrize(
    "mode", ("missing", "additional", "wrong_profile", "wrong_dimensions", "failure")
)
def test_materialization_rejects_partial_mismatched_and_failed_provider(mode: str) -> None:
    with pytest.raises(EmbeddingMaterializationError):
        asyncio.run(
            EmbeddingMaterializer(DeterministicEmbeddingProvider(mode=mode)).materialize(
                source(), profile()
            )
        )


def test_materialization_rejects_invalid_batch_and_tampered_set() -> None:
    with pytest.raises(ValueError):
        EmbeddingMaterializer(DeterministicEmbeddingProvider(), batch_size=0)
    valid = asyncio.run(
        EmbeddingMaterializer(DeterministicEmbeddingProvider()).materialize(source(), profile())
    )
    with pytest.raises(ValidationError):
        PreparedEmbeddingSet.model_validate(
            {
                **valid.model_dump(exclude={"profile": {"profile_sha256"}}),
                "embedding_set_sha256": "0" * 64,
            }
        )
    reversed_items = tuple(reversed(valid.embeddings))
    with pytest.raises(ValidationError, match="canonically ordered"):
        PreparedEmbeddingSet.model_validate(
            {
                **valid.model_dump(exclude={"profile": {"profile_sha256"}}),
                "embeddings": reversed_items,
            }
        )
    wrong_dimension = valid.embeddings[0].model_copy(
        update={
            "values": (1.0,),
            "vector_sha256": EmbeddingVector(input_id="x", values=(1.0,)).vector_sha256,
        }
    )
    with pytest.raises(ValidationError, match="dimensions mismatch"):
        PreparedEmbeddingSet.model_validate(
            {
                **valid.model_dump(exclude={"profile": {"profile_sha256"}}),
                "embeddings": (wrong_dimension, *valid.embeddings[1:]),
            }
        )
    with pytest.raises(ValidationError, match="duplicate generation chunks"):
        EmbeddingGenerationSource.model_validate(
            {**source().model_dump(), "chunks": (source().chunks[0], source().chunks[0])}
        )


def test_materialization_preserves_cancellation() -> None:
    class CancelledProvider:
        async def embed(self, request: EmbeddingBatchRequest) -> EmbeddingBatchResult:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(EmbeddingMaterializer(CancelledProvider()).materialize(source(), profile()))


def test_materialization_defensively_revalidates_copied_contracts() -> None:
    valid_source = source()
    invalid_chunk = valid_source.chunks[0].model_copy(update={"text": None})
    copied_source = valid_source.model_copy(
        update={"chunks": (invalid_chunk, *valid_source.chunks[1:])}
    )
    with pytest.raises(EmbeddingMaterializationError, match="contract"):
        asyncio.run(
            EmbeddingMaterializer(DeterministicEmbeddingProvider()).materialize(
                copied_source, profile()
            )
        )
    restricted_profile = profile(allowed_data_classifications=("public",))
    with pytest.raises(EmbeddingMaterializationError, match="classification"):
        asyncio.run(
            EmbeddingMaterializer(DeterministicEmbeddingProvider()).materialize(
                valid_source, restricted_profile
            )
        )
    with pytest.raises(EmbeddingMaterializationError, match="contract"):
        asyncio.run(
            EmbeddingMaterializer(DeterministicEmbeddingProvider()).materialize(
                valid_source, profile().model_copy(update={"dimensions": 0})
            )
        )
