"""Async provider boundary for embedding generation."""

from typing import Protocol

from erp_ai.knowledge.embeddings.models import EmbeddingBatchRequest, EmbeddingBatchResult


class EmbeddingProvider(Protocol):
    async def embed(self, request: EmbeddingBatchRequest) -> EmbeddingBatchResult: ...
