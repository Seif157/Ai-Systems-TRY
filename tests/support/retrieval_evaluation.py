"""Approved synthetic-only retrieval evaluation fixtures."""

from datetime import UTC, datetime, timedelta

from erp_ai.capabilities import DataClassification
from erp_ai.knowledge import KnowledgeMatch, KnowledgeSourceType
from erp_ai.knowledge.evaluation import (
    EvaluationAuthorizationScope,
    GradedRelevantItem,
    RetrievalEvaluationCase,
    RetrievalEvaluationSuite,
)

NOW = datetime(2026, 8, 24, tzinfo=UTC)


def authorization_scope(**overrides: object) -> EvaluationAuthorizationScope:
    values: dict[str, object] = {
        "namespace": "hr",
        "customer_environment_id": "synthetic_customer_a",
        "enabled_modules": ("hr_core", "leave"),
        "permission_codes": ("hr.knowledge.read",),
        "roles": ("employee",),
        "legal_entity_ids": ("synthetic_legal_entity_a",),
        "purpose": "employee_self_service",
        "locale": "en",
        "effective_at": NOW,
    }
    values.update(overrides)
    return EvaluationAuthorizationScope.model_validate(values)


def relevant(
    result_id: str = "cite_relevant",
    *,
    grade: int = 3,
    source_type: KnowledgeSourceType = KnowledgeSourceType.PRODUCT_DOCUMENTATION,
) -> GradedRelevantItem:
    return GradedRelevantItem(
        result_id=result_id,
        identifier_type="citation",
        relevance_grade=grade,
        source_type=source_type,
    )


def evaluation_case(**overrides: object) -> RetrievalEvaluationCase:
    values: dict[str, object] = {
        "case_id": "case_english_policy",
        "query": "synthetic annual leave policy",
        "language_slice": "english",
        "authorization_scope": authorization_scope(),
        "relevant_items": (relevant(),),
        "forbidden_result_ids": ("cite_forbidden",),
        "expected_empty": False,
        "evaluation_limit": 3,
    }
    values.update(overrides)
    return RetrievalEvaluationCase.model_validate(values)


def suite(*cases: RetrievalEvaluationCase) -> RetrievalEvaluationSuite:
    return RetrievalEvaluationSuite(
        contract_version=1,
        suite_id="synthetic_hr_retrieval",
        suite_version="1.0.0",
        corpus_generation_digest="a" * 64,
        dataset_governance="approved_synthetic",
        cases=cases or (evaluation_case(),),
    )


def match(**overrides: object) -> KnowledgeMatch:
    values: dict[str, object] = {
        "chunk_id": "chunk_relevant",
        "document_id": "document_synthetic",
        "citation_id": "cite_relevant",
        "namespace": "hr",
        "source_type": KnowledgeSourceType.PRODUCT_DOCUMENTATION,
        "customer_environment_id": None,
        "required_modules_all": ("hr_core",),
        "required_permissions_all": ("hr.knowledge.read",),
        "allowed_purposes": ("employee_self_service",),
        "legal_entity_ids": (),
        "data_classification": DataClassification.INTERNAL,
        "language": "en",
        "title": "Synthetic policy",
        "section": "Synthetic leave",
        "document_version": "1.2.3",
        "effective_from": NOW - timedelta(days=1),
        "effective_to": None,
        "content": "Approved synthetic policy content.",
        "relevance_score": 0.9,
    }
    values.update(overrides)
    return KnowledgeMatch.model_validate(values)
