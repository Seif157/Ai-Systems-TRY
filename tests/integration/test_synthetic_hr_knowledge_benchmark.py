import json
import os
from collections.abc import Mapping

import pytest

from erp_ai.infrastructure.postgres import (
    HybridRetrievalPolicy,
    PostgresEmbeddingRepository,
    PostgresHybridKnowledgeRetrievalProvider,
    PostgresKnowledgeIndexRepository,
    PostgresLexicalKnowledgeRetrievalProvider,
    PostgresSemanticKnowledgeRetrievalProvider,
    SemanticRetrievalPolicy,
)
from erp_ai.infrastructure.tei import (
    QWEN3_LOCAL_TEST_RESOURCE_POLICY,
    QWEN3_PINNED_RUNTIME_IDENTITY,
    QWEN3_QUERY_INSTRUCTION,
    TeiEmbeddingProvider,
)
from erp_ai.knowledge import KnowledgeRetrievalProvider, KnowledgeRetrievalRequest
from erp_ai.knowledge.embeddings import EmbeddingMaterializer
from erp_ai.knowledge.evaluation import (
    CalibrationCaseObservation,
    CalibrationScoredResult,
    EvaluationAuthorizationScope,
    EvaluationThresholds,
    GradedRelevantItem,
    RetrievalCandidate,
    RetrievalEvaluationCase,
    RetrievalEvaluationService,
    RetrievalEvaluationSuite,
    select_semantic_threshold,
)
from erp_ai.knowledge.indexing import KnowledgeIndexPublisher
from tests.integration.test_postgres_knowledge_storage import CUSTOMERS, _provision, _run
from tests.integration.test_postgres_qwen_retrieval_evaluation import _tei_config
from tests.support.synthetic_hr_knowledge import (
    AggregateZeroRecallDiagnostics,
    SyntheticReferenceCase,
    ZeroRecallReason,
    load_manifest,
    partition_fingerprint,
    prepare_corpus,
    publishable_corpus,
    reference_cases,
)
from tests.unit.test_embedding_models import profile
from tests.unit.test_knowledge_index_publication import context

REQUIRED = (
    os.environ.get("ERP_AI_REQUIRE_POSTGRES_TESTS") == "1"
    and os.environ.get("ERP_AI_REQUIRE_LOCAL_EMBEDDING_TESTS") == "1"
)
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.local_embedding,
    pytest.mark.skipif(not REQUIRED, reason="synthetic live benchmark was not required"),
]


class CustomerProvider:
    def __init__(self, providers: Mapping[str, KnowledgeRetrievalProvider]) -> None:
        self.providers = dict(providers)
        self.records = []

    async def retrieve(self, request: KnowledgeRetrievalRequest):  # type: ignore[no-untyped-def]
        try:
            result = await self.providers[request.customer_environment_id].retrieve(request)
        except Exception:
            self.records.append(None)
            raise
        self.records.append(result)
        return result


def _scope(case: SyntheticReferenceCase):  # type: ignore[no-untyped-def]
    manifest = load_manifest()
    entities = {
        f"{key}_{index + 1}": value
        for key, values in manifest.fictional_legal_entities.items()
        for index, value in enumerate(values)
    }
    return EvaluationAuthorizationScope(
        namespace="hr",
        customer_environment_id=manifest.fictional_customers[case.customer_key],
        enabled_modules=case.enabled_modules,
        permission_codes=("hr.knowledge.read",),
        roles=("employee",),
        legal_entity_ids=tuple(entities[key] for key in case.legal_entity_keys),
        purpose="employee_self_service",
        locale="ar-EG" if case.language_slice == "arabic" else "en",
        effective_at=manifest.evaluation_at,
    )


def _evaluation_case(case: SyntheticReferenceCase, bundles):  # type: ignore[no-untyped-def]
    by_document = {item.manifest.document_id: item for item in bundles}
    manifest = load_manifest()
    source_types = {item.id: item.source for item in manifest.documents}
    relevant = tuple(
        GradedRelevantItem(
            result_id=next(
                chunk.citation_id
                for chunk in by_document[label.document_id].chunks
                if chunk.section_key == label.section_key
            ),
            identifier_type="citation",
            relevance_grade=label.relevance_grade,
            source_type=source_types[label.document_id],
        )
        for label in case.labels
    )
    return RetrievalEvaluationCase(
        case_id=case.case_id,
        query=case.query,
        language_slice=case.language_slice,
        partition=case.partition,
        authorization_scope=_scope(case),
        relevant_items=relevant,
        forbidden_result_ids=(),
        expected_empty=case.expected_empty,
        evaluation_limit=5,
    )


async def _benchmark() -> dict[str, object]:
    manifest = load_manifest()
    customers = {
        manifest.fictional_customers["alpha"]: CUSTOMERS[0][1],
        manifest.fictional_customers["beta"]: CUSTOMERS[1][1],
    }
    router = await _provision(tuple(customers.items()))
    bundles = prepare_corpus()
    embedding_profile = profile(
        dimensions=1024,
        profile_id="qwen3_synthetic_hr_v1",
        provider_id="local_tei",
        model_id="Qwen/Qwen3-Embedding-0.6B",
        model_revision="97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3",
        query_instruction=QWEN3_QUERY_INSTRUCTION,
    )
    try:
        publications = {}
        async with TeiEmbeddingProvider(_tei_config()) as embedding_provider:
            for key, customer in manifest.fictional_customers.items():
                selected = publishable_corpus(customer)
                publication = await KnowledgeIndexPublisher(
                    PostgresKnowledgeIndexRepository(router, customer)
                ).publish(
                    context(
                        operation=f"synthetic-step18-{key}",
                        customer=customer,
                        installed_modules=(
                            "hr_core",
                            "leave",
                            "attendance_fixture",
                            "payroll_fixture",
                        ),
                    ),
                    selected,
                    expected_active_generation_id=None,
                )
                repository = PostgresEmbeddingRepository(router, customer)
                source = await repository.load_generation_source(
                    publication.scope, publication.generation_id
                )
                prepared = await EmbeddingMaterializer(
                    embedding_provider, batch_size=4
                ).materialize(source, embedding_profile)
                await repository.persist(
                    prepared,
                    operation_id=f"synthetic-step18-embed-{key}",
                    request_id=f"synthetic-step18-request-{key}",
                    actor_id="synthetic_evaluator",
                )
                publications[customer] = publication

            zero_semantic = {
                customer: PostgresSemanticKnowledgeRetrievalProvider(
                    router,
                    customer,
                    embedding_profile,
                    embedding_provider,
                    SemanticRetrievalPolicy(
                        namespace="hr",
                        embedding_profile_sha256=embedding_profile.profile_sha256,
                        minimum_relevance_score=0.0,
                        policy_version="1.0.0",
                    ),
                )
                for customer in customers
            }
            evaluation_cases = tuple(_evaluation_case(case, bundles) for case in reference_cases())
            observations = []
            for case in evaluation_cases:
                if case.partition != "calibration":
                    continue
                scope = case.authorization_scope
                matches = await zero_semantic[scope.customer_environment_id].retrieve(
                    KnowledgeRetrievalRequest(
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
                )
                relevant_ids = {item.result_id for item in case.relevant_items}
                observations.append(
                    CalibrationCaseObservation(
                        case_id=case.case_id,
                        partition="calibration",
                        evaluation_limit=case.evaluation_limit,
                        expected_empty=case.expected_empty,
                        relevant_items=case.relevant_items,
                        scored_results=tuple(
                            CalibrationScoredResult(
                                result_id=item.citation_id,
                                relevance_score=item.relevance_score,
                                authorization_violation=False,
                                forbidden_result=case.expected_empty
                                or (bool(relevant_ids) and item.citation_id not in relevant_ids),
                                cross_customer_result=False,
                            )
                            for item in matches
                        ),
                    )
                )
            gates = EvaluationThresholds(
                minimum_precision_at_k=0.01,
                minimum_recall_at_k=0.01,
                minimum_mrr_at_k=0.01,
                minimum_ndcg_at_k=0.01,
                minimum_expected_empty_accuracy=1.0,
            )
            selection = select_semantic_threshold(tuple(observations), gates)
            lexical, semantic, hybrid = {}, {}, {}
            hybrid_policies = {}
            semantic_policy = SemanticRetrievalPolicy(
                namespace="hr",
                embedding_profile_sha256=embedding_profile.profile_sha256,
                minimum_relevance_score=selection.selected_threshold,
                policy_version="1.0.0",
            )
            for customer, publication in publications.items():
                lexical[customer] = PostgresLexicalKnowledgeRetrievalProvider(router, customer)
                semantic[customer] = PostgresSemanticKnowledgeRetrievalProvider(
                    router, customer, embedding_profile, embedding_provider, semantic_policy
                )
                hybrid_policy = HybridRetrievalPolicy(
                    policy_version="1.0.0",
                    namespace="hr",
                    embedding_profile_sha256=embedding_profile.profile_sha256,
                    semantic_threshold=selection.selected_threshold,
                    threshold_approval_status="unapproved_test_only",
                    generation_digest=publication.generation_digest,
                    embedding_resource_policy_sha256=QWEN3_LOCAL_TEST_RESOURCE_POLICY.policy_sha256,
                    embedding_runtime_identity_sha256=QWEN3_PINNED_RUNTIME_IDENTITY.identity_sha256,
                )
                hybrid_policies[customer] = hybrid_policy
                hybrid[customer] = PostgresHybridKnowledgeRetrievalProvider(
                    router, customer, embedding_profile, embedding_provider, hybrid_policy
                )
            output = {}
            diagnostic_counts = {
                candidate: {reason: 0 for reason in ZeroRecallReason}
                for candidate in ("lexical", "semantic", "hybrid")
            }
            for partition in ("calibration", "holdout"):
                output[partition] = {}
                for customer_key, customer in manifest.fictional_customers.items():
                    partition_cases = tuple(
                        case
                        for case in evaluation_cases
                        if case.partition == partition
                        and case.authorization_scope.customer_environment_id == customer
                    )
                    candidates = (
                        RetrievalCandidate(candidate_id="lexical", candidate_type="lexical"),
                        RetrievalCandidate(
                            candidate_id="semantic",
                            candidate_type="semantic",
                            embedding_profile_sha256=embedding_profile.profile_sha256,
                            semantic_policy_sha256=semantic_policy.policy_sha256,
                            embedding_resource_policy_sha256=QWEN3_LOCAL_TEST_RESOURCE_POLICY.policy_sha256,
                            embedding_runtime_identity_sha256=QWEN3_PINNED_RUNTIME_IDENTITY.identity_sha256,
                        ),
                        RetrievalCandidate(
                            candidate_id="hybrid",
                            candidate_type="hybrid",
                            embedding_profile_sha256=embedding_profile.profile_sha256,
                            semantic_policy_sha256=semantic_policy.policy_sha256,
                            embedding_resource_policy_sha256=QWEN3_LOCAL_TEST_RESOURCE_POLICY.policy_sha256,
                            embedding_runtime_identity_sha256=QWEN3_PINNED_RUNTIME_IDENTITY.identity_sha256,
                            hybrid_policy_sha256=hybrid_policies[customer].policy_sha256,
                            threshold_approval_status="unapproved_test_only",
                        ),
                    )
                    recording = {
                        "lexical": CustomerProvider(lexical),
                        "semantic": CustomerProvider(semantic),
                        "hybrid": CustomerProvider(hybrid),
                    }
                    service = RetrievalEvaluationService(recording)
                    suite = RetrievalEvaluationSuite(
                        contract_version=1,
                        suite_id=f"synthetic_hr_{customer_key}_{partition}",
                        suite_version=manifest.dataset_version,
                        corpus_generation_digest=publications[customer].generation_digest,
                        dataset_governance="approved_synthetic",
                        cases=partition_cases,
                    )
                    reports = await service.evaluate(suite, candidates, gates)
                    output[partition][customer_key] = {
                        report.candidate_type.value: {
                            item.slice_name: item.metrics.model_dump(mode="json")
                            for item in report.slices
                        }
                        for report in reports
                    }
                    for report in reports:
                        overall = report.slices[0].metrics
                        assert overall.authorization_leak_count == 0
                        assert overall.cross_customer_result_count == 0
                        assert overall.forbidden_result_count == 0
                        assert overall.unexpected_provider_failure_count == 0
                    for candidate_name, provider_record in recording.items():
                        assert len(provider_record.records) == len(partition_cases)
                        for case, matches in zip(
                            partition_cases, provider_record.records, strict=True
                        ):
                            if not case.relevant_items:
                                continue
                            relevant = {item.result_id for item in case.relevant_items}
                            if matches is None:
                                diagnostic_counts[candidate_name][
                                    ZeroRecallReason.PROVIDER_FAILURE
                                ] += 1
                            elif not any(item.citation_id in relevant for item in matches):
                                reason = (
                                    ZeroRecallReason.NO_LEXICAL_MATCH
                                    if candidate_name == "lexical"
                                    else ZeroRecallReason.BELOW_THRESHOLD
                                )
                                diagnostic_counts[candidate_name][reason] += 1
            diagnostics = {
                candidate: AggregateZeroRecallDiagnostics(counts=counts).model_dump(mode="json")
                for candidate, counts in diagnostic_counts.items()
            }
            return {
                "corpus_fingerprint": manifest.corpus_fingerprint,
                "calibration_partition_fingerprint": partition_fingerprint("calibration"),
                "holdout_partition_fingerprint": partition_fingerprint("holdout"),
                "threshold": selection.model_dump(mode="json"),
                "reports": output,
                "zero_recall_diagnostics": diagnostics,
            }
    finally:
        await router.close()


def test_live_synthetic_hr_benchmark() -> None:
    result = _run(_benchmark())
    print("SYNTHETIC_HR_BENCHMARK=" + json.dumps(result, sort_keys=True, separators=(",", ":")))
