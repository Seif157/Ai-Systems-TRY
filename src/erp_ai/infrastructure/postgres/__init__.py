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
from erp_ai.infrastructure.postgres.production_rag import (
    KNOWLEDGE_MIGRATION_CHECKSUMS,
    KNOWLEDGE_READ_CONTRACT_DIGEST,
    KNOWLEDGE_READ_CONTRACT_VERSION,
    PostgresKnowledgeContractVerifier,
    ProductionKnowledgeConfig,
    ProductionKnowledgeDatabaseRouter,
    ProductionKnowledgeRoute,
    ProductionRagBundle,
    build_production_rag_bundle,
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
    "KNOWLEDGE_MIGRATION_CHECKSUMS",
    "KNOWLEDGE_READ_CONTRACT_DIGEST",
    "KNOWLEDGE_READ_CONTRACT_VERSION",
    "EmbeddingMaterializationConflict",
    "HybridRetrievalPolicy",
    "KnowledgeDatabaseAccess",
    "KnowledgeDatabaseRouteConfig",
    "KnowledgeDatabaseRouter",
    "PostgresEmbeddingRepository",
    "PostgresHybridKnowledgeRetrievalProvider",
    "PostgresKnowledgeContractVerifier",
    "PostgresKnowledgeIndexRepository",
    "PostgresLexicalKnowledgeRetrievalProvider",
    "PostgresSemanticKnowledgeRetrievalProvider",
    "ProductionKnowledgeConfig",
    "ProductionKnowledgeDatabaseRouter",
    "ProductionKnowledgeRoute",
    "ProductionRagBundle",
    "SemanticRetrievalPolicy",
    "StaticKnowledgeDatabaseConfig",
    "StaticKnowledgeDatabaseRouter",
    "build_production_rag_bundle",
    "reciprocal_rank_fusion",
]
