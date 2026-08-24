from erp_ai.knowledge.evaluation import (
    EvaluationAuthorizationScope,
    EvaluationCaseResult,
    RetrievalEvaluationCase,
    RetrievalEvaluationReport,
    RetrievalEvaluationSuite,
)


def test_dataset_contract_excludes_production_payload_and_embedding_fields() -> None:
    forbidden = {
        "employee_id",
        "payroll",
        "attendance",
        "credentials",
        "trusted_request_context",
        "database_rows",
        "embeddings",
        "vectors",
        "excerpts",
        "titles",
        "schema_documents",
    }
    for contract in (
        RetrievalEvaluationSuite,
        RetrievalEvaluationCase,
        EvaluationAuthorizationScope,
    ):
        assert forbidden.isdisjoint(contract.model_fields)


def test_safe_reports_are_aggregate_only() -> None:
    forbidden = {
        "query",
        "content",
        "excerpt",
        "title",
        "vector",
        "provider_exception",
        "matches",
        "citations",
        "authorization_scope",
    }
    assert forbidden.isdisjoint(RetrievalEvaluationReport.model_fields)
    assert forbidden.isdisjoint(EvaluationCaseResult.model_fields)
    assert "failing_case_ids" in RetrievalEvaluationReport.model_fields
