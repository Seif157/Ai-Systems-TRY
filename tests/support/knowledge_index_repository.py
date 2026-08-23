"""Test-only atomic repository; never exported by the production package."""

import asyncio
from uuid import UUID

from erp_ai.context.models import Identifier
from erp_ai.knowledge.indexing import (
    GenerationStatus,
    KnowledgeIndexScope,
    KnowledgeIndexSnapshot,
    KnowledgePublicationAuditOutboxEvent,
    KnowledgePublicationConflict,
    KnowledgePublicationPlan,
    KnowledgePublicationResult,
    KnowledgeRollbackRequest,
    KnowledgeRollbackResult,
    PublicationDisposition,
)
from erp_ai.knowledge.indexing.models import KnowledgeOperationResult


class AtomicTestKnowledgeIndexRepository:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.active: dict[KnowledgeIndexScope, UUID] = {}
        self.plans: dict[UUID, KnowledgePublicationPlan] = {}
        self.statuses: dict[UUID, GenerationStatus] = {}
        self.operations: dict[Identifier, KnowledgeOperationResult] = {}
        self.outbox: dict[UUID, KnowledgePublicationAuditOutboxEvent] = {}
        self.fail_next_commit = False

    async def get_operation_result(
        self, operation_id: Identifier
    ) -> KnowledgeOperationResult | None:
        return self.operations.get(operation_id)

    async def get_active_snapshot(
        self, scope: KnowledgeIndexScope
    ) -> KnowledgeIndexSnapshot | None:
        generation_id = self.active.get(scope)
        if generation_id is None:
            return None
        manifest = self.plans[generation_id].manifest
        return KnowledgeIndexSnapshot(
            scope=scope,
            active_generation_id=generation_id,
            generation_digest=manifest.generation_digest,
            publication_contract_version=manifest.publication_contract_version,
        )

    async def commit_generation(
        self, plan: KnowledgePublicationPlan, expected_active_generation_id: UUID | None
    ) -> KnowledgePublicationResult:
        async with self._lock:
            existing = self.operations.get(plan.context.operation_id)
            if existing is not None:
                if (
                    not isinstance(existing, KnowledgePublicationResult)
                    or existing.operation_digest != plan.operation_digest
                ):
                    raise KnowledgePublicationConflict("operation ID conflict")
                return existing
            current = self.active.get(plan.manifest.scope)
            if current != expected_active_generation_id:
                raise KnowledgePublicationConflict("active generation changed")
            if self.fail_next_commit:
                self.fail_next_commit = False
                raise RuntimeError("injected atomic failure")
            event = plan.outbox_event.model_copy(update={"previous_generation_id": current})
            result = KnowledgePublicationResult(
                operation_id=plan.context.operation_id,
                scope=plan.manifest.scope,
                generation_id=plan.manifest.generation_id,
                previous_generation_id=current,
                generation_digest=plan.manifest.generation_digest,
                operation_digest=plan.operation_digest,
                disposition=PublicationDisposition.PUBLISHED,
            )
            if current is not None:
                self.statuses[current] = GenerationStatus.RETIRED
            self.plans[plan.manifest.generation_id] = plan
            self.statuses[plan.manifest.generation_id] = GenerationStatus.ACTIVE
            self.active[plan.manifest.scope] = plan.manifest.generation_id
            self.outbox[event.outbox_id] = event
            self.operations[plan.context.operation_id] = result
            return result

    async def commit_rollback(
        self, request: KnowledgeRollbackRequest, expected_active_generation_id: UUID
    ) -> KnowledgeRollbackResult:
        async with self._lock:
            existing = self.operations.get(request.context.operation_id)
            if existing is not None:
                if (
                    not isinstance(existing, KnowledgeRollbackResult)
                    or existing.operation_digest != request.operation_digest
                ):
                    raise KnowledgePublicationConflict("operation ID conflict")
                return existing
            current = self.active.get(request.scope)
            if current != expected_active_generation_id:
                raise KnowledgePublicationConflict("active generation changed")
            target = self.plans.get(request.target_generation_id)
            if target is None or target.manifest.scope != request.scope:
                raise KnowledgePublicationConflict("rollback target is unavailable")
            if self.statuses.get(request.target_generation_id) is not GenerationStatus.RETIRED:
                raise KnowledgePublicationConflict("rollback target is not retained")
            if self.fail_next_commit:
                self.fail_next_commit = False
                raise RuntimeError("injected atomic failure")
            self.statuses[current] = GenerationStatus.RETIRED
            self.statuses[request.target_generation_id] = GenerationStatus.ACTIVE
            self.active[request.scope] = request.target_generation_id
            digest = target.manifest.generation_digest
            event = KnowledgePublicationAuditOutboxEvent(
                outbox_id=request.outbox_id,
                operation_id=request.context.operation_id,
                request_id=request.context.request_id,
                customer_environment_id=request.context.customer_environment_id,
                actor_id=request.context.actor_id,
                namespace=request.context.namespace,
                action="knowledge.rollback",
                previous_generation_id=current,
                activated_generation_id=request.target_generation_id,
                generation_digest=digest,
                outcome="succeeded",
            )
            result = KnowledgeRollbackResult(
                operation_id=request.context.operation_id,
                scope=request.scope,
                activated_generation_id=request.target_generation_id,
                previous_generation_id=current,
                generation_digest=digest,
                operation_digest=request.operation_digest,
                disposition=PublicationDisposition.ROLLED_BACK,
            )
            self.outbox[event.outbox_id] = event
            self.operations[request.context.operation_id] = result
            return result
