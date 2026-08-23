import asyncio

import pytest

from erp_ai.knowledge.indexing import GenerationStatus, KnowledgePublicationConflict
from tests.support.knowledge_index_repository import AtomicTestKnowledgeIndexRepository
from tests.unit.test_knowledge_index_publication import bundle, context, publisher


def run(coro):
    return asyncio.run(coro)


def test_snapshot_binding_replacement_and_successful_rollback() -> None:
    repository = AtomicTestKnowledgeIndexRepository()
    service = publisher(repository)
    first = run(
        service.publish(context(), (bundle(content="Old"),), expected_active_generation_id=None)
    )
    acquired = run(service.get_active_snapshot(first.scope))
    second = run(
        service.publish(
            context(operation="publish-2"),
            (bundle(content="New"),),
            expected_active_generation_id=first.generation_id,
        )
    )
    assert acquired is not None and acquired.active_generation_id == first.generation_id
    assert (
        run(service.get_active_snapshot(first.scope)).active_generation_id == second.generation_id
    )  # type: ignore[union-attr]

    rollback = run(
        service.rollback(
            context(operation="rollback-1"),
            target_generation_id=first.generation_id,
            expected_active_generation_id=second.generation_id,
        )
    )
    assert rollback.activated_generation_id == first.generation_id
    assert repository.statuses[first.generation_id] is GenerationStatus.ACTIVE
    assert repository.statuses[second.generation_id] is GenerationStatus.RETIRED
    assert len(repository.outbox) == 3

    repeated = run(
        service.rollback(
            context(operation="rollback-1"),
            target_generation_id=first.generation_id,
            expected_active_generation_id=second.generation_id,
        )
    )
    assert repeated == rollback and len(repository.outbox) == 3


def test_rollback_rejects_stale_candidate_and_cross_scope_targets() -> None:
    repository = AtomicTestKnowledgeIndexRepository()
    service = publisher(repository)
    first = run(service.publish(context(), (bundle(),), expected_active_generation_id=None))
    candidate = service.build_plan(context(operation="candidate"), (bundle(content="candidate"),))
    repository.plans[candidate.manifest.generation_id] = candidate
    repository.statuses[candidate.manifest.generation_id] = GenerationStatus.CANDIDATE
    with pytest.raises(KnowledgePublicationConflict):
        run(
            service.rollback(
                context(operation="rollback-candidate"),
                target_generation_id=candidate.manifest.generation_id,
                expected_active_generation_id=first.generation_id,
            )
        )
    with pytest.raises(KnowledgePublicationConflict):
        run(
            service.rollback(
                context(operation="rollback-stale"),
                target_generation_id=first.generation_id,
                expected_active_generation_id=candidate.manifest.generation_id,
            )
        )


def test_rollback_cross_customer_and_namespace_and_atomic_failure() -> None:
    repository = AtomicTestKnowledgeIndexRepository()
    service = publisher(repository)
    first = run(service.publish(context(), (bundle(),), expected_active_generation_id=None))
    second = run(
        service.publish(
            context(operation="second"),
            (bundle(content="second"),),
            expected_active_generation_id=first.generation_id,
        )
    )
    for trusted in (
        context(operation="cross-customer", customer="customer-b"),
        context(operation="cross-namespace", namespace="finance"),
    ):
        with pytest.raises(KnowledgePublicationConflict):
            run(
                service.rollback(
                    trusted,
                    target_generation_id=first.generation_id,
                    expected_active_generation_id=second.generation_id,
                )
            )
    repository.fail_next_commit = True
    with pytest.raises(RuntimeError):
        run(
            service.rollback(
                context(operation="failed-rollback"),
                target_generation_id=first.generation_id,
                expected_active_generation_id=second.generation_id,
            )
        )
    assert repository.active[first.scope] == second.generation_id
    assert len(repository.outbox) == 2
