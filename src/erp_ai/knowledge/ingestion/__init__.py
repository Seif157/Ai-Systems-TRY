"""Deterministic offline preparation of approved normalized knowledge documents."""

from erp_ai.knowledge.ingestion.models import (
    ExistingDocumentManifest,
    IngestionLimits,
    KnowledgeDocumentDraft,
    KnowledgeSection,
    PreparationDisposition,
    PreparedKnowledgeBundle,
    PreparedKnowledgeChunk,
)
from erp_ai.knowledge.ingestion.service import prepare_knowledge_document

__all__ = [
    "ExistingDocumentManifest",
    "IngestionLimits",
    "KnowledgeDocumentDraft",
    "KnowledgeSection",
    "PreparationDisposition",
    "PreparedKnowledgeBundle",
    "PreparedKnowledgeChunk",
    "prepare_knowledge_document",
]
