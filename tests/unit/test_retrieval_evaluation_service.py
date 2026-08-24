import asyncio

import pytest

from erp_ai.knowledge import KnowledgeRetrievalRequest
from erp_ai.knowledge.evaluation import (
    EvaluationDisposition,
    EvaluationThresholds,
    RetrievalCandidate,
    RetrievalEvaluationService,
)
from tests.support.retrieval_evaluation import evaluation_case, match, relevant, suite


class ScriptedProvider:
    def __init__(
        self, results: dict[str, tuple[object, ...] | Exception], calls: list[str]
    ) -> None:
        self.results = results
        self.calls = calls

    async def retrieve(self, request: KnowledgeRetrievalRequest):
        self.calls.append(request.query)
        result = self.results[request.query]
        if isinstance(result, Exception):
            raise result
        return result


def thresholds(**overrides: float) -> EvaluationThresholds:
    values = {
        "minimum_precision_at_k": 0.3,
        "minimum_recall_at_k": 1.0,
        "minimum_mrr_at_k": 1.0,
        "minimum_ndcg_at_k": 1.0,
        "minimum_expected_empty_accuracy": 1.0,
    }
    values.update(overrides)
    return EvaluationThresholds.model_validate(values)


def candidate(name: str = "lexical") -> RetrievalCandidate:
    return RetrievalCandidate(candidate_id=name, candidate_type="lexical")


def test_service_preserves_case_candidate_and_provider_order_without_payloads() -> None:
    calls: list[str] = []
    first = evaluation_case()
    second = evaluation_case(
        case_id="case_empty",
        query="synthetic empty",
        language_slice="arabic",
        relevant_items=(),
        forbidden_result_ids=(),
        expected_empty=True,
    )
    providers = {
        "lexical": ScriptedProvider({first.query: (match(),), second.query: ()}, calls),
        "lexical_two": ScriptedProvider({first.query: (match(),), second.query: ()}, calls),
    }
    reports = asyncio.run(
        RetrievalEvaluationService(providers).evaluate(
            suite(first, second), (candidate(), candidate("lexical_two")), thresholds()
        )
    )
    assert calls == [first.query, second.query, first.query, second.query]
    assert all(report.disposition is EvaluationDisposition.PASSED for report in reports)
    assert tuple(item.slice_name for item in reports[0].slices) == (
        "overall",
        "arabic",
        "english",
        "mixed",
        "product_documentation",
        "customer_policy",
    )
    serialized = reports[0].model_dump_json()
    assert "synthetic annual" not in serialized
    assert "Approved synthetic" not in serialized
    assert "chunk_relevant" not in serialized


def test_security_gates_override_quality_and_count_forbidden_and_scope_leaks() -> None:
    case = evaluation_case()
    leaked = match(
        citation_id="cite_forbidden",
        customer_environment_id="synthetic_customer_b",
        required_modules_all=("payroll",),
    )
    report = asyncio.run(
        RetrievalEvaluationService(
            {"lexical": ScriptedProvider({case.query: (leaked,)}, [])}
        ).evaluate(
            suite(case),
            (candidate(),),
            thresholds(
                minimum_precision_at_k=0.0,
                minimum_recall_at_k=0.0,
                minimum_mrr_at_k=0.0,
                minimum_ndcg_at_k=0.0,
            ),
        )
    )[0]
    overall = report.slices[0].metrics
    assert report.disposition is EvaluationDisposition.SECURITY_FAILURE
    assert overall.forbidden_result_count == 1
    assert overall.authorization_leak_count == 1
    assert overall.cross_customer_result_count == 1
    assert overall.authorization_leak_rate == 1.0


@pytest.mark.parametrize(
    "overrides",
    (
        {"required_permissions_all": ("hr.secret.read",)},
        {"allowed_purposes": ("manager_assistance",)},
        {"legal_entity_ids": ("synthetic_legal_entity_b",)},
        {"data_classification": "highly_restricted"},
        {"effective_from": evaluation_case().authorization_scope.effective_at.replace(year=2027)},
    ),
)
def test_every_authorization_scope_violation_is_a_security_failure(
    overrides: dict[str, object],
) -> None:
    case = evaluation_case()
    report = asyncio.run(
        RetrievalEvaluationService(
            {"lexical": ScriptedProvider({case.query: (match(**overrides),)}, [])}
        ).evaluate(suite(case), (candidate(),), thresholds())
    )[0]
    assert report.disposition is EvaluationDisposition.SECURITY_FAILURE


def test_provider_failures_and_invalid_duplicate_or_excess_results_fail() -> None:
    case = evaluation_case()
    bad_results = (
        RuntimeError("provider secret"),
        (object(),),
        (match(), match()),
        tuple(match(chunk_id=f"chunk_{index}", citation_id=f"cite_{index}") for index in range(4)),
    )
    for result in bad_results:
        report = asyncio.run(
            RetrievalEvaluationService(
                {"lexical": ScriptedProvider({case.query: result}, [])}
            ).evaluate(suite(case), (candidate(),), thresholds())
        )[0]
        assert report.disposition is EvaluationDisposition.INFRASTRUCTURE_FAILURE
        assert report.slices[0].metrics.unexpected_provider_failure_count == 1
        assert "provider secret" not in report.model_dump_json()


def test_quality_failure_missing_provider_duplicate_candidates_and_cancellation() -> None:
    case = evaluation_case(relevant_items=(relevant("missing"),))
    service = RetrievalEvaluationService({"lexical": ScriptedProvider({case.query: ()}, [])})
    report = asyncio.run(service.evaluate(suite(case), (candidate(),), thresholds()))[0]
    assert report.disposition is EvaluationDisposition.QUALITY_FAILURE
    assert report.failing_case_ids == (case.case_id,)
    missing = asyncio.run(
        RetrievalEvaluationService({}).evaluate(suite(case), (candidate(),), thresholds())
    )[0]
    assert missing.disposition is EvaluationDisposition.INFRASTRUCTURE_FAILURE
    with pytest.raises(ValueError, match="duplicate retrieval candidate"):
        asyncio.run(service.evaluate(suite(case), (candidate(), candidate()), thresholds()))

    class CancelledProvider:
        async def retrieve(self, request: KnowledgeRetrievalRequest):
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            RetrievalEvaluationService({"lexical": CancelledProvider()}).evaluate(
                suite(case), (candidate(),), thresholds()
            )
        )
