"""Strict aggregate-only contracts for offline retrieval evaluation."""

import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from erp_ai.capabilities.models import Code
from erp_ai.context.models import Identifier, PolicyCode
from erp_ai.knowledge import KnowledgeSourceType
from erp_ai.knowledge.ingestion.models import Digest
from erp_ai.knowledge.models import KnowledgeText, LanguageCode
from erp_ai.types import CanonicalSemVer


def _immutable_unique(value: Any) -> Any:
    value = tuple(value) if isinstance(value, list) else value
    if isinstance(value, tuple) and len(set(value)) != len(value):
        raise ValueError("duplicate evaluation values are forbidden")
    return value


class EvaluationLanguageSlice(str, Enum):
    ARABIC = "arabic"
    ENGLISH = "english"
    MIXED = "mixed"


class CandidateType(str, Enum):
    LEXICAL = "lexical"
    SEMANTIC = "semantic"


class EvaluationDisposition(str, Enum):
    PASSED = "passed"
    QUALITY_FAILURE = "quality_failure"
    SECURITY_FAILURE = "security_failure"
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"


class EvaluationAuthorizationScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    namespace: Code
    customer_environment_id: Identifier = Field(repr=False)
    enabled_modules: tuple[Code, ...] = Field(repr=False)
    permission_codes: tuple[PolicyCode, ...] = Field(repr=False)
    roles: tuple[Code, ...] = Field(repr=False)
    legal_entity_ids: tuple[Identifier, ...] = Field(repr=False)
    purpose: Code
    locale: LanguageCode
    effective_at: datetime

    @field_validator("customer_environment_id")
    @classmethod
    def synthetic_customer_only(cls, value: str) -> str:
        if not value.startswith("synthetic_"):
            raise ValueError("evaluation customer IDs must be explicitly synthetic")
        return value

    @field_validator(
        "enabled_modules", "permission_codes", "roles", "legal_entity_ids", mode="before"
    )
    @classmethod
    def immutable_scope(cls, value: Any) -> Any:
        return _immutable_unique(value)

    @field_validator("effective_at")
    @classmethod
    def aware_effective_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evaluation effective_at must be timezone-aware")
        return value


class GradedRelevantItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    result_id: Identifier
    identifier_type: Literal["citation", "chunk"]
    relevance_grade: int = Field(default=1, strict=True, ge=1, le=3)
    source_type: KnowledgeSourceType

    @field_validator("source_type", mode="before")
    @classmethod
    def parse_source_type(cls, value: Any) -> Any:
        return KnowledgeSourceType(value)


class RetrievalEvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    case_id: Identifier
    query: KnowledgeText = Field(repr=False)
    language_slice: EvaluationLanguageSlice
    authorization_scope: EvaluationAuthorizationScope = Field(repr=False)
    relevant_items: tuple[GradedRelevantItem, ...] = Field(repr=False)
    forbidden_result_ids: tuple[Identifier, ...] = Field(repr=False)
    expected_empty: bool
    evaluation_limit: int = Field(strict=True, ge=1, le=5)

    @field_validator("language_slice", mode="before")
    @classmethod
    def parse_language_slice(cls, value: Any) -> Any:
        return EvaluationLanguageSlice(value)

    @field_validator("relevant_items", "forbidden_result_ids", mode="before")
    @classmethod
    def immutable_values(cls, value: Any) -> Any:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_identifiers(self) -> "RetrievalEvaluationCase":
        relevant_ids = tuple(item.result_id for item in self.relevant_items)
        if len(set(relevant_ids)) != len(relevant_ids):
            raise ValueError("duplicate relevant result IDs are forbidden")
        if len(set(self.forbidden_result_ids)) != len(self.forbidden_result_ids):
            raise ValueError("duplicate forbidden result IDs are forbidden")
        if set(relevant_ids).intersection(self.forbidden_result_ids):
            raise ValueError("relevant and forbidden result IDs must not overlap")
        if self.expected_empty and self.relevant_items:
            raise ValueError("expected-empty cases cannot declare relevant results")
        if not self.expected_empty and not self.relevant_items:
            raise ValueError("non-empty cases require relevant results")
        return self


class RetrievalEvaluationSuite(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    contract_version: Literal[1]
    suite_id: Identifier
    suite_version: CanonicalSemVer
    corpus_generation_digest: Digest
    dataset_governance: Literal["approved_synthetic", "approved_sanitized"]
    cases: tuple[RetrievalEvaluationCase, ...] = Field(min_length=1, repr=False)

    @field_validator("cases", mode="before")
    @classmethod
    def immutable_cases(cls, value: Any) -> Any:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("cases")
    @classmethod
    def unique_cases(
        cls, value: tuple[RetrievalEvaluationCase, ...]
    ) -> tuple[RetrievalEvaluationCase, ...]:
        if len({case.case_id for case in value}) != len(value):
            raise ValueError("duplicate evaluation case IDs are forbidden")
        return value


class RetrievalCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    candidate_id: Code
    candidate_type: CandidateType
    embedding_profile_sha256: Digest | None = Field(default=None, repr=False)

    @field_validator("candidate_type", mode="before")
    @classmethod
    def parse_candidate_type(cls, value: Any) -> Any:
        return CandidateType(value)

    @model_validator(mode="after")
    def validate_profile_binding(self) -> "RetrievalCandidate":
        if (self.candidate_type is CandidateType.SEMANTIC) != (
            self.embedding_profile_sha256 is not None
        ):
            raise ValueError("only semantic candidates require an embedding profile digest")
        return self


class EvaluationThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    minimum_precision_at_k: float = Field(strict=True, ge=0, le=1)
    minimum_recall_at_k: float = Field(strict=True, ge=0, le=1)
    minimum_mrr_at_k: float = Field(strict=True, ge=0, le=1)
    minimum_ndcg_at_k: float = Field(strict=True, ge=0, le=1)
    minimum_expected_empty_accuracy: float = Field(strict=True, ge=0, le=1)


class EvaluationCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    case_id: Identifier
    precision_at_k: float = Field(strict=True, ge=0, le=1)
    recall_at_k: float = Field(strict=True, ge=0, le=1)
    mrr_at_k: float = Field(strict=True, ge=0, le=1)
    ndcg_at_k: float = Field(strict=True, ge=0, le=1)
    expected_empty_accuracy: float | None = Field(default=None, ge=0, le=1)
    retrieved_count: int = Field(strict=True, ge=0, le=5)
    forbidden_result_count: int = Field(strict=True, ge=0)
    authorization_leak_count: int = Field(strict=True, ge=0)
    cross_customer_result_count: int = Field(strict=True, ge=0)
    unexpected_provider_failure_count: int = Field(strict=True, ge=0, le=1)
    disposition: EvaluationDisposition


class RetrievalMetricSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    case_count: int = Field(strict=True, ge=0)
    precision_at_k: float = Field(strict=True, ge=0, le=1)
    recall_at_k: float = Field(strict=True, ge=0, le=1)
    mrr_at_k: float = Field(strict=True, ge=0, le=1)
    ndcg_at_k: float = Field(strict=True, ge=0, le=1)
    expected_empty_accuracy: float = Field(strict=True, ge=0, le=1)
    expected_empty_case_count: int = Field(strict=True, ge=0)
    retrieved_count: int = Field(strict=True, ge=0)
    unexpected_provider_failure_count: int = Field(strict=True, ge=0)
    forbidden_result_count: int = Field(strict=True, ge=0)
    authorization_leak_count: int = Field(strict=True, ge=0)
    authorization_leak_rate: float = Field(strict=True, ge=0, le=1)
    cross_customer_result_count: int = Field(strict=True, ge=0)


class EvaluationSliceResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    slice_name: Literal[
        "overall",
        "arabic",
        "english",
        "mixed",
        "product_documentation",
        "customer_policy",
    ]
    metrics: RetrievalMetricSummary


class RetrievalEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    suite_id: Identifier
    suite_version: CanonicalSemVer
    candidate_id: Code
    candidate_type: CandidateType
    evaluation_fingerprint: Digest
    disposition: EvaluationDisposition
    slices: tuple[EvaluationSliceResult, ...]
    failing_case_ids: tuple[Identifier, ...]

    @field_validator("slices", "failing_case_ids", mode="before")
    @classmethod
    def immutable_report_values(cls, value: Any) -> Any:
        return tuple(value) if isinstance(value, list) else value


def evaluation_fingerprint(
    suite: RetrievalEvaluationSuite,
    candidate: RetrievalCandidate,
    thresholds: EvaluationThresholds,
) -> str:
    payload = {
        "candidate": candidate.model_dump(mode="json"),
        "metric_configuration": thresholds.model_dump(mode="json"),
        "suite": suite.model_dump(mode="json"),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
