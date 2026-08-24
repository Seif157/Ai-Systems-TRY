import json
import os
from datetime import UTC, datetime
from uuid import UUID

import pytest

from erp_ai.infrastructure.postgres import (
    PostgresEmbeddingRepository,
    PostgresKnowledgeIndexRepository,
    PostgresSemanticKnowledgeRetrievalProvider,
    SemanticRetrievalPolicy,
)
from erp_ai.infrastructure.tei import (
    QWEN3_LOCAL_TEST_RESOURCE_POLICY,
    QWEN3_PINNED_RUNTIME_IDENTITY,
    QWEN3_QUERY_INSTRUCTION,
    TeiEmbeddingProvider,
    TeiEmbeddingProviderConfig,
)
from erp_ai.knowledge import KnowledgeRetrievalRequest
from erp_ai.knowledge.embeddings import EmbeddingMaterializer
from erp_ai.knowledge.evaluation import (
    CalibrationCaseObservation,
    CalibrationScoredResult,
    EvaluationAuthorizationScope,
    EvaluationDisposition,
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
from tests.unit.test_embedding_models import profile
from tests.unit.test_knowledge_index_publication import bundle, context

REQUIRED = (
    os.environ.get("ERP_AI_REQUIRE_POSTGRES_TESTS") == "1"
    and os.environ.get("ERP_AI_REQUIRE_LOCAL_EMBEDDING_TESTS") == "1"
)
ENDPOINT = os.environ.get("ERP_AI_TEI_ENDPOINT")
API_KEY = os.environ.get("ERP_AI_TEI_API_KEY")
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.local_embedding,
    pytest.mark.skipif(not REQUIRED, reason="combined PostgreSQL/Qwen tests were not required"),
]
NOW = datetime(2026, 8, 24, tzinfo=UTC)


def _case(
    case_id: str,
    query: str,
    language: str,
    partition: str,
    citation_id: str | None,
    forbidden: tuple[str, ...],
) -> RetrievalEvaluationCase:
    relevant = (
        ()
        if citation_id is None
        else (
            GradedRelevantItem(
                result_id=citation_id,
                identifier_type="citation",
                relevance_grade=3,
                source_type="product_documentation",
            ),
        )
    )
    return RetrievalEvaluationCase(
        case_id=case_id,
        query=query,
        language_slice=language,
        partition=partition,
        authorization_scope=EvaluationAuthorizationScope(
            namespace="hr",
            customer_environment_id="synthetic_customer_a",
            enabled_modules=("hr_core", "leave"),
            permission_codes=("hr.knowledge.read",),
            roles=("employee",),
            legal_entity_ids=("synthetic_entity_a",),
            purpose="employee_self_service",
            locale="en",
            effective_at=NOW,
        ),
        relevant_items=relevant,
        forbidden_result_ids=forbidden,
        expected_empty=citation_id is None,
        evaluation_limit=5,
    )


def _request(case: RetrievalEvaluationCase) -> KnowledgeRetrievalRequest:
    scope = case.authorization_scope
    return KnowledgeRetrievalRequest(
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


def _tei_config() -> TeiEmbeddingProviderConfig:
    assert ENDPOINT is not None and API_KEY is not None
    return TeiEmbeddingProviderConfig(
        endpoint=ENDPOINT,
        api_key=API_KEY,
        expected_model_id="Qwen/Qwen3-Embedding-0.6B",
        expected_model_revision="97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3",
        expected_tei_version_minimum="1.9.3",
        expected_tei_version_maximum="1.9.3",
        expected_pooling="last-token",
        dimensions=1024,
        connect_timeout_seconds=3.0,
        read_timeout_seconds=180.0,
        write_timeout_seconds=10.0,
        pool_timeout_seconds=3.0,
        maximum_response_bytes=1_000_000,
        maximum_tokenize_response_bytes=250_000,
        maximum_input_characters=4000,
        maximum_input_bytes=16_000,
        resource_policy=QWEN3_LOCAL_TEST_RESOURCE_POLICY,
        local_testing_mode=True,
    )


async def _exercise() -> dict[str, object]:
    router = await _provision((("synthetic_customer_a", CUSTOMERS[0][1]),))
    embedding_profile = profile(
        dimensions=1024,
        profile_id="qwen3_local_v1",
        provider_id="local_tei",
        model_id="Qwen/Qwen3-Embedding-0.6B",
        model_revision="97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3",
        query_instruction=QWEN3_QUERY_INSTRUCTION,
    )
    try:
        documents = (
            bundle(
                document_id=UUID(int=101), content="Annual leave entitlement and vacation policy."
            ),
            bundle(document_id=UUID(int=102), content="سياسة استحقاق الإجازة السنوية للموظفين."),
            bundle(
                document_id=UUID(int=103),
                content="Sick leave entitlement and medical absence policy.",
            ),
            bundle(document_id=UUID(int=104), content="سياسة الإجازة المرضية والغياب الطبي."),
            bundle(
                document_id=UUID(int=105),
                content="Payroll tax configuration restricted guidance.",
                modules=("hr_core", "payroll"),
            ),
            bundle(
                document_id=UUID(int=106),
                content="Annual leave guidance for another legal entity.",
                legal_entities=("synthetic_entity_b",),
            ),
        )
        publication = await KnowledgeIndexPublisher(
            PostgresKnowledgeIndexRepository(router, "synthetic_customer_a")
        ).publish(
            context(
                operation="qwen-evaluation-publication",
                customer="synthetic_customer_a",
                installed_modules=("hr_core", "leave", "payroll"),
            ),
            documents,
            expected_active_generation_id=None,
        )
        repository = PostgresEmbeddingRepository(router, "synthetic_customer_a")
        source = await repository.load_generation_source(
            publication.scope, publication.generation_id
        )
        async with TeiEmbeddingProvider(_tei_config()) as provider:
            prepared = await EmbeddingMaterializer(provider, batch_size=4).materialize(
                source, embedding_profile
            )
            await repository.persist(
                prepared,
                operation_id="qwen-evaluation-embeddings",
                request_id="qwen-evaluation-request",
                actor_id="synthetic_evaluator",
            )
            forbidden = tuple(item.chunks[0].citation_id for item in documents[4:])
            cases = (
                _case(
                    "cal_en",
                    "annual vacation entitlement",
                    "english",
                    "calibration",
                    documents[0].chunks[0].citation_id,
                    forbidden,
                ),
                _case(
                    "cal_ar",
                    "ما هي سياسة الإجازة السنوية؟",
                    "arabic",
                    "calibration",
                    documents[1].chunks[0].citation_id,
                    forbidden,
                ),
                _case(
                    "cal_empty",
                    "quantum processor procurement",
                    "english",
                    "calibration",
                    None,
                    forbidden,
                ),
                _case(
                    "hold_en",
                    "medical absence and sick leave",
                    "english",
                    "holdout",
                    documents[2].chunks[0].citation_id,
                    forbidden,
                ),
                _case(
                    "hold_ar",
                    "ما هي قواعد الإجازة المرضية؟",
                    "arabic",
                    "holdout",
                    documents[3].chunks[0].citation_id,
                    forbidden,
                ),
                _case(
                    "hold_mixed",
                    "What is سياسة الإجازة المرضية؟",
                    "mixed",
                    "holdout",
                    documents[3].chunks[0].citation_id,
                    forbidden,
                ),
                _case(
                    "hold_empty", "marine cargo insurance", "english", "holdout", None, forbidden
                ),
            )
            zero_policy = SemanticRetrievalPolicy(
                namespace="hr",
                embedding_profile_sha256=embedding_profile.profile_sha256,
                minimum_relevance_score=0.0,
                policy_version="1.0.0",
            )
            zero_provider = PostgresSemanticKnowledgeRetrievalProvider(
                router,
                "synthetic_customer_a",
                embedding_profile,
                provider,
                zero_policy,
            )
            observations = []
            for case in cases[:3]:
                matches = await zero_provider.retrieve(_request(case))
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
                                forbidden_result=item.citation_id in forbidden,
                                cross_customer_result=False,
                            )
                            for item in matches
                        ),
                    )
                )
            gates = EvaluationThresholds(
                minimum_precision_at_k=0.2,
                minimum_recall_at_k=0.5,
                minimum_mrr_at_k=0.5,
                minimum_ndcg_at_k=0.5,
                minimum_expected_empty_accuracy=1.0,
            )
            selection = select_semantic_threshold(tuple(observations), gates)
            selected_policy = SemanticRetrievalPolicy(
                namespace="hr",
                embedding_profile_sha256=embedding_profile.profile_sha256,
                minimum_relevance_score=selection.selected_threshold,
                policy_version="1.0.0",
            )
            candidate = RetrievalCandidate(
                candidate_id="qwen3_semantic",
                candidate_type="semantic",
                embedding_profile_sha256=embedding_profile.profile_sha256,
                semantic_policy_sha256=selected_policy.policy_sha256,
                embedding_resource_policy_sha256=(QWEN3_LOCAL_TEST_RESOURCE_POLICY.policy_sha256),
                embedding_runtime_identity_sha256=(QWEN3_PINNED_RUNTIME_IDENTITY.identity_sha256),
            )
            service = RetrievalEvaluationService(
                {
                    candidate.candidate_id: PostgresSemanticKnowledgeRetrievalProvider(
                        router,
                        "synthetic_customer_a",
                        embedding_profile,
                        provider,
                        selected_policy,
                    )
                }
            )
            reports = []
            for partition, partition_cases in (
                ("calibration", cases[:3]),
                ("holdout", cases[3:]),
            ):
                suite = RetrievalEvaluationSuite(
                    contract_version=1,
                    suite_id=f"synthetic_qwen_{partition}",
                    suite_version="1.0.0",
                    corpus_generation_digest=publication.generation_digest,
                    dataset_governance="approved_synthetic",
                    cases=partition_cases,
                )
                report = (await service.evaluate(suite, (candidate,), gates))[0]
                overall = report.slices[0].metrics
                assert report.disposition is EvaluationDisposition.PASSED
                assert overall.forbidden_result_count == 0
                assert overall.authorization_leak_count == 0
                assert overall.cross_customer_result_count == 0
                assert overall.unexpected_provider_failure_count == 0
                reports.append((partition, report))
            return {
                "selection": selection.model_dump(mode="json"),
                **{
                    partition: {
                        item.slice_name: item.metrics.model_dump(mode="json")
                        for item in report.slices
                        if item.slice_name in {"overall", "arabic", "english", "mixed"}
                    }
                    for partition, report in reports
                },
            }
    finally:
        await router.close()


def test_real_qwen_postgres_calibration_and_holdout() -> None:
    result = _run(_exercise())
    print("QWEN_EVALUATION=" + json.dumps(result, sort_keys=True, separators=(",", ":")))
