from erp_ai.knowledge.embeddings import (
    EmbeddingBatchRequest,
    EmbeddingInput,
    EmbeddingMaterializationResult,
    EmbeddingProfile,
    EmbeddingVector,
    PreparedEmbeddingSet,
)
from erp_ai.orchestration import AgentAuditEvent, ModelTurnRequest, PublicCitation
from erp_ai.tools import ToolAuditEvent


def test_embedding_contract_has_no_trusted_authorization_or_public_leakage_fields() -> None:
    forbidden = {
        "permissions",
        "roles",
        "legal_entity_ids",
        "enabled_modules",
        "customer_environment_id",
        "query",
    }
    assert forbidden.isdisjoint(EmbeddingInput.model_fields)
    assert forbidden.isdisjoint(EmbeddingBatchRequest.model_fields)
    assert {"values", "vector_sha256"}.isdisjoint(EmbeddingMaterializationResult.model_fields)
    assert {"text", "query", "citations"}.isdisjoint(EmbeddingVector.model_fields)
    assert "profile" not in EmbeddingMaterializationResult.model_fields
    assert "profile_sha256" in EmbeddingMaterializationResult.model_fields
    assert "embeddings" in PreparedEmbeddingSet.model_fields
    assert "provider_id" in EmbeddingProfile.model_fields
    sensitive_profile_fields = {
        "profile",
        "profile_id",
        "profile_sha256",
        "provider_id",
        "model_id",
        "model_revision",
        "dimensions",
        "distance_metric",
        "vector",
        "values",
    }
    for contract in (PublicCitation, ModelTurnRequest, ToolAuditEvent, AgentAuditEvent):
        assert sensitive_profile_fields.isdisjoint(contract.model_fields)
