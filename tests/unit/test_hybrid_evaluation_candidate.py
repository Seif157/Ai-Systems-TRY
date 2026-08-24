import pytest
from pydantic import ValidationError

from erp_ai.knowledge.evaluation import RetrievalCandidate


def candidate() -> RetrievalCandidate:
    return RetrievalCandidate(
        candidate_id="hybrid",
        candidate_type="hybrid",
        embedding_profile_sha256="a" * 64,
        semantic_policy_sha256="b" * 64,
        embedding_resource_policy_sha256="c" * 64,
        embedding_runtime_identity_sha256="d" * 64,
        hybrid_policy_sha256="e" * 64,
        threshold_approval_status="unapproved_test_only",
    )


def test_hybrid_candidate_binds_provenance_and_fails_without_approval() -> None:
    item = candidate()
    assert item.candidate_type.value == "hybrid" and "embedding" not in repr(item)
    with pytest.raises(ValidationError):
        RetrievalCandidate.model_validate(item.model_dump(exclude={"threshold_approval_status"}))
    with pytest.raises(ValidationError):
        RetrievalCandidate.model_validate(item.model_dump(exclude={"hybrid_policy_sha256"}))
    with pytest.raises(ValidationError):
        RetrievalCandidate(
            candidate_id="lexical",
            candidate_type="lexical",
            threshold_approval_status="unapproved_test_only",
        )


def test_hybrid_fingerprint_input_changes_with_policy() -> None:
    assert candidate() != candidate().model_copy(update={"hybrid_policy_sha256": "f" * 64})
