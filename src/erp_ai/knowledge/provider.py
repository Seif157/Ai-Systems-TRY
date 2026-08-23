"""Provider boundary for authorized knowledge retrieval."""

from typing import Protocol, runtime_checkable

from erp_ai.knowledge.models import KnowledgeMatch, KnowledgeRetrievalRequest


@runtime_checkable
class KnowledgeRetrievalProvider(Protocol):
    """Apply tenant and authorization filters before semantic or lexical retrieval."""

    async def retrieve(self, request: KnowledgeRetrievalRequest) -> tuple[KnowledgeMatch, ...]: ...
