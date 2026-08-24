import pytest
from pydantic import ValidationError

from erp_ai.knowledge.evaluation import (
    CalibrationCaseObservation,
    CalibrationScoredResult,
    EvaluationThresholds,
    select_semantic_threshold,
)
from tests.support.retrieval_evaluation import relevant


def scored(identifier: str, score: float, **flags: bool) -> CalibrationScoredResult:
    return CalibrationScoredResult(
        result_id=identifier,
        relevance_score=score,
        authorization_violation=flags.get("authorization_violation", False),
        forbidden_result=flags.get("forbidden_result", False),
        cross_customer_result=flags.get("cross_customer_result", False),
    )


def observation(
    case_id: str,
    results: tuple[CalibrationScoredResult, ...],
    *,
    expected_empty: bool = False,
) -> CalibrationCaseObservation:
    return CalibrationCaseObservation(
        case_id=case_id,
        partition="calibration",
        evaluation_limit=1,
        expected_empty=expected_empty,
        relevant_items=() if expected_empty else (relevant("relevant"),),
        scored_results=results,
    )


def gates(**overrides: float) -> EvaluationThresholds:
    values = {
        "minimum_precision_at_k": 0.5,
        "minimum_recall_at_k": 0.5,
        "minimum_mrr_at_k": 0.5,
        "minimum_ndcg_at_k": 0.5,
        "minimum_expected_empty_accuracy": 1.0,
    }
    values.update(overrides)
    return EvaluationThresholds.model_validate(values)


def test_calibration_selects_highest_quality_then_highest_threshold_without_holdout() -> None:
    selected = select_semantic_threshold(
        (
            observation("answer", (scored("relevant", 0.8),)),
            observation("empty", (scored("irrelevant", 0.4),), expected_empty=True),
        ),
        gates(),
    )
    assert selected.selected_threshold == 0.8
    assert selected.expected_empty_accuracy == 1.0
    assert selected.approval == "unapproved_test_only"
    assert 0.4 in selected.candidate_thresholds
    assert selected.candidate_thresholds == tuple(sorted(selected.candidate_thresholds))


def test_security_is_unconditional_and_no_eligible_threshold_fails() -> None:
    with pytest.raises(ValueError, match="no calibration threshold"):
        select_semantic_threshold(
            (observation("answer", (scored("relevant", 1.0, forbidden_result=True),)),),
            gates(),
        )


def test_calibration_models_and_inputs_fail_closed() -> None:
    with pytest.raises(ValueError, match="observations are required"):
        select_semantic_threshold((), gates())
    with pytest.raises(ValueError, match="must be nonzero"):
        select_semantic_threshold(
            (observation("answer", (scored("relevant", 0.8),)),),
            gates(minimum_recall_at_k=0.0),
        )
    duplicate = scored("same", 0.5)
    with pytest.raises(ValidationError, match="duplicate calibration"):
        observation("duplicate", (duplicate, duplicate))
    with pytest.raises(ValidationError):
        CalibrationCaseObservation(
            **{
                **observation("answer", (scored("relevant", 0.8),)).model_dump(),
                "partition": "holdout",
            }
        )


def test_empty_quality_slice_and_missing_empty_slice_have_explicit_behavior() -> None:
    with pytest.raises(ValueError, match="no calibration threshold"):
        select_semantic_threshold(
            (observation("empty", (), expected_empty=True),),
            gates(),
        )
    selected = select_semantic_threshold(
        (observation("answer", (scored("relevant", 0.7),)),), gates()
    )
    assert selected.expected_empty_accuracy == 1.0
