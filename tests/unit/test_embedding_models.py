import math
import struct

import pytest
from pydantic import ValidationError

from erp_ai.capabilities import DataClassification
from erp_ai.knowledge.embeddings import (
    EmbeddingBatchRequest,
    EmbeddingBatchResult,
    EmbeddingInput,
    EmbeddingProfile,
    EmbeddingVector,
    PreparedEmbedding,
)


def profile(**overrides: object) -> EmbeddingProfile:
    values: dict[str, object] = {
        "contract_version": 1,
        "profile_id": "knowledge_v1",
        "provider_id": "test_provider",
        "model_id": "test-model",
        "model_revision": "revision-1",
        "dimensions": 3,
        "distance_metric": "cosine",
        "storage_representation": "float32",
        "input_normalization_version": 1,
        "allowed_data_classifications": ("internal", "public", "restricted"),
    }
    values.update(overrides)
    return EmbeddingProfile.model_validate(values)


def test_profile_is_strict_frozen_deterministic_and_server_safe() -> None:
    first = profile()
    second = profile(allowed_data_classifications=("restricted", "public", "internal"))
    assert first.profile_sha256 == second.profile_sha256
    assert first.allowed_data_classifications == (
        DataClassification.INTERNAL,
        DataClassification.PUBLIC,
        DataClassification.RESTRICTED,
    )
    assert "test-model" not in repr(first)
    with pytest.raises(ValidationError):
        first.dimensions = 4  # type: ignore[misc]
    with pytest.raises(ValidationError):
        profile(unknown=True)
    with pytest.raises(ValidationError):
        profile(distance_metric="euclidean")
    with pytest.raises(ValidationError):
        profile(storage_representation="float64")
    with pytest.raises(ValidationError):
        profile(allowed_data_classifications=("public", "public"))
    with pytest.raises(ValidationError):
        profile(allowed_data_classifications="public")


@pytest.mark.parametrize(
    "values",
    (
        (True, 1.0, 2.0),
        ("1", 1.0, 2.0),
        (math.nan, 1.0, 2.0),
        (math.inf, 1.0, 2.0),
        (-math.inf, 1.0, 2.0),
        (1e100, 1.0, 2.0),
        (0.0, -0.0, 0),
    ),
)
def test_vector_rejects_unsafe_values(values: tuple[object, ...]) -> None:
    with pytest.raises(ValidationError):
        EmbeddingVector(input_id="chunk_1", values=values)  # type: ignore[arg-type]


def test_vector_is_float32_immutable_and_hashes_canonical_bytes() -> None:
    vector = EmbeddingVector(input_id="chunk_1", values=(0.1, 2, -3.25))
    expected_values = tuple(
        float(struct.unpack("!f", struct.pack("!f", item))[0]) for item in (0.1, 2, -3.25)
    )
    assert vector.values == expected_values
    assert len(vector.vector_sha256) == 64
    assert (
        vector.vector_sha256
        == EmbeddingVector(input_id="other", values=expected_values).vector_sha256
    )
    assert "0.1" not in repr(vector)
    with pytest.raises(ValidationError):
        vector.values = (1.0,)  # type: ignore[misc]
    with pytest.raises(ValidationError):
        EmbeddingVector(input_id="chunk_1", values="1,2,3")  # type: ignore[arg-type]


def test_prepared_embedding_rejects_vector_hash_mismatch() -> None:
    with pytest.raises(ValidationError, match="hash mismatch"):
        PreparedEmbedding(
            chunk_id="chunk_1",
            content_sha256="a" * 64,
            values=(1.0, 2.0, 3.0),
            vector_sha256="b" * 64,
        )


def test_batch_contracts_reject_duplicates_and_hide_text_vectors() -> None:
    item = EmbeddingInput(
        input_id="chunk_1",
        text="restricted text",
        content_sha256="a" * 64,
        data_classification=DataClassification.RESTRICTED,
    )
    request = EmbeddingBatchRequest(profile=profile(), inputs=(item,))
    result = EmbeddingBatchResult(
        profile_sha256=request.profile.profile_sha256,
        vectors=(EmbeddingVector(input_id="chunk_1", values=(1.0, 2.0, 3.0)),),
    )
    assert "restricted text" not in repr(request)
    assert "1.0" not in repr(result)
    with pytest.raises(ValidationError):
        EmbeddingBatchRequest(profile=profile(), inputs=(item, item))
    with pytest.raises(ValidationError):
        EmbeddingBatchResult(
            profile_sha256=profile().profile_sha256,
            vectors=(result.vectors[0], result.vectors[0]),
        )
