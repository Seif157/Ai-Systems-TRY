"""Customer-routed PostgreSQL knowledge storage adapters."""

from erp_ai.infrastructure.postgres.config import (
    KnowledgeDatabaseRouteConfig,
    StaticKnowledgeDatabaseConfig,
)
from erp_ai.infrastructure.postgres.embedding_repository import (
    EmbeddingMaterializationConflict,
    PostgresEmbeddingRepository,
)
from erp_ai.infrastructure.postgres.hybrid_retrieval import (
    HybridRetrievalPolicy,
    PostgresHybridKnowledgeRetrievalProvider,
    reciprocal_rank_fusion,
)
from erp_ai.infrastructure.postgres.knowledge_repository import PostgresKnowledgeIndexRepository
from erp_ai.infrastructure.postgres.knowledge_retrieval import (
    PostgresLexicalKnowledgeRetrievalProvider,
)
from erp_ai.infrastructure.postgres.routing import (
    KnowledgeDatabaseAccess,
    KnowledgeDatabaseRouter,
    StaticKnowledgeDatabaseRouter,
)
from erp_ai.infrastructure.postgres.semantic_retrieval import (
    PostgresSemanticKnowledgeRetrievalProvider,
    SemanticRetrievalPolicy,
)

__all__ = [
    "EmbeddingMaterializationConflict",
    "HybridRetrievalPolicy",
    "KnowledgeDatabaseAccess",
    "KnowledgeDatabaseRouteConfig",
    "KnowledgeDatabaseRouter",
    "PostgresEmbeddingRepository",
    "PostgresHybridKnowledgeRetrievalProvider",
    "PostgresKnowledgeIndexRepository",
    "PostgresLexicalKnowledgeRetrievalProvider",
    "PostgresSemanticKnowledgeRetrievalProvider",
    "SemanticRetrievalPolicy",
    "StaticKnowledgeDatabaseConfig",
    "StaticKnowledgeDatabaseRouter",
    "reciprocal_rank_fusion",
]
