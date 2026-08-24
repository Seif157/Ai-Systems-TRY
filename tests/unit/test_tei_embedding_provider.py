import asyncio
import json
from collections.abc import Callable

import httpx
import pytest
from pydantic import ValidationError

from erp_ai.api import PublicChatRequest
from erp_ai.capabilities import DataClassification
from erp_ai.infrastructure.tei import (
    QWEN3_LOCAL_TEST_RESOURCE_POLICY,
    QWEN3_PINNED_RUNTIME_IDENTITY,
    QWEN3_QUERY_INSTRUCTION,
    TeiEmbeddingProvider,
    TeiEmbeddingProviderConfig,
    TeiProviderUnavailable,
    TeiResourcePolicy,
    TeiRuntimeIdentity,
)
from erp_ai.knowledge.embeddings import EmbeddingBatchRequest, EmbeddingInput
from tests.unit.test_embedding_models import profile

REVISION = "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3"
ASYNC_CLIENT = httpx.AsyncClient


def config(**overrides: object) -> TeiEmbeddingProviderConfig:
    values: dict[str, object] = {
        "endpoint": "http://127.0.0.1:58080",
        "api_key": "test-secret",
        "expected_model_id": "Qwen/Qwen3-Embedding-0.6B",
        "expected_model_revision": REVISION,
        "expected_tei_version_minimum": "1.9.3",
        "expected_tei_version_maximum": "1.9.3",
        "expected_pooling": "last-token",
        "dimensions": 1024,
        "connect_timeout_seconds": 2.0,
        "read_timeout_seconds": 20.0,
        "write_timeout_seconds": 5.0,
        "pool_timeout_seconds": 2.0,
        "maximum_response_bytes": 100_000,
        "maximum_tokenize_response_bytes": 100_000,
        "maximum_input_characters": 4000,
        "maximum_input_bytes": 16_000,
        "resource_policy": QWEN3_LOCAL_TEST_RESOURCE_POLICY,
        "local_testing_mode": True,
    }
    values.update(overrides)
    return TeiEmbeddingProviderConfig.model_validate(values)


def info(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "model_id": "Qwen/Qwen3-Embedding-0.6B",
        "model_sha": REVISION,
        "model_dtype": "float32",
        "served_model_name": "Qwen/Qwen3-Embedding-0.6B",
        "model_type": {"embedding": {"pooling": "last_token"}},
        "max_concurrent_requests": 1,
        "max_input_length": 32768,
        "max_batch_tokens": 1024,
        "max_batch_requests": 4,
        "max_client_batch_size": 4,
        "auto_truncate": True,
        "tokenization_workers": 1,
        "version": "1.9.3",
        "sha": "0667015",
        "docker_label": None,
    }
    values.update(overrides)
    return values


def install_transport(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> None:
    def factory(**kwargs: object) -> httpx.AsyncClient:
        return ASYNC_CLIENT(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr("erp_ai.infrastructure.tei.provider.httpx.AsyncClient", factory)


def request(*kinds: str, dimensions: int = 1024) -> EmbeddingBatchRequest:
    embedding_profile = profile(
        dimensions=dimensions,
        query_instruction=QWEN3_QUERY_INSTRUCTION,
        model_id="Qwen/Qwen3-Embedding-0.6B",
        model_revision=REVISION,
    )
    return EmbeddingBatchRequest(
        profile=embedding_profile,
        inputs=tuple(
            EmbeddingInput(
                input_id=f"input_{index}",
                text=f"text {index}",
                content_sha256=f"{index + 1:064x}",
                data_classification=DataClassification.INTERNAL,
                input_kind=kind,
            )
            for index, kind in enumerate(kinds)
        ),
    )


def token_response(count: int = 1) -> httpx.Response:
    return httpx.Response(
        200,
        json=[
            [
                {"id": index, "text": "<token>", "special": True, "start": None, "stop": None}
                for index in range(count)
            ]
        ],
        headers={"content-type": "application/json"},
    )


def test_config_is_strict_secret_safe_and_loopback_only() -> None:
    value = config()
    assert "test-secret" not in repr(value)
    for endpoint in (
        "https://127.0.0.1:58080",
        "http://example.com:58080",
        "http://127.0.0.1:58080/path",
        "http://user:pass@127.0.0.1:58080",
        "http://127.0.0.1",
        "http://127.0.0.1:58080?customer=a",
        "http://127.0.0.1:58080#fragment",
    ):
        with pytest.raises(ValidationError):
            config(endpoint=endpoint)
    with pytest.raises(ValidationError):
        config(expected_model_revision="main")
    with pytest.raises(ValidationError):
        config(expected_tei_version_minimum="1.9.4")
    with pytest.raises(ValidationError):
        config(unknown=True)


def test_open_handshake_and_document_query_transforms(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        seen.append(http_request)
        if http_request.url.path == "/info":
            return httpx.Response(200, json=info(), headers={"content-type": "application/json"})
        if http_request.url.path == "/tokenize":
            payload = json.loads(http_request.content)
            assert payload["add_special_tokens"] is True
            return token_response()
        payload = json.loads(http_request.content)
        assert payload in (
            {"inputs": ["text 0"], "truncate": False, "normalize": True},
            {
                "inputs": [f"Instruct: {QWEN3_QUERY_INSTRUCTION}\nQuery: text 1"],
                "truncate": False,
                "normalize": True,
            },
        )
        vector = (
            [1.0] + [0.0] * 1023 if payload["inputs"] == ["text 0"] else [0.0, 1.0] + [0.0] * 1022
        )
        return httpx.Response(
            200,
            json=[vector],
            headers={"content-type": "application/json; charset=utf-8"},
        )

    install_transport(monkeypatch, handler)

    async def exercise() -> None:
        provider = TeiEmbeddingProvider(config())
        async with provider:
            runtime = provider.runtime_identity
            assert runtime.configured_max_batch_requests == 1
            assert runtime.observed_max_batch_requests == 4
            assert runtime.application_max_concurrent_requests == 1
            assert runtime.application_execution_mode == "sequential"
            assert runtime.identity_sha256 == QWEN3_PINNED_RUNTIME_IDENTITY.identity_sha256
            result = await provider.embed(request("document", "query"))
            assert len(result.vectors) == 2
        with pytest.raises(TeiProviderUnavailable):
            await provider.embed(request("query"))
        with pytest.raises(TeiProviderUnavailable):
            _ = provider.runtime_identity

    asyncio.run(exercise())
    assert len(seen) == 5
    assert seen[0].headers["authorization"] == "Bearer test-secret"


@pytest.mark.parametrize(
    "override",
    (
        {"model_id": "wrong"},
        {"model_sha": "0" * 40},
        {"version": "1.9.2"},
        {"model_type": {"embedding": {"pooling": "mean"}}},
        {"auto_truncate": False},
        {"max_input_length": 100},
        {"max_batch_tokens": 100},
        {"max_client_batch_size": 3},
        {"max_concurrent_requests": 2},
        {"tokenization_workers": 2},
        {"model_dtype": "float16"},
        {"max_batch_requests": 3},
    ),
)
def test_identity_mismatch_fails_closed(
    monkeypatch: pytest.MonkeyPatch, override: dict[str, object]
) -> None:
    install_transport(
        monkeypatch,
        lambda _: httpx.Response(
            200, json=info(**override), headers={"content-type": "application/json"}
        ),
    )
    with pytest.raises(TeiProviderUnavailable, match="identity is unavailable"):
        asyncio.run(TeiEmbeddingProvider(config()).open())


def test_response_and_profile_failures_are_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    responses: list[httpx.Response] = [
        httpx.Response(200, json=info(), headers={"content-type": "application/json"}),
        token_response(),
        httpx.Response(
            200, json=[[2.0] + [0.0] * 1023], headers={"content-type": "application/json"}
        ),
    ]
    install_transport(monkeypatch, lambda _: responses.pop(0))

    async def exercise() -> None:
        provider = TeiEmbeddingProvider(config())
        await provider.open()
        with pytest.raises(TeiProviderUnavailable, match="generation is unavailable"):
            await provider.embed(request("document"))
        with pytest.raises(TeiProviderUnavailable, match="profile is incompatible"):
            await provider.embed(request("document", dimensions=3))
        with pytest.raises(TeiProviderUnavailable, match="lifecycle is invalid"):
            await provider.open()
        await provider.close()
        await provider.close()

    asyncio.run(exercise())


def test_bad_status_content_type_size_json_and_batch_are_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad = (
        httpx.Response(503, json={"secret": "provider-detail"}),
        httpx.Response(200, content=b"[]", headers={"content-type": "text/plain"}),
        httpx.Response(200, content=b"x" * 4097, headers={"content-type": "application/json"}),
        httpx.Response(200, content=b"not-json", headers={"content-type": "application/json"}),
    )
    for response in bad:
        calls = [
            httpx.Response(200, json=info(), headers={"content-type": "application/json"}),
            token_response(),
            response,
        ]
        install_transport(monkeypatch, lambda _, calls=calls: calls.pop(0))

        async def exercise() -> None:
            provider = TeiEmbeddingProvider(config(maximum_response_bytes=4096))
            await provider.open()
            with pytest.raises(TeiProviderUnavailable) as caught:
                await provider.embed(request("document"))
            assert "provider-detail" not in str(caught.value)
            await provider.close()

        asyncio.run(exercise())

    provider = TeiEmbeddingProvider(
        config(
            resource_policy=TeiResourcePolicy(
                max_batch_tokens=1024,
                max_batch_requests=1,
                max_concurrent_requests=1,
                tokenization_workers=1,
                max_client_batch_size=1,
                auto_truncate=True,
            )
        )
    )
    provider._opened = True
    provider._client = ASYNC_CLIENT(transport=httpx.MockTransport(lambda _: None))
    with pytest.raises(TeiProviderUnavailable, match="request is invalid"):
        asyncio.run(provider.embed(request("document", "query")))
    asyncio.run(provider.close())


def test_cancellation_wrong_count_shape_instruction_and_missing_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def cancelled(_: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError

    install_transport(monkeypatch, cancelled)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(TeiEmbeddingProvider(config()).open())

    responses: list[httpx.Response | BaseException] = [
        httpx.Response(200, json=info(), headers={"content-type": "application/json"}),
        token_response(),
        httpx.Response(200, json=[], headers={"content-type": "application/json"}),
        httpx.Response(200, json=info(), headers={"content-type": "application/json"}),
        token_response(),
        httpx.Response(200, json=[[1.0]], headers={"content-type": "application/json"}),
        httpx.Response(200, json=info(), headers={"content-type": "application/json"}),
        token_response(),
        asyncio.CancelledError(),
    ]

    def handler(_: httpx.Request) -> httpx.Response:
        result = responses.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    install_transport(monkeypatch, handler)

    async def exercise() -> None:
        for expected in (TeiProviderUnavailable, TeiProviderUnavailable, asyncio.CancelledError):
            provider = TeiEmbeddingProvider(config())
            await provider.open()
            with pytest.raises(expected):
                await provider.embed(request("document"))
            await provider.close()

        provider = TeiEmbeddingProvider(config())
        with pytest.raises(TeiProviderUnavailable):
            await provider._request("GET", "/info")

        provider._opened = True
        provider._client = ASYNC_CLIENT(transport=httpx.MockTransport(lambda _: None))
        incompatible = request("query").model_copy(
            update={
                "profile": request("query").profile.model_copy(
                    update={"query_instruction": "untrusted replacement"}
                )
            }
        )
        with pytest.raises(TeiProviderUnavailable, match="profile is incompatible"):
            await provider.embed(incompatible)
        await provider.close()

    asyncio.run(exercise())


def test_token_budget_counts_transformed_queries_and_preserves_exact_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, dict[str, object]]] = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        if http_request.url.path == "/info":
            return httpx.Response(200, json=info(), headers={"content-type": "application/json"})
        payload = json.loads(http_request.content)
        seen.append((http_request.url.path, payload))
        if http_request.url.path == "/tokenize":
            return token_response(512)
        vector = (
            [1.0] + [0.0] * 1023
            if len([x for x in seen if x[0] == "/embed"]) == 1
            else [0.0, 1.0] + [0.0] * 1022
        )
        return httpx.Response(200, json=[vector], headers={"content-type": "application/json"})

    install_transport(monkeypatch, handler)

    async def exercise() -> None:
        async with TeiEmbeddingProvider(config()) as provider:
            await provider.embed(request("document", "query"))

    asyncio.run(exercise())
    transformed = [
        "text 0",
        f"Instruct: {QWEN3_QUERY_INSTRUCTION}\nQuery: text 1",
    ]
    assert seen == [
        ("/tokenize", {"inputs": transformed[0], "add_special_tokens": True}),
        ("/tokenize", {"inputs": transformed[1], "add_special_tokens": True}),
        ("/embed", {"inputs": [transformed[0]], "truncate": False, "normalize": True}),
        ("/embed", {"inputs": [transformed[1]], "truncate": False, "normalize": True}),
    ]


@pytest.mark.parametrize("token_count", (1025,))
def test_individual_token_overflow_never_calls_embed(
    monkeypatch: pytest.MonkeyPatch, token_count: int
) -> None:
    paths: list[str] = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        paths.append(http_request.url.path)
        if http_request.url.path == "/info":
            return httpx.Response(200, json=info(), headers={"content-type": "application/json"})
        return token_response(token_count)

    install_transport(monkeypatch, handler)

    async def exercise() -> None:
        async with TeiEmbeddingProvider(config()) as provider:
            with pytest.raises(TeiProviderUnavailable, match="generation is unavailable"):
                await provider.embed(request("document"))

    asyncio.run(exercise())
    assert paths == ["/info", "/tokenize"]


def test_exact_token_boundary_passes_and_batch_overflow_never_embeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths: list[str] = []
    counts = iter((1024, 600, 425))

    def handler(http_request: httpx.Request) -> httpx.Response:
        paths.append(http_request.url.path)
        if http_request.url.path == "/info":
            return httpx.Response(200, json=info(), headers={"content-type": "application/json"})
        if http_request.url.path == "/tokenize":
            return token_response(next(counts))
        return httpx.Response(
            200,
            json=[[1.0] + [0.0] * 1023],
            headers={"content-type": "application/json"},
        )

    install_transport(monkeypatch, handler)

    async def exercise() -> None:
        async with TeiEmbeddingProvider(config()) as provider:
            assert len((await provider.embed(request("document"))).vectors) == 1
            with pytest.raises(TeiProviderUnavailable):
                await provider.embed(request("document", "query"))

    asyncio.run(exercise())
    assert paths == ["/info", "/tokenize", "/embed", "/tokenize", "/tokenize"]


@pytest.mark.parametrize(
    "bad_tokens",
    (
        [],
        [[]],
        {"tokens": []},
        [
            [
                {"id": 1, "text": "x", "special": True, "start": None, "stop": None},
                {"id": 1, "text": "x", "special": True, "start": None, "stop": None},
            ]
        ],
        [[{"id": 1, "text": "x", "special": False, "start": 0, "stop": None}]],
        [[{"id": 1, "text": "x", "special": False, "start": 2, "stop": 1}]],
        [[{"id": 1, "text": "x", "special": False, "start": None, "stop": None}]],
        [
            [
                {"id": 1, "text": "x", "special": False, "start": 0, "stop": 2},
                {"id": 2, "text": "y", "special": False, "start": 1, "stop": 3},
            ],
        ],
    ),
)
def test_malformed_duplicate_and_inconsistent_tokens_fail_safely(
    monkeypatch: pytest.MonkeyPatch, bad_tokens: object
) -> None:
    paths: list[str] = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        paths.append(http_request.url.path)
        if http_request.url.path == "/info":
            return httpx.Response(200, json=info(), headers={"content-type": "application/json"})
        return httpx.Response(200, json=bad_tokens, headers={"content-type": "application/json"})

    install_transport(monkeypatch, handler)

    async def exercise() -> None:
        async with TeiEmbeddingProvider(config()) as provider:
            with pytest.raises(TeiProviderUnavailable) as caught:
                await provider.embed(request("document"))
            assert "text 0" not in repr(caught.value)

    asyncio.run(exercise())
    assert paths == ["/info", "/tokenize"]


def test_raw_limits_and_oversized_tokenize_response_precede_embedding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths: list[str] = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        paths.append(http_request.url.path)
        if http_request.url.path == "/info":
            return httpx.Response(200, json=info(), headers={"content-type": "application/json"})
        return httpx.Response(
            200,
            content=b"[" + b" " * 4096 + b"]",
            headers={"content-type": "application/json"},
        )

    install_transport(monkeypatch, handler)

    async def exercise() -> None:
        async with TeiEmbeddingProvider(config(maximum_input_bytes=3)) as provider:
            with pytest.raises(TeiProviderUnavailable, match="request is invalid"):
                await provider.embed(request("document"))
        async with TeiEmbeddingProvider(config(maximum_tokenize_response_bytes=4096)) as provider:
            with pytest.raises(TeiProviderUnavailable):
                await provider.embed(request("document"))

    asyncio.run(exercise())
    assert paths == ["/info", "/info", "/tokenize"]


def test_tokenize_timeout_exception_and_cancellation_are_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure: BaseException = httpx.ReadTimeout("private input timeout")

    def handler(http_request: httpx.Request) -> httpx.Response:
        nonlocal failure
        if http_request.url.path == "/info":
            return httpx.Response(200, json=info(), headers={"content-type": "application/json"})
        raise failure

    install_transport(monkeypatch, handler)

    async def exercise() -> None:
        nonlocal failure
        provider = TeiEmbeddingProvider(config())
        await provider.open()
        with pytest.raises(TeiProviderUnavailable) as caught:
            await provider.embed(request("document"))
        assert "private input" not in str(caught.value)
        await provider.close()

        failure = asyncio.CancelledError()
        provider = TeiEmbeddingProvider(config())
        await provider.open()
        with pytest.raises(asyncio.CancelledError):
            await provider.embed(request("document"))
        await provider.close()

    asyncio.run(exercise())


def test_resource_policy_is_immutable_safe_and_not_public_input() -> None:
    policy = config().resource_policy
    assert policy.policy_sha256 == policy.policy_sha256
    with pytest.raises(ValidationError):
        policy.max_batch_tokens = 1  # type: ignore[misc]
    with pytest.raises(ValidationError):
        TeiResourcePolicy.model_validate(
            {
                **policy.model_dump(exclude={"policy_sha256"}),
                "max_batch_tokens": 2048,
            }
        )
    assert "input" not in repr(policy).lower()
    with pytest.raises(ValidationError):
        PublicChatRequest(message="safe", max_batch_tokens=1)  # type: ignore[call-arg]


def test_runtime_identity_distinguishes_configured_observed_and_public_data() -> None:
    identity = QWEN3_PINNED_RUNTIME_IDENTITY
    assert identity.configured_max_batch_requests == 1
    assert identity.observed_max_batch_requests == 4
    assert identity.application_max_concurrent_requests == 1
    assert identity.application_execution_mode == "sequential"
    assert "Qwen" not in repr(identity)
    with pytest.raises(ValidationError):
        TeiRuntimeIdentity.model_validate(
            {
                **identity.model_dump(exclude={"identity_sha256"}),
                "observed_max_batch_requests": 1,
            }
        )
    with pytest.raises(ValidationError):
        PublicChatRequest(
            message="safe",
            runtime_identity=identity.model_dump(mode="json"),
        )  # type: ignore[call-arg]
