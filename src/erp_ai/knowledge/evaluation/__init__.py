"""Deterministic offline knowledge-retrieval evaluation."""

from erp_ai.knowledge.evaluation.calibration import (
    CalibrationCaseObservation,
    CalibrationScoredResult,
    SemanticThresholdSelection,
    select_semantic_threshold,
)
from erp_ai.knowledge.evaluation.models import (
    CandidateType,
    EvaluationAuthorizationScope,
    EvaluationCaseResult,
    EvaluationDisposition,
    EvaluationLanguageSlice,
    EvaluationSliceResult,
    EvaluationThresholds,
    GradedRelevantItem,
    RetrievalCandidate,
    RetrievalEvaluationCase,
    RetrievalEvaluationReport,
    RetrievalEvaluationSuite,
    RetrievalMetricSummary,
)
from erp_ai.knowledge.evaluation.service import RetrievalEvaluationService

__all__ = [
    "CalibrationCaseObservation",
    "CalibrationScoredResult",
    "CandidateType",
    "EvaluationAuthorizationScope",
    "EvaluationCaseResult",
    "EvaluationDisposition",
    "EvaluationLanguageSlice",
    "EvaluationSliceResult",
    "EvaluationThresholds",
    "GradedRelevantItem",
    "RetrievalCandidate",
    "RetrievalEvaluationCase",
    "RetrievalEvaluationReport",
    "RetrievalEvaluationService",
    "RetrievalEvaluationSuite",
    "RetrievalMetricSummary",
    "SemanticThresholdSelection",
    "select_semantic_threshold",
]
