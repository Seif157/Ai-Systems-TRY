"""Deterministic calibration-only semantic abstention threshold selection."""

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from erp_ai.context.models import Identifier
from erp_ai.knowledge.evaluation.metrics import retrieval_metrics
from erp_ai.knowledge.evaluation.models import EvaluationThresholds, GradedRelevantItem


def _mean(quality: list[tuple[float, float, float, float]], index: int) -> float:
    return sum(item[index] for item in quality) / len(quality) if quality else 0.0


class CalibrationScoredResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    result_id: Identifier = Field(repr=False)
    relevance_score: float = Field(strict=True, ge=0, le=1, repr=False)
    authorization_violation: bool
    forbidden_result: bool
    cross_customer_result: bool


class CalibrationCaseObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    case_id: Identifier
    partition: Literal["calibration"]
    evaluation_limit: int = Field(strict=True, ge=1, le=5)
    expected_empty: bool
    relevant_items: tuple[GradedRelevantItem, ...] = Field(repr=False)
    scored_results: tuple[CalibrationScoredResult, ...] = Field(repr=False)

    @field_validator("relevant_items", "scored_results", mode="before")
    @classmethod
    def immutable_values(cls, value: Any) -> Any:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def unique_results(self) -> "CalibrationCaseObservation":
        if len({item.result_id for item in self.scored_results}) != len(self.scored_results):
            raise ValueError("duplicate calibration results are forbidden")
        return self


class SemanticThresholdSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    selected_threshold: float = Field(strict=True, ge=0, le=1, repr=False)
    candidate_thresholds: tuple[float, ...] = Field(repr=False)
    precision_at_k: float = Field(strict=True, ge=0, le=1)
    recall_at_k: float = Field(strict=True, ge=0, le=1)
    mrr_at_k: float = Field(strict=True, ge=0, le=1)
    ndcg_at_k: float = Field(strict=True, ge=0, le=1)
    expected_empty_accuracy: float = Field(strict=True, ge=1, le=1)
    approval: Literal["unapproved_test_only"] = "unapproved_test_only"


def select_semantic_threshold(
    observations: tuple[CalibrationCaseObservation, ...], gates: EvaluationThresholds
) -> SemanticThresholdSelection:
    if not observations:
        raise ValueError("calibration observations are required")
    if (
        min(
            gates.minimum_precision_at_k,
            gates.minimum_recall_at_k,
            gates.minimum_mrr_at_k,
            gates.minimum_ndcg_at_k,
            gates.minimum_expected_empty_accuracy,
        )
        <= 0
    ):
        raise ValueError("calibration quality gates must be nonzero")
    scores = {item.relevance_score for case in observations for item in case.scored_results}
    candidates = tuple(
        sorted(
            {0.0, 1.0, *scores, *(math.nextafter(score, 1.0) for score in scores if score < 1.0)}
        )
    )
    eligible: list[SemanticThresholdSelection] = []
    for threshold in candidates:
        quality: list[tuple[float, float, float, float]] = []
        empty: list[float] = []
        security = False
        for case in observations:
            retained = tuple(
                result for result in case.scored_results if result.relevance_score >= threshold
            )
            security |= any(
                result.authorization_violation
                or result.forbidden_result
                or result.cross_customer_result
                for result in retained
            )
            if case.expected_empty:
                empty.append(1.0 if not retained else 0.0)
            else:
                quality.append(
                    retrieval_metrics(
                        tuple(result.result_id for result in retained),
                        case.relevant_items,
                        case.evaluation_limit,
                    )
                )

        expected_empty = sum(empty) / len(empty) if empty else 1.0
        metrics = tuple(_mean(quality, index) for index in range(4))
        if (
            not security
            and expected_empty == 1.0
            and metrics[0] >= gates.minimum_precision_at_k
            and metrics[1] >= gates.minimum_recall_at_k
            and metrics[2] >= gates.minimum_mrr_at_k
            and metrics[3] >= gates.minimum_ndcg_at_k
            and expected_empty >= gates.minimum_expected_empty_accuracy
        ):
            eligible.append(
                SemanticThresholdSelection(
                    selected_threshold=threshold,
                    candidate_thresholds=candidates,
                    precision_at_k=metrics[0],
                    recall_at_k=metrics[1],
                    mrr_at_k=metrics[2],
                    ndcg_at_k=metrics[3],
                    expected_empty_accuracy=1.0,
                )
            )
    if not eligible:
        raise ValueError("no calibration threshold satisfies security and quality gates")
    return max(
        eligible,
        key=lambda item: (
            item.precision_at_k,
            item.recall_at_k,
            item.mrr_at_k,
            item.ndcg_at_k,
            item.selected_threshold,
        ),
    )
