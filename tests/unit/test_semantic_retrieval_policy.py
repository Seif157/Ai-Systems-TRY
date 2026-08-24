import pytest
from pydantic import ValidationError

from erp_ai.infrastructure.postgres import (
    PostgresSemanticKnowledgeRetrievalProvider,
    SemanticRetrievalPolicy,
)
from tests.unit.test_embedding_models import profile


def policy(**overrides: object) -> SemanticRetrievalPolicy:
    values: dict[str, object] = {
        "namespace": "hr",
        "embedding_profile_sha256": "a" * 64,
        "minimum_relevance_score": 0.72,
        "policy_version": "1.0.0",
    }
    values.update(overrides)
    return SemanticRetrievalPolicy.model_validate(values)


def test_policy_is_strict_frozen_private_and_deterministic() -> None:
    first = policy()
    assert first.policy_sha256 == policy().policy_sha256
    assert "0.72" not in repr(first)
    with pytest.raises(ValidationError):
        first.minimum_relevance_score = 0.0  # type: ignore[misc]
    with pytest.raises(ValidationError):
        policy(unknown=True)


@pytest.mark.parametrize("score", (-0.1, 1.1))
def test_policy_rejects_out_of_range_thresholds(score: float) -> None:
    with pytest.raises(ValidationError):
        policy(minimum_relevance_score=score)


def test_semantic_provider_requires_an_exact_profile_bound_policy() -> None:
    embedding_profile = profile()
    valid = policy(embedding_profile_sha256=embedding_profile.profile_sha256)
    provider = PostgresSemanticKnowledgeRetrievalProvider(
        object(),
        "customer-a",
        embedding_profile,
        object(),
        valid,  # type: ignore[arg-type]
    )
    assert provider is not None
    with pytest.raises(TypeError):
        PostgresSemanticKnowledgeRetrievalProvider(  # type: ignore[call-arg]
            object(),
            object(),
            embedding_profile,
            object(),  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="policy is incompatible"):
        PostgresSemanticKnowledgeRetrievalProvider(
            object(),  # type: ignore[arg-type]
            "customer-a",
            embedding_profile,
            object(),  # type: ignore[arg-type]
            policy(embedding_profile_sha256="b" * 64),
        )
