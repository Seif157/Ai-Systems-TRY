import asyncio
import hashlib
import os

import pytest
from pydantic import SecretStr

from erp_ai.capabilities import DataClassification
from erp_ai.infrastructure.tei import (
    QWEN3_LOCAL_TEST_RESOURCE_POLICY,
    QWEN3_QUERY_INSTRUCTION,
    TeiEmbeddingProvider,
    TeiEmbeddingProviderConfig,
    TeiProviderUnavailable,
)
from erp_ai.knowledge.embeddings import EmbeddingBatchRequest, EmbeddingInput
from tests.unit.test_embedding_models import profile

REQUIRE_LOCAL = os.environ.get("ERP_AI_REQUIRE_LOCAL_EMBEDDING_TESTS") == "1"
ENDPOINT = os.environ.get("ERP_AI_TEI_ENDPOINT")
API_KEY = os.environ.get("ERP_AI_TEI_API_KEY")
if REQUIRE_LOCAL and (not ENDPOINT or not API_KEY):
    raise pytest.UsageError(
        "ERP_AI_TEI_ENDPOINT and ERP_AI_TEI_API_KEY are required when "
        "ERP_AI_REQUIRE_LOCAL_EMBEDDING_TESTS=1"
    )
pytestmark = [
    pytest.mark.local_embedding,
    pytest.mark.skipif(
        not REQUIRE_LOCAL,
        reason="local embedding tests were not explicitly required",
    ),
]


def _input(identifier: str, text: str, kind: str) -> EmbeddingInput:
    return EmbeddingInput(
        input_id=identifier,
        text=text,
        content_sha256=hashlib.sha256(text.encode()).hexdigest(),
        data_classification=DataClassification.INTERNAL,
        input_kind=kind,
    )


async def _exercise() -> None:
    assert ENDPOINT is not None and API_KEY is not None
    config = TeiEmbeddingProviderConfig(
        endpoint=ENDPOINT,
        api_key=API_KEY,
        expected_model_id="Qwen/Qwen3-Embedding-0.6B",
        expected_model_revision="97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3",
        expected_tei_version_minimum="1.9.3",
        expected_tei_version_maximum="1.9.3",
        expected_pooling="last-token",
        dimensions=1024,
        connect_timeout_seconds=3.0,
        read_timeout_seconds=180.0,
        write_timeout_seconds=10.0,
        pool_timeout_seconds=3.0,
        maximum_response_bytes=1_000_000,
        maximum_tokenize_response_bytes=250_000,
        maximum_input_characters=4000,
        maximum_input_bytes=16_000,
        resource_policy=QWEN3_LOCAL_TEST_RESOURCE_POLICY,
        local_testing_mode=True,
    )
    embedding_profile = profile(
        profile_id="qwen3_local_v1",
        provider_id="local_tei",
        model_id="Qwen/Qwen3-Embedding-0.6B",
        model_revision="97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3",
        dimensions=1024,
        query_instruction=QWEN3_QUERY_INSTRUCTION,
    )
    async with TeiEmbeddingProvider(config) as provider:
        result = await provider.embed(
            EmbeddingBatchRequest(
                profile=embedding_profile,
                inputs=(
                    _input("arabic_query", "ما هي سياسة الإجازة السنوية؟", "query"),
                    _input("english_query", "What is the annual leave policy?", "query"),
                    _input("mixed_query", "What is سياسة الإجازة؟", "query"),
                    _input("document", "Annual leave is governed by approved policy.", "document"),
                ),
            )
        )
        assert len(result.vectors) == 4
        assert all(len(item.values) == 1024 for item in result.vectors)
        assert len({item.vector_sha256 for item in result.vectors}) == 4

        exact_text = ("x " * 1023).strip()
        exact = await provider.embed(
            EmbeddingBatchRequest(
                profile=embedding_profile,
                inputs=(_input("exact_1024_tokens", exact_text, "document"),),
            )
        )
        assert len(exact.vectors[0].values) == 1024

        over_text = ("x " * 1024).strip()
        with pytest.raises(TeiProviderUnavailable, match="generation is unavailable"):
            await provider.embed(
                EmbeddingBatchRequest(
                    profile=embedding_profile,
                    inputs=(_input("over_1024_tokens", over_text, "document"),),
                )
            )

    wrong_key_config = config.model_copy(update={"api_key": SecretStr("wrong-key")})
    with pytest.raises(TeiProviderUnavailable, match="identity is unavailable"):
        await TeiEmbeddingProvider(wrong_key_config).open()

    bounded_config = config.model_copy(update={"maximum_response_bytes": 4096})
    async with TeiEmbeddingProvider(bounded_config) as provider:
        with pytest.raises(TeiProviderUnavailable, match="generation is unavailable"):
            await provider.embed(
                EmbeddingBatchRequest(
                    profile=embedding_profile,
                    inputs=(_input("bounded_response", "synthetic response bound", "document"),),
                )
            )

    async with TeiEmbeddingProvider(config) as provider:
        task = asyncio.create_task(
            provider.embed(
                EmbeddingBatchRequest(
                    profile=embedding_profile,
                    inputs=(_input("cancelled", exact_text, "document"),),
                )
            )
        )
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


def test_real_qwen3_bilingual_embedding_batch() -> None:
    asyncio.run(_exercise())
