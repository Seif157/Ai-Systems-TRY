"""Production HR knowledge-search capability."""

from erp_ai.capabilities.hr_knowledge.handlers import SearchHrKnowledgeHandler
from erp_ai.capabilities.hr_knowledge.manifest import HR_KNOWLEDGE_MANIFEST
from erp_ai.capabilities.hr_knowledge.models import (
    KnowledgeExcerpt,
    SearchHrKnowledgeInput,
    SearchHrKnowledgeOutput,
)

__all__ = [
    "HR_KNOWLEDGE_MANIFEST",
    "KnowledgeExcerpt",
    "SearchHrKnowledgeHandler",
    "SearchHrKnowledgeInput",
    "SearchHrKnowledgeOutput",
]
