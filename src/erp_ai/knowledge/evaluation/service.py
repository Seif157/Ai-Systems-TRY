"""Sequential fail-closed evaluation over injected production retrieval providers."""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from erp_ai.capabilities import DataClassification
from erp_ai.knowledge import KnowledgeMatch, KnowledgeRetrievalProvider, KnowledgeRetrievalRequest
from erp_ai.knowledge.evaluation.metrics import retrieval_metrics
from erp_ai.knowledge.evaluation.models import (
    EvaluationAuthorizationScope,
    EvaluationCaseResult,
    EvaluationDisposition,
    EvaluationSliceResult,
    EvaluationThresholds,
    RetrievalCandidate,
    RetrievalEvaluationCase,
    RetrievalEvaluationReport,
    RetrievalEvaluationSuite,
    RetrievalMetricSummary,
    evaluation_fingerprint,
)

_CLASSIFICATION_RANK = {
    DataClassification.PUBLIC: 0,
    DataClassification.INTERNAL: 1,
    DataClassification.RESTRICTED: 2,
    DataClassification.HIGHLY_RESTRICTED: 3,
}


@dataclass(frozen=True, slots=True)
class RetrievalEvaluationService:
    _providers: Mapping[str, KnowledgeRetrievalProvider]

    def __post_init__(self) -> None:
        object.__setattr__(self, "_providers", MappingProxyType(dict(self._providers)))

    async def evaluate(
        self,
        suite: RetrievalEvaluationSuite,
        candidates: tuple[RetrievalCandidate, ...],
        thresholds: EvaluationThresholds,
    ) -> tuple[RetrievalEvaluationReport, ...]:
        if len({candidate.candidate_id for candidate in candidates}) != len(candidates):
            raise ValueError("duplicate retrieval candidate IDs are forbidden")
        reports = []
        for candidate in candidates:
            provider = self._providers.get(candidate.candidate_id)
            if provider is None:
                results = tuple(self._provider_failure(case) for case in suite.cases)
            else:
                case_results = []
                for case in suite.cases:
                    case_results.append(await self._evaluate_case(provider, case))
                results = tuple(case_results)
            reports.append(self._report(suite, candidate, thresholds, results))
        return tuple(reports)

    async def _evaluate_case(
        self, provider: KnowledgeRetrievalProvider, case: RetrievalEvaluationCase
    ) -> EvaluationCaseResult:
        scope = case.authorization_scope
        request = KnowledgeRetrievalRequest(
            namespace=scope.namespace,
            query=case.query,
            maximum_results=case.evaluation_limit,
            customer_environment_id=scope.customer_environment_id,
            enabled_modules=scope.enabled_modules,
            permission_codes=scope.permission_codes,
            roles=scope.roles,
            authorized_legal_entity_ids=scope.legal_entity_ids,
            purpose=scope.purpose,
            locale=scope.locale,
            effective_at=scope.effective_at,
        )
        try:
            returned = await provider.retrieve(request)
            matches = tuple(KnowledgeMatch.model_validate(item.model_dump()) for item in returned)
            if len(matches) > case.evaluation_limit:
                raise ValueError("provider exceeded evaluation limit")
            if len({item.chunk_id for item in matches}) != len(matches) or len(
                {item.citation_id for item in matches}
            ) != len(matches):
                raise ValueError("provider returned duplicate results")
        except asyncio.CancelledError:
            raise
        except Exception:
            return self._provider_failure(case)

        relevant = {item.result_id: item for item in case.relevant_items}
        retrieved_ids = tuple(
            item.citation_id if item.citation_id in relevant else item.chunk_id for item in matches
        )
        precision, recall, mrr, ndcg = retrieval_metrics(
            retrieved_ids, case.relevant_items, case.evaluation_limit
        )
        forbidden = sum(
            item.chunk_id in case.forbidden_result_ids
            or item.citation_id in case.forbidden_result_ids
            for item in matches
        )
        cross_customer = sum(
            item.customer_environment_id not in (None, scope.customer_environment_id)
            for item in matches
        )
        leaks = sum(not self._authorized(scope, item) for item in matches)
        security = forbidden + leaks + cross_customer
        return EvaluationCaseResult(
            case_id=case.case_id,
            precision_at_k=precision,
            recall_at_k=recall,
            mrr_at_k=mrr,
            ndcg_at_k=ndcg,
            expected_empty_accuracy=(1.0 if not matches else 0.0) if case.expected_empty else None,
            retrieved_count=len(matches),
            forbidden_result_count=forbidden,
            authorization_leak_count=leaks,
            cross_customer_result_count=cross_customer,
            unexpected_provider_failure_count=0,
            disposition=(
                EvaluationDisposition.SECURITY_FAILURE if security else EvaluationDisposition.PASSED
            ),
        )

    @staticmethod
    def _authorized(scope: EvaluationAuthorizationScope, match: KnowledgeMatch) -> bool:
        return (
            match.namespace == scope.namespace
            and set(match.required_modules_all).issubset(scope.enabled_modules)
            and set(match.required_permissions_all).issubset(scope.permission_codes)
            and scope.purpose in match.allowed_purposes
            and set(match.legal_entity_ids).issubset(scope.legal_entity_ids)
            and (
                match.customer_environment_id is None
                or match.customer_environment_id == scope.customer_environment_id
            )
            and scope.effective_at >= match.effective_from
            and (match.effective_to is None or scope.effective_at < match.effective_to)
            and _CLASSIFICATION_RANK[match.data_classification]
            <= _CLASSIFICATION_RANK[DataClassification.RESTRICTED]
        )

    @staticmethod
    def _provider_failure(case: RetrievalEvaluationCase) -> EvaluationCaseResult:
        return EvaluationCaseResult(
            case_id=case.case_id,
            precision_at_k=0.0,
            recall_at_k=0.0,
            mrr_at_k=0.0,
            ndcg_at_k=0.0,
            expected_empty_accuracy=0.0 if case.expected_empty else None,
            retrieved_count=0,
            forbidden_result_count=0,
            authorization_leak_count=0,
            cross_customer_result_count=0,
            unexpected_provider_failure_count=1,
            disposition=EvaluationDisposition.INFRASTRUCTURE_FAILURE,
        )

    def _report(
        self,
        suite: RetrievalEvaluationSuite,
        candidate: RetrievalCandidate,
        thresholds: EvaluationThresholds,
        results: tuple[EvaluationCaseResult, ...],
    ) -> RetrievalEvaluationReport:
        slice_cases: tuple[tuple[str, tuple[str, ...]], ...] = (
            ("overall", tuple(case.case_id for case in suite.cases)),
            *(
                (
                    name,
                    tuple(
                        case.case_id for case in suite.cases if case.language_slice.value == name
                    ),
                )
                for name in ("arabic", "english", "mixed")
            ),
            *(
                (
                    source,
                    tuple(
                        case.case_id
                        for case in suite.cases
                        if any(item.source_type.value == source for item in case.relevant_items)
                    ),
                )
                for source in ("product_documentation", "customer_policy")
            ),
        )
        by_id = {result.case_id: result for result in results}
        slices = tuple(
            EvaluationSliceResult(
                slice_name=name,  # type: ignore[arg-type]
                metrics=self._summary(tuple(by_id[case_id] for case_id in case_ids)),
            )
            for name, case_ids in slice_cases
        )
        overall = slices[0].metrics
        security = any(
            result.forbidden_result_count
            or result.authorization_leak_count
            or result.cross_customer_result_count
            for result in results
        )
        infrastructure = any(result.unexpected_provider_failure_count for result in results)
        quality = (
            overall.precision_at_k < thresholds.minimum_precision_at_k
            or overall.recall_at_k < thresholds.minimum_recall_at_k
            or overall.mrr_at_k < thresholds.minimum_mrr_at_k
            or overall.ndcg_at_k < thresholds.minimum_ndcg_at_k
            or overall.expected_empty_accuracy < thresholds.minimum_expected_empty_accuracy
        )
        disposition = (
            EvaluationDisposition.SECURITY_FAILURE
            if security
            else EvaluationDisposition.INFRASTRUCTURE_FAILURE
            if infrastructure
            else EvaluationDisposition.QUALITY_FAILURE
            if quality
            else EvaluationDisposition.PASSED
        )
        failing = tuple(
            result.case_id
            for result in results
            if result.disposition is not EvaluationDisposition.PASSED
            or (
                result.expected_empty_accuracy is None
                and (
                    result.precision_at_k < thresholds.minimum_precision_at_k
                    or result.recall_at_k < thresholds.minimum_recall_at_k
                    or result.mrr_at_k < thresholds.minimum_mrr_at_k
                    or result.ndcg_at_k < thresholds.minimum_ndcg_at_k
                )
            )
            or (
                result.expected_empty_accuracy is not None
                and result.expected_empty_accuracy < thresholds.minimum_expected_empty_accuracy
            )
        )
        return RetrievalEvaluationReport(
            suite_id=suite.suite_id,
            suite_version=suite.suite_version,
            candidate_id=candidate.candidate_id,
            candidate_type=candidate.candidate_type,
            evaluation_fingerprint=evaluation_fingerprint(suite, candidate, thresholds),
            disposition=disposition,
            slices=slices,
            failing_case_ids=failing,
        )

    @staticmethod
    def _summary(results: tuple[EvaluationCaseResult, ...]) -> RetrievalMetricSummary:
        count = len(results)
        empty = tuple(
            result.expected_empty_accuracy
            for result in results
            if result.expected_empty_accuracy is not None
        )
        quality_results = tuple(
            result for result in results if result.expected_empty_accuracy is None
        )

        def mean(values: tuple[float, ...]) -> float:
            return sum(values) / len(values) if values else 0.0

        retrieved_count = sum(result.retrieved_count for result in results)
        authorization_leak_count = sum(result.authorization_leak_count for result in results)
        return RetrievalMetricSummary(
            case_count=count,
            precision_at_k=mean(tuple(result.precision_at_k for result in quality_results)),
            recall_at_k=mean(tuple(result.recall_at_k for result in quality_results)),
            mrr_at_k=mean(tuple(result.mrr_at_k for result in quality_results)),
            ndcg_at_k=mean(tuple(result.ndcg_at_k for result in quality_results)),
            expected_empty_accuracy=mean(empty) if empty else 1.0,
            expected_empty_case_count=len(empty),
            retrieved_count=retrieved_count,
            unexpected_provider_failure_count=sum(
                result.unexpected_provider_failure_count for result in results
            ),
            forbidden_result_count=sum(result.forbidden_result_count for result in results),
            authorization_leak_count=authorization_leak_count,
            authorization_leak_rate=(
                authorization_leak_count / retrieved_count if retrieved_count else 0.0
            ),
            cross_customer_result_count=sum(
                result.cross_customer_result_count for result in results
            ),
        )
