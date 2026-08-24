import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from erp_ai.capabilities import DataClassification
from erp_ai.knowledge import KnowledgeSourceType
from erp_ai.knowledge.indexing import (
    IndexPublicationLimits,
    KnowledgeIndexPublisher,
    KnowledgePublicationConflict,
    KnowledgePublicationContext,
    KnowledgePublicationError,
)
from erp_ai.knowledge.indexing.models import KnowledgePublicationAuditOutboxEvent
from erp_ai.knowledge.ingestion import (
    IngestionLimits,
    KnowledgeDocumentDraft,
    KnowledgeSection,
    SourceProvenance,
    prepare_knowledge_document,
)
from tests.support.knowledge_index_repository import AtomicTestKnowledgeIndexRepository

NOW = datetime(2026, 8, 23, tzinfo=UTC)


def context(
    *,
    operation: str = "op-1",
    customer: str = "customer-a",
    namespace: str = "hr",
    installed_modules: tuple[str, ...] = ("hr_core", "leave"),
):
    return KnowledgePublicationContext(
        operation_id=operation,
        request_id=f"request-{operation}",
        customer_environment_id=customer,
        actor_id="admin-service",
        namespace=namespace,
        installed_modules=installed_modules,
        authorization_snapshot_id="auth-1",
        issued_at=NOW,
    )


def bundle(
    *,
    document_id: UUID | None = None,
    customer: str | None = None,
    source_type: KnowledgeSourceType = KnowledgeSourceType.PRODUCT_DOCUMENTATION,
    namespace: str = "hr",
    modules: tuple[str, ...] = ("hr_core",),
    permissions: tuple[str, ...] = ("hr.knowledge.read",),
    purposes: tuple[str, ...] = ("employee_self_service",),
    legal_entities: tuple[str, ...] = (),
    effective_from: datetime | None = None,
    effective_to: datetime | None = None,
    content: str = "Approved knowledge",
    version: str = "1.0.0",
    classification: DataClassification = DataClassification.INTERNAL,
    provenance: SourceProvenance | None = None,
    chunk_characters: int = 2_000,
):
    draft = KnowledgeDocumentDraft(
        document_id=document_id or uuid4(),
        document_version=version,
        namespace=namespace,
        source_type=source_type,
        customer_environment_id=customer,
        title="Guide",
        language="en",
        required_modules_all=modules,
        required_permissions_all=permissions,
        allowed_purposes=purposes,
        legal_entity_ids=legal_entities,
        data_classification=classification,
        effective_from=effective_from or NOW - timedelta(days=2),
        effective_to=effective_to,
        approval_reference="approval-1",
        approved_at=NOW - timedelta(days=3),
        source_provenance=provenance,
        sections=(KnowledgeSection(section_key="guide", heading="Guide", text_blocks=(content,)),),
    )
    return prepare_knowledge_document(
        draft,
        limits=IngestionLimits(
            overlap_characters=0,
            maximum_chunk_characters=chunk_characters,
            maximum_chunk_bytes=8_192,
        ),
    )


def publisher(repository: AtomicTestKnowledgeIndexRepository) -> KnowledgeIndexPublisher:
    return KnowledgeIndexPublisher(repository, clock=lambda: NOW)


def run(coro):
    return asyncio.run(coro)


def test_models_are_strict_frozen_and_context_is_trusted_only() -> None:
    trusted = context()
    with pytest.raises(ValidationError):
        trusted.actor_id = "other"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        KnowledgePublicationContext(**{**trusted.model_dump(), "unknown": True})
    with pytest.raises(ValidationError, match="timezone-aware"):
        KnowledgePublicationContext(**{**trusted.model_dump(), "issued_at": datetime(2026, 1, 1)})
    assert "installed_modules" not in repr(trusted)
    with pytest.raises(ValidationError, match="duplicate"):
        KnowledgePublicationContext(
            **{**trusted.model_dump(), "installed_modules": ["leave", "leave"]}
        )


def test_first_replacement_snapshot_outbox_and_idempotency() -> None:
    repository = AtomicTestKnowledgeIndexRepository()
    service = publisher(repository)
    first = run(service.publish(context(), (bundle(),), expected_active_generation_id=None))
    snapshot = run(service.get_active_snapshot(first.scope))
    assert snapshot is not None and snapshot.active_generation_id == first.generation_id
    assert len(repository.outbox) == 1

    repeated = run(
        service.publish(
            context(),
            (repository.plans[first.generation_id].bundles[0],),
            expected_active_generation_id=None,
        )
    )
    assert repeated.generation_id == first.generation_id
    assert repeated == first
    assert len(repository.outbox) == 1

    second_bundle = bundle(content="Replacement")
    second = run(
        service.publish(
            context(operation="op-2"),
            (second_bundle,),
            expected_active_generation_id=first.generation_id,
        )
    )
    assert second.previous_generation_id == first.generation_id
    assert repository.statuses[first.generation_id].value == "retired"
    assert len(repository.outbox) == 2


def test_digest_is_deterministic_and_independent_of_bundle_order() -> None:
    repository = AtomicTestKnowledgeIndexRepository()
    service = publisher(repository)
    one = bundle(document_id=UUID(int=1), content="One")
    two = bundle(document_id=UUID(int=2), content="Two")
    left = service.build_plan(context(), (one, two))
    right = service.build_plan(context(operation="op-2"), (two, one))
    assert left.manifest.generation_digest == right.manifest.generation_digest
    assert tuple(item.manifest.document_id for item in left.bundles) == (UUID(int=1), UUID(int=2))
    assert left.manifest.document_count == 2 and left.manifest.chunk_count == 2


@pytest.mark.parametrize(
    ("prepared", "message"),
    [
        (
            lambda: _with_namespace("finance"),
            "namespace",
        ),
        (
            lambda: bundle(customer="customer-b", source_type=KnowledgeSourceType.CUSTOMER_POLICY),
            "customer policy",
        ),
        (
            lambda: _with_customer_on_global(),
            "global document",
        ),
        (lambda: bundle(modules=("payroll",)), "unavailable module"),
        (lambda: bundle(effective_to=NOW), "expired"),
        (
            lambda: _with_classification(DataClassification.HIGHLY_RESTRICTED),
            "classification",
        ),
    ],
)
def test_scope_module_effective_and_classification_rejections(prepared, message: str) -> None:
    with pytest.raises(KnowledgePublicationError, match=message):
        publisher(AtomicTestKnowledgeIndexRepository()).build_plan(context(), (prepared(),))


def test_global_product_and_matching_customer_policy_are_allowed() -> None:
    plan = publisher(AtomicTestKnowledgeIndexRepository()).build_plan(
        context(),
        (
            bundle(),
            bundle(customer="customer-a", source_type=KnowledgeSourceType.CUSTOMER_POLICY),
        ),
    )
    assert plan.manifest.document_count == 2


def _with_customer_on_global():
    valid = bundle()
    return valid.model_copy(
        update={
            "manifest": valid.manifest.model_copy(update={"customer_environment_id": "customer-a"}),
            "chunks": tuple(
                chunk.model_copy(update={"customer_environment_id": "customer-a"})
                for chunk in valid.chunks
            ),
        }
    )


def _with_namespace(namespace: str):
    valid = bundle()
    return valid.model_copy(
        update={
            "manifest": valid.manifest.model_copy(update={"namespace": namespace}),
            "chunks": tuple(
                chunk.model_copy(update={"namespace": namespace}) for chunk in valid.chunks
            ),
        }
    )


def _with_classification(classification: DataClassification):
    valid = bundle()
    return valid.model_copy(
        update={
            "chunks": tuple(
                chunk.model_copy(update={"data_classification": classification})
                for chunk in valid.chunks
            )
        }
    )


def test_empty_constructed_invalid_and_tampered_bundles_fail_boundary() -> None:
    service = publisher(AtomicTestKnowledgeIndexRepository())
    with pytest.raises(KnowledgePublicationError, match="bundle count"):
        service.build_plan(context(), ())
    malformed = bundle().model_construct(manifest="bad", chunks=(), disposition="bad")
    with pytest.warns(UserWarning), pytest.raises(KnowledgePublicationError, match="invalid"):
        service.build_plan(context(), (malformed,))
    valid = bundle()
    tampered_manifest = valid.model_copy(
        update={"manifest": valid.manifest.model_copy(update={"document_fingerprint": "0" * 64})}
    )
    with pytest.raises(KnowledgePublicationError, match="document fingerprint"):
        service.build_plan(context(), (tampered_manifest,))
    tampered_chunk = valid.model_copy(
        update={"chunks": (valid.chunks[0].model_copy(update={"chunk_id": "chk_" + "0" * 32}),)}
    )
    with pytest.raises(KnowledgePublicationError, match="chunk fingerprint"):
        service.build_plan(context(), (tampered_chunk,))


def test_chunk_order_totals_and_metadata_are_revalidated() -> None:
    service = publisher(AtomicTestKnowledgeIndexRepository())
    valid = bundle(content="one two three four")
    chunk = valid.chunks[0]
    cases = (
        valid.model_copy(update={"chunks": (chunk.model_copy(update={"chunk_ordinal": 1}),)}),
        valid.model_copy(update={"total_chunk_count": 2}),
        valid.model_copy(update={"chunks": (chunk.model_copy(update={"namespace": "finance"}),)}),
        valid.model_copy(
            update={"chunks": (chunk.model_copy(update={"citation_id": "cite_" + "0" * 32}),)}
        ),
    )
    for malformed in cases:
        with pytest.raises(KnowledgePublicationError):
            service.build_plan(context(), (malformed,))
    multiple = bundle(content="one two three four", chunk_characters=7)
    inconsistent = multiple.model_copy(
        update={
            "chunks": (
                multiple.chunks[0],
                multiple.chunks[1].model_copy(update={"title": "Changed"}),
                *multiple.chunks[2:],
            )
        }
    )
    with pytest.raises(KnowledgePublicationError, match="governance"):
        service.build_plan(context(), (inconsistent,))


def test_duplicate_documents_and_versions_fail() -> None:
    service = publisher(AtomicTestKnowledgeIndexRepository())
    document_id = uuid4()
    first = bundle(document_id=document_id)
    with pytest.raises(KnowledgePublicationError, match="duplicate document"):
        service.build_plan(context(), (first, first))
    different_version = bundle(document_id=document_id, version="2.0.0")
    with pytest.raises(KnowledgePublicationError, match="conflicting document versions"):
        service.build_plan(context(), (first, different_version))


def test_duplicate_chunk_and_citation_ids_fail_before_tampered_bundle_use() -> None:
    service = publisher(AtomicTestKnowledgeIndexRepository())
    first = bundle()
    second = bundle()
    duplicate_chunk = second.model_copy(
        update={
            "chunks": (second.chunks[0].model_copy(update={"chunk_id": first.chunks[0].chunk_id}),)
        }
    )
    with pytest.raises(KnowledgePublicationError, match="chunk IDs"):
        service.build_plan(context(), (first, duplicate_chunk))
    duplicate_citation = second.model_copy(
        update={
            "chunks": (
                second.chunks[0].model_copy(update={"citation_id": first.chunks[0].citation_id}),
            )
        }
    )
    with pytest.raises(KnowledgePublicationError, match="citation IDs"):
        service.build_plan(context(), (first, duplicate_citation))


def test_source_provenance_is_fingerprinted() -> None:
    provenance = SourceProvenance(
        catalog_version=1,
        raw_source_sha256="a" * 64,
        parser_name="markdown-it-py",
        parser_major_version=4,
        adapter_contract_version=1,
    )
    plan = publisher(AtomicTestKnowledgeIndexRepository()).build_plan(
        context(), (bundle(provenance=provenance),)
    )
    assert plan.manifest.generation_digest


@pytest.mark.parametrize(
    "limits",
    [
        IndexPublicationLimits(maximum_bundles_per_call=1),
        IndexPublicationLimits(maximum_documents=1),
        IndexPublicationLimits(maximum_chunks=1),
        IndexPublicationLimits(maximum_normalized_bytes=1),
    ],
)
def test_incremental_publication_limits(limits: IndexPublicationLimits) -> None:
    bundles = (bundle(content="One"), bundle(content="Two"))
    with pytest.raises(KnowledgePublicationError):
        publisher(AtomicTestKnowledgeIndexRepository()).build_plan(
            context(), bundles, limits=limits
        )


def test_concurrency_conflict_and_atomic_failure_have_no_partial_visibility() -> None:
    repository = AtomicTestKnowledgeIndexRepository()
    service = publisher(repository)
    repository.fail_next_commit = True
    with pytest.raises(RuntimeError, match="atomic failure"):
        run(service.publish(context(), (bundle(),), expected_active_generation_id=None))
    assert repository.active == repository.plans == repository.operations == repository.outbox == {}

    async def compete():
        return await asyncio.gather(
            service.publish(
                context(operation="winner-a"), (bundle(),), expected_active_generation_id=None
            ),
            service.publish(
                context(operation="winner-b"), (bundle(),), expected_active_generation_id=None
            ),
            return_exceptions=True,
        )

    results = run(compete())
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, KnowledgePublicationConflict) for result in results) == 1
    assert len(repository.plans) == len(repository.outbox) == 1


def test_changed_operation_digest_conflicts() -> None:
    repository = AtomicTestKnowledgeIndexRepository()
    service = publisher(repository)
    run(service.publish(context(), (bundle(content="One"),), expected_active_generation_id=None))
    with pytest.raises(KnowledgePublicationConflict, match="operation ID"):
        run(
            service.publish(
                context(), (bundle(content="Changed"),), expected_active_generation_id=None
            )
        )


def test_outbox_exact_allowlist_and_excludes_payload_and_authorization() -> None:
    repository = AtomicTestKnowledgeIndexRepository()
    result = run(
        publisher(repository).publish(context(), (bundle(),), expected_active_generation_id=None)
    )
    event = next(iter(repository.outbox.values()))
    assert set(event.model_dump()) == {
        "outbox_id",
        "operation_id",
        "request_id",
        "customer_environment_id",
        "actor_id",
        "namespace",
        "action",
        "previous_generation_id",
        "activated_generation_id",
        "generation_digest",
        "outcome",
    }
    serialized = event.model_dump_json()
    assert result.generation_id == event.activated_generation_id
    assert not any(
        forbidden in serialized
        for forbidden in ("Approved knowledge", "permissions", "purposes", "modules", "citation")
    )
    assert set(KnowledgePublicationAuditOutboxEvent.model_fields) == set(event.model_dump())


def test_invalid_context_construct_is_rejected() -> None:
    malformed = context().model_construct(namespace="BAD VALUE")
    with pytest.raises(KnowledgePublicationError, match="context"):
        publisher(AtomicTestKnowledgeIndexRepository()).build_plan(malformed, (bundle(),))


def test_rollback_operation_id_cannot_reuse_publication_result() -> None:
    repository = AtomicTestKnowledgeIndexRepository()
    service = publisher(repository)
    published = run(service.publish(context(), (bundle(),), expected_active_generation_id=None))
    with pytest.raises(KnowledgePublicationConflict, match="operation ID"):
        run(
            service.rollback(
                context(),
                target_generation_id=published.generation_id,
                expected_active_generation_id=published.generation_id,
            )
        )
