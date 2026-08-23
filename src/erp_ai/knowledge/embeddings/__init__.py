"""Provider-neutral embedding preparation contracts."""

from erp_ai.knowledge.embeddings.models import (
    EmbeddingBatchRequest,
    EmbeddingBatchResult,
    EmbeddingInput,
    EmbeddingMaterializationResult,
    EmbeddingProfile,
    EmbeddingVector,
    PreparedEmbedding,
    PreparedEmbeddingSet,
)
from erp_ai.knowledge.embeddings.provider import EmbeddingProvider
from erp_ai.knowledge.embeddings.service import (
    EmbeddingGenerationSource,
    EmbeddingMaterializationError,
    EmbeddingMaterializer,
)

__all__ = [
    "EmbeddingBatchRequest",
    "EmbeddingBatchResult",
    "EmbeddingGenerationSource",
    "EmbeddingInput",
    "EmbeddingMaterializationError",
    "EmbeddingMaterializationResult",
    "EmbeddingMaterializer",
    "EmbeddingProfile",
    "EmbeddingProvider",
    "EmbeddingVector",
    "PreparedEmbedding",
    "PreparedEmbeddingSet",
]
