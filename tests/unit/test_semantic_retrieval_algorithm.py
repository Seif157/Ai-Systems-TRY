import math
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from erp_ai.infrastructure.postgres.errors import KnowledgeStorageUnavailable
from erp_ai.infrastructure.postgres.semantic_retrieval import (
    _SEMANTIC_QUERY,
    SEMANTIC_MAXIMUM_RESULTS,
    SEMANTIC_NAMESPACE,
    SEMANTIC_QUERY_PARAMETER_ORDER,
    PostgresSemanticKnowledgeRetrievalProvider,
    _distance_to_score,
)


def row(
    *,
    chunk: str = "chunk_a",
    citation: str = "citation_a",
    content: str = "Synthetic content",
    distance: object = 0.5,
    score: object = 0.75,
) -> tuple[object, ...]:
    return (
        chunk,
        "document_a",
        citation,
        "hr",
        "customer_policy",
        "customer-a",
        ["hr_core"],
        ["hr.knowledge.read"],
        ["employee_self_service"],
        ["entity-a"],
        "internal",
        "en",
        "Synthetic title",
        "Synthetic section",
        "1.0.0",
        datetime(2026, 1, 1, tzinfo=UTC),
        None,
        content,
        score,
        distance,
    )


def test_algorithm_sql_and_parameters_are_frozen() -> None:
    assert SEMANTIC_NAMESPACE == "hr"
    assert SEMANTIC_MAXIMUM_RESULTS == 5
    assert _SEMANTIC_QUERY.count("%s") == len(SEMANTIC_QUERY_PARAMETER_ORDER) == 19
    assert "OPERATOR(public.<=>)" in _SEMANTIC_QUERY
    assert "ORDER BY cosine_distance ASC,chunk_id ASC" in _SEMANTIC_QUERY
    assert "g.status='active'" in _SEMANTIC_QUERY
    assert "s.status='ready'" in _SEMANTIC_QUERY
    assert "hnsw" not in _SEMANTIC_QUERY.lower()
    assert "ivfflat" not in _SEMANTIC_QUERY.lower()


@pytest.mark.parametrize(
    ("distance", "score"),
    ((0, 1.0), (0.5, 0.75), (1, 0.5), (2, 0.0), (Decimal("0.2"), 0.9)),
)
def test_distance_to_score_is_exact_and_bounded(distance: object, score: float) -> None:
    assert _distance_to_score(distance) == score


@pytest.mark.parametrize("distance", (True, "0", None, -0.1, 2.1, math.nan, math.inf, -math.inf))
def test_distance_rejects_malformed_nonfinite_and_out_of_range(distance: object) -> None:
    with pytest.raises(KnowledgeStorageUnavailable):
        _distance_to_score(distance)


def test_result_validation_preserves_identical_distance_tie_order() -> None:
    rows = [
        row(chunk="chunk_a", citation="citation_a"),
        row(chunk="chunk_b", citation="citation_b"),
    ]
    matches = PostgresSemanticKnowledgeRetrievalProvider._validated_matches(rows)
    assert tuple(item.chunk_id for item in matches) == ("chunk_a", "chunk_b")
    with pytest.raises(KnowledgeStorageUnavailable):
        PostgresSemanticKnowledgeRetrievalProvider._validated_matches(list(reversed(rows)))


def test_result_validation_rejects_duplicates_score_drift_and_context_overflow() -> None:
    with pytest.raises(KnowledgeStorageUnavailable):
        PostgresSemanticKnowledgeRetrievalProvider._validated_matches(
            [row(), row(citation="citation_b")]
        )
    with pytest.raises(KnowledgeStorageUnavailable):
        PostgresSemanticKnowledgeRetrievalProvider._validated_matches([row(), row(chunk="chunk_b")])
    with pytest.raises(KnowledgeStorageUnavailable):
        PostgresSemanticKnowledgeRetrievalProvider._validated_matches([row(score=0.5)])
    oversized_rows = [
        row(chunk=f"chunk_{index}", citation=f"citation_{index}", content="x" * 3000)
        for index in range(5)
    ]
    with pytest.raises(KnowledgeStorageUnavailable):
        PostgresSemanticKnowledgeRetrievalProvider._validated_matches(oversized_rows)


def test_result_validation_rejects_more_than_server_limit() -> None:
    rows = [row(chunk=f"chunk_{index}", citation=f"citation_{index}") for index in range(6)]
    with pytest.raises(KnowledgeStorageUnavailable):
        PostgresSemanticKnowledgeRetrievalProvider._validated_matches(rows)
