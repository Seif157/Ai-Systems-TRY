from dataclasses import FrozenInstanceError

import pytest
from pydantic import ValidationError

from erp_ai.infrastructure.tei import QWEN3_PINNED_RUNTIME_IDENTITY
from erp_ai.knowledge.evaluation import (
    EvaluationThresholds,
    RetrievalCandidate,
    RetrievalEvaluationService,
)
from erp_ai.knowledge.evaluation.models import evaluation_fingerprint
from tests.support.retrieval_evaluation import (
    authorization_scope,
    evaluation_case,
    relevant,
    suite,
)


def thresholds() -> EvaluationThresholds:
    return EvaluationThresholds(
        minimum_precision_at_k=0.2,
        minimum_recall_at_k=0.5,
        minimum_mrr_at_k=0.5,
        minimum_ndcg_at_k=0.5,
        minimum_expected_empty_accuracy=1.0,
    )


def test_suite_is_strict_frozen_repr_safe_and_synthetic_only() -> None:
    value = suite()
    assert "annual leave" not in repr(value)
    assert isinstance(value.cases, tuple)
    with pytest.raises(ValidationError):
        value.cases = ()  # type: ignore[misc]
    with pytest.raises(ValidationError):
        authorization_scope(customer_environment_id="production_customer")
    with pytest.raises(ValidationError):
        authorization_scope(effective_at=authorization_scope().effective_at.replace(tzinfo=None))
    with pytest.raises(ValidationError):
        authorization_scope(enabled_modules=("leave", "leave"))


def test_cases_reject_duplicates_overlap_unknown_fields_and_invalid_empty_behavior() -> None:
    with pytest.raises(ValidationError, match="duplicate relevant"):
        evaluation_case(relevant_items=(relevant(), relevant()))
    with pytest.raises(ValidationError, match="duplicate forbidden"):
        evaluation_case(forbidden_result_ids=("same", "same"))
    with pytest.raises(ValidationError, match="overlap"):
        evaluation_case(forbidden_result_ids=("cite_relevant",))
    with pytest.raises(ValidationError):
        evaluation_case(expected_empty=True)
    with pytest.raises(ValidationError):
        evaluation_case(relevant_items=())
    with pytest.raises(ValidationError):
        evaluation_case(evaluation_limit=6)
    with pytest.raises(ValidationError):
        evaluation_case(unknown=True)
    with pytest.raises(ValidationError, match="duplicate evaluation case"):
        suite(evaluation_case(), evaluation_case())


def test_candidate_profile_binding_and_thresholds_are_explicit() -> None:
    lexical = RetrievalCandidate(candidate_id="lexical", candidate_type="lexical")
    semantic = RetrievalCandidate(
        candidate_id="semantic",
        candidate_type="semantic",
        embedding_profile_sha256="b" * 64,
        semantic_policy_sha256="c" * 64,
        embedding_resource_policy_sha256="d" * 64,
        embedding_runtime_identity_sha256="e" * 64,
    )
    assert lexical.embedding_profile_sha256 is None
    assert semantic.embedding_profile_sha256 == "b" * 64
    with pytest.raises(ValidationError):
        RetrievalCandidate(candidate_id="semantic", candidate_type="semantic")
    with pytest.raises(ValidationError):
        RetrievalCandidate(
            candidate_id="lexical",
            candidate_type="lexical",
            embedding_profile_sha256="b" * 64,
            semantic_policy_sha256="c" * 64,
            embedding_resource_policy_sha256="d" * 64,
            embedding_runtime_identity_sha256="e" * 64,
        )
    with pytest.raises(ValidationError):
        RetrievalCandidate(
            candidate_id="lexical",
            candidate_type="lexical",
            semantic_policy_sha256="c" * 64,
        )
    with pytest.raises(ValidationError):
        RetrievalCandidate(
            candidate_id="lexical",
            candidate_type="lexical",
            embedding_resource_policy_sha256="d" * 64,
            embedding_runtime_identity_sha256="e" * 64,
        )
    with pytest.raises(ValidationError):
        RetrievalCandidate(
            candidate_id="lexical",
            candidate_type="lexical",
            embedding_runtime_identity_sha256="e" * 64,
        )
    with pytest.raises(ValidationError):
        EvaluationThresholds.model_validate({})


def test_fingerprint_is_deterministic_and_binds_candidate_dataset_thresholds_and_limits() -> None:
    candidate = RetrievalCandidate(candidate_id="lexical", candidate_type="lexical")
    first = evaluation_fingerprint(suite(), candidate, thresholds())
    assert first == evaluation_fingerprint(suite(), candidate, thresholds())
    assert first != evaluation_fingerprint(
        suite(evaluation_case(evaluation_limit=2)), candidate, thresholds()
    )
    assert first != evaluation_fingerprint(
        suite(),
        RetrievalCandidate(
            candidate_id="semantic",
            candidate_type="semantic",
            embedding_profile_sha256="b" * 64,
            semantic_policy_sha256="c" * 64,
            embedding_resource_policy_sha256="d" * 64,
            embedding_runtime_identity_sha256="e" * 64,
        ),
        thresholds(),
    )
    observed_changed = QWEN3_PINNED_RUNTIME_IDENTITY.model_copy(
        update={"observed_max_batch_requests": 5}
    )
    semantic = RetrievalCandidate(
        candidate_id="semantic",
        candidate_type="semantic",
        embedding_profile_sha256="b" * 64,
        semantic_policy_sha256="c" * 64,
        embedding_resource_policy_sha256="d" * 64,
        embedding_runtime_identity_sha256=QWEN3_PINNED_RUNTIME_IDENTITY.identity_sha256,
    )
    changed = semantic.model_copy(
        update={"embedding_runtime_identity_sha256": observed_changed.identity_sha256}
    )
    assert observed_changed.identity_sha256 != QWEN3_PINNED_RUNTIME_IDENTITY.identity_sha256
    assert evaluation_fingerprint(suite(), semantic, thresholds()) != evaluation_fingerprint(
        suite(), changed, thresholds()
    )
    assert first != evaluation_fingerprint(
        suite(),
        candidate,
        thresholds().model_copy(update={"minimum_recall_at_k": 0.75}),
    )


def test_service_is_immutable() -> None:
    service = RetrievalEvaluationService({})
    with pytest.raises(FrozenInstanceError):
        service._providers = {}  # type: ignore[misc]
