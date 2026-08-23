"""Customer-routed PostgreSQL knowledge storage adapters."""

from erp_ai.infrastructure.postgres.config import (
    KnowledgeDatabaseRouteConfig,
    StaticKnowledgeDatabaseConfig,
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

__all__ = [
    "KnowledgeDatabaseAccess",
    "KnowledgeDatabaseRouteConfig",
    "KnowledgeDatabaseRouter",
    "PostgresKnowledgeIndexRepository",
    "PostgresLexicalKnowledgeRetrievalProvider",
    "StaticKnowledgeDatabaseConfig",
    "StaticKnowledgeDatabaseRouter",
]
