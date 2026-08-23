from erp_ai.api import PublicChatRequest
from erp_ai.knowledge.indexing import KnowledgeIndexRepository, KnowledgePublicationContext
from erp_ai.knowledge.indexing.audit import KnowledgePublicationAuditOutboxEvent
from tests.support.knowledge_index_repository import AtomicTestKnowledgeIndexRepository


def test_repository_protocol_and_public_boundary() -> None:
    assert isinstance(AtomicTestKnowledgeIndexRepository(), KnowledgeIndexRepository)
    public_fields = set(PublicChatRequest.model_fields)
    assert not public_fields.intersection(KnowledgePublicationContext.model_fields)
    assert not public_fields.intersection(
        {"operation_id", "installed_modules", "authorization_snapshot_id", "generation_id"}
    )
    assert KnowledgePublicationAuditOutboxEvent.model_fields
