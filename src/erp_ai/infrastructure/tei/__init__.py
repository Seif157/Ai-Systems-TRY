"""Self-hosted TEI embedding adapter for explicitly enabled local tests."""

from erp_ai.infrastructure.tei.provider import (
    QWEN3_LOCAL_TEST_RESOURCE_POLICY,
    QWEN3_PINNED_RUNTIME_IDENTITY,
    QWEN3_QUERY_INSTRUCTION,
    TeiEmbeddingProvider,
    TeiEmbeddingProviderConfig,
    TeiProviderUnavailable,
    TeiResourcePolicy,
    TeiRuntimeIdentity,
)

__all__ = [
    "QWEN3_LOCAL_TEST_RESOURCE_POLICY",
    "QWEN3_PINNED_RUNTIME_IDENTITY",
    "QWEN3_QUERY_INSTRUCTION",
    "TeiEmbeddingProvider",
    "TeiEmbeddingProviderConfig",
    "TeiProviderUnavailable",
    "TeiResourcePolicy",
    "TeiRuntimeIdentity",
]
