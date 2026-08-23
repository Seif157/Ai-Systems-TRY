"""Atomic persistence boundary for full knowledge-index generations."""

from typing import Protocol, runtime_checkable
from uuid import UUID

from erp_ai.context.models import Identifier
from erp_ai.knowledge.indexing.models import (
    KnowledgeIndexScope,
    KnowledgeIndexSnapshot,
    KnowledgeOperationResult,
    KnowledgePublicationPlan,
    KnowledgePublicationResult,
    KnowledgeRollbackRequest,
    KnowledgeRollbackResult,
)


@runtime_checkable
class KnowledgeIndexRepository(Protocol):
    """Adapter must make each commit operation one indivisible durable transaction."""

    async def commit_generation(
        self, plan: KnowledgePublicationPlan, expected_active_generation_id: UUID | None
    ) -> KnowledgePublicationResult: ...

    async def get_active_snapshot(
        self, scope: KnowledgeIndexScope
    ) -> KnowledgeIndexSnapshot | None: ...

    async def commit_rollback(
        self, request: KnowledgeRollbackRequest, expected_active_generation_id: UUID
    ) -> KnowledgeRollbackResult: ...

    async def get_operation_result(
        self, operation_id: Identifier
    ) -> KnowledgeOperationResult | None: ...
