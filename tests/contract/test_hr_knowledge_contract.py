from erp_ai.capabilities.hr_knowledge import KnowledgeExcerpt, SearchHrKnowledgeInput


def test_public_input_and_excerpt_are_explicit_allowlists() -> None:
    assert set(SearchHrKnowledgeInput.model_fields) == {"query"}
    assert set(KnowledgeExcerpt.model_fields) == {
        "citation_id",
        "title",
        "section",
        "language",
        "source_type",
        "document_version",
        "content",
        "content_trust",
    }


def test_public_excerpt_excludes_internal_scope_and_retrieval_metadata() -> None:
    forbidden = {
        "chunk_id",
        "document_id",
        "customer_environment_id",
        "legal_entity_ids",
        "required_modules_all",
        "required_permissions_all",
        "roles",
        "allowed_purposes",
        "data_classification",
        "relevance_score",
        "embedding",
        "storage_path",
    }
    assert forbidden.isdisjoint(KnowledgeExcerpt.model_fields)
