from erp_ai.knowledge.ingestion import (
    KnowledgeDocumentDraft,
    PreparedKnowledgeBundle,
    PreparedKnowledgeChunk,
)


def test_draft_has_only_normalized_approved_document_fields() -> None:
    assert set(KnowledgeDocumentDraft.model_fields) == {
        "document_id",
        "document_version",
        "namespace",
        "source_type",
        "customer_environment_id",
        "title",
        "language",
        "required_modules_all",
        "required_permissions_all",
        "allowed_purposes",
        "legal_entity_ids",
        "data_classification",
        "effective_from",
        "effective_to",
        "approval_reference",
        "approved_at",
        "sections",
    }
    assert {"path", "url", "embedding", "database_row", "sql"}.isdisjoint(
        KnowledgeDocumentDraft.model_fields
    )


def test_prepared_contract_is_internal_and_has_no_relevance_or_storage_metadata() -> None:
    assert "relevance_score" not in PreparedKnowledgeChunk.model_fields
    assert {"path", "storage_url", "embedding", "vector"}.isdisjoint(
        PreparedKnowledgeChunk.model_fields
    )
    assert set(PreparedKnowledgeBundle.model_fields) == {
        "manifest",
        "chunks",
        "disposition",
        "total_normalized_utf8_bytes",
        "total_chunk_count",
    }
