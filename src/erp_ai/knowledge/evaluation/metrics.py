"""Pure deterministic retrieval metrics with explicit zero-denominator behavior."""

import math

from erp_ai.knowledge.evaluation.models import GradedRelevantItem


def retrieval_metrics(
    retrieved_ids: tuple[str, ...], relevant: tuple[GradedRelevantItem, ...], limit: int
) -> tuple[float, float, float, float]:
    grades = {item.result_id: item.relevance_grade for item in relevant}
    observed_grades = tuple(grades.get(result_id, 0) for result_id in retrieved_ids[:limit])
    relevant_retrieved = sum(grade > 0 for grade in observed_grades)
    precision = relevant_retrieved / limit
    recall = relevant_retrieved / len(grades) if grades else 0.0
    first = next((index for index, grade in enumerate(observed_grades, start=1) if grade), None)
    mrr = 0.0 if first is None else 1.0 / first
    dcg = sum(
        ((2**grade) - 1) / math.log2(index + 1)
        for index, grade in enumerate(observed_grades, start=1)
        if grade
    )
    ideal = tuple(sorted(grades.values(), reverse=True))[:limit]
    ideal_dcg = sum(
        ((2**grade) - 1) / math.log2(index + 1) for index, grade in enumerate(ideal, start=1)
    )
    ndcg = dcg / ideal_dcg if ideal_dcg else 0.0
    return precision, recall, mrr, ndcg
