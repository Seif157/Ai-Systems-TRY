import asyncio
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from erp_ai.infrastructure.postgres import (
    HybridRetrievalPolicy,
    PostgresHybridKnowledgeRetrievalProvider,
    reciprocal_rank_fusion,
)
from erp_ai.infrastructure.postgres.errors import KnowledgeStorageUnavailable
from erp_ai.infrastructure.postgres.hybrid_retrieval import (
    _decode_lexical_row,
    _decode_semantic_row,
)
from erp_ai.knowledge import KnowledgeMatch, KnowledgeRetrievalRequest
from tests.unit.test_embedding_models import profile


def policy(**overrides: object) -> HybridRetrievalPolicy:
    values: dict[str, object] = {
        "policy_version": "1.0.0",
        "namespace": "hr",
        "embedding_profile_sha256": "a" * 64,
        "semantic_threshold": 0.8170998503506278,
        "threshold_approval_status": "unapproved_test_only",
        "generation_digest": "b" * 64,
        "embedding_resource_policy_sha256": "c" * 64,
        "embedding_runtime_identity_sha256": "d" * 64,
    }
    values.update(overrides)
    return HybridRetrievalPolicy.model_validate(values)


def match(chunk_id: str, *, title: str | None = None) -> KnowledgeMatch:
    return KnowledgeMatch(
        chunk_id=chunk_id,
        document_id=f"doc_{chunk_id}",
        citation_id=f"cite_{chunk_id}",
        namespace="hr",
        source_type="product_documentation",
        customer_environment_id=None,
        required_modules_all=("hr_core",),
        required_permissions_all=("hr.knowledge.read",),
        allowed_purposes=("employee_self_service",),
        legal_entity_ids=(),
        data_classification="internal",
        language="en",
        title=title or chunk_id,
        section="Policy",
        document_version="1.0.0",
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
        content="Approved policy excerpt.",
        relevance_score=0.5,
    )


def test_policy_is_strict_frozen_bounded_and_deterministic() -> None:
    item = policy()
    assert item.policy_sha256 == policy().policy_sha256 and item.final_result_limit == 5
    with pytest.raises(ValidationError):
        item.final_result_limit = 2  # type: ignore[misc]
    with pytest.raises(ValidationError):
        policy(final_result_limit=6)
    with pytest.raises(ValidationError):
        policy(unknown=True)
    with pytest.raises(ValidationError):
        policy(threshold_approval_status="approved")


def test_rrf_one_based_both_paths_and_chunk_tie_breaking() -> None:
    a, b, c = match("a"), match("b"), match("c")
    assert tuple(x.chunk_id for x in reciprocal_rank_fusion((a, b), (b, c), policy(), 5)) == (
        "b",
        "a",
        "c",
    )
    assert tuple(x.chunk_id for x in reciprocal_rank_fusion((a, b), (b, a), policy(), 5)) == (
        "a",
        "b",
    )


def test_equal_weight_rrf_is_independent_of_caller_path_order() -> None:
    a, b, c = match("a"), match("b"), match("c")
    first = reciprocal_rank_fusion((a, b), (b, c), policy(), 5)
    swapped = reciprocal_rank_fusion((b, c), (a, b), policy(), 5)
    assert tuple(item.chunk_id for item in first) == tuple(item.chunk_id for item in swapped)


def test_rrf_empty_paths_limits_duplicates_and_metadata_mismatch() -> None:
    a = match("a")
    assert reciprocal_rank_fusion((), (a,), policy(), 1) == (a,)
    assert reciprocal_rank_fusion((), (), policy(), 5) == ()
    with pytest.raises(ValueError, match="duplicate"):
        reciprocal_rank_fusion((a, a), (), policy(), 5)
    with pytest.raises(ValueError, match="metadata mismatch"):
        reciprocal_rank_fusion((a,), (match("a", title="Changed"),), policy(), 5)
    with pytest.raises(ValueError, match="limit"):
        reciprocal_rank_fusion((a, match("b")), (), policy(lexical_candidate_limit=1), 1)


def test_public_match_contains_no_hybrid_scoring_or_provenance() -> None:
    result = reciprocal_rank_fusion((match("a"),), (), policy(), 5)[0].model_dump()
    assert not {"hybrid_score", "embedding_profile_sha256", "generation_digest"} & result.keys()


def projected_row(item: KnowledgeMatch) -> tuple[object, ...]:
    return (
        item.chunk_id,
        item.document_id,
        item.citation_id,
        item.namespace,
        item.source_type.value,
        item.customer_environment_id,
        list(item.required_modules_all),
        list(item.required_permissions_all),
        list(item.allowed_purposes),
        list(item.legal_entity_ids),
        item.data_classification.value,
        item.language,
        item.title,
        item.section,
        item.document_version,
        item.effective_from,
        item.effective_to,
        item.content,
    )


def test_exact_lexical_and_semantic_row_decoders_are_separate() -> None:
    expected = match("exact")
    lexical_row = (*projected_row(expected), 0.5)
    semantic_row = (*projected_row(expected), 0.5, 1.0)

    assert _decode_lexical_row(lexical_row) == expected
    assert _decode_semantic_row(semantic_row) == expected
    with pytest.raises(KnowledgeStorageUnavailable, match="unavailable"):
        _decode_lexical_row(semantic_row)
    with pytest.raises(KnowledgeStorageUnavailable, match="unavailable"):
        _decode_semantic_row(lexical_row)


@pytest.mark.parametrize("invalid_score", [True, "0.5", float("nan"), -0.1, 1.1])
def test_lexical_row_score_fails_closed_without_payload_leakage(invalid_score: object) -> None:
    marker = "restricted-content-marker"
    row = (*projected_row(match("malformed"))[:-1], marker, invalid_score)

    with pytest.raises(KnowledgeStorageUnavailable, match="unavailable") as error:
        _decode_lexical_row(row)

    assert marker not in str(error.value)


def test_semantic_failure_fails_complete_request_before_lexical_access() -> None:
    embedding_profile = profile()

    class FailingEmbeddingProvider:
        async def embed(self, request: object) -> object:
            raise RuntimeError("provider detail")

    class RouterMustNotBeUsed:
        def pool(self, *args: object) -> object:
            raise AssertionError("lexical fallback/database access is forbidden")

    provider = PostgresHybridKnowledgeRetrievalProvider(
        RouterMustNotBeUsed(),  # type: ignore[arg-type]
        "customer_a",
        embedding_profile,
        FailingEmbeddingProvider(),  # type: ignore[arg-type]
        policy(embedding_profile_sha256=embedding_profile.profile_sha256),
    )
    request = KnowledgeRetrievalRequest(
        namespace="hr",
        query="annual leave",
        maximum_results=5,
        customer_environment_id="customer_a",
        enabled_modules=("hr_core",),
        permission_codes=("hr.knowledge.read",),
        roles=("employee",),
        authorized_legal_entity_ids=("entity_a",),
        purpose="employee_self_service",
        locale="en",
        effective_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    with pytest.raises(KnowledgeStorageUnavailable, match="unavailable") as error:
        asyncio.run(provider.retrieve(request))
    assert "provider detail" not in str(error.value)
