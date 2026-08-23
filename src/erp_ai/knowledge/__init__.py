"""Reusable, provider-neutral contracts for authorized knowledge retrieval."""

from erp_ai.knowledge.models import (
    KnowledgeMatch,
    KnowledgeRetrievalRequest,
    KnowledgeSourceType,
)
from erp_ai.knowledge.provider import KnowledgeRetrievalProvider

__all__ = [
    "KnowledgeMatch",
    "KnowledgeRetrievalProvider",
    "KnowledgeRetrievalRequest",
    "KnowledgeSourceType",
]
