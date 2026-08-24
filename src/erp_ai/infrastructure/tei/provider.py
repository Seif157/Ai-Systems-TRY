"""Bounded async adapter for a pinned local Text Embeddings Inference service."""

import asyncio
import hashlib
import json
import math
from typing import Any, Literal, Self
from urllib.parse import urlsplit

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    computed_field,
    field_validator,
    model_validator,
)

from erp_ai.knowledge.embeddings import (
    EmbeddingBatchRequest,
    EmbeddingBatchResult,
    EmbeddingInputKind,
    EmbeddingVector,
)

QWEN3_QUERY_INSTRUCTION = (
    "Given a user question about HR policies and ERP product documentation, retrieve relevant "
    "passages that answer the question."
)


class TeiProviderUnavailable(RuntimeError):
    """Safe failure without remote payload or exception detail."""


class TeiResourcePolicy(BaseModel):
    """Immutable server-owned resource limits that do not alter accepted vectors."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    max_batch_tokens: Literal[1024]
    max_batch_requests: Literal[1]
    max_concurrent_requests: Literal[1]
    tokenization_workers: Literal[1]
    max_client_batch_size: int = Field(strict=True, ge=1, le=8)
    auto_truncate: Literal[True]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def policy_sha256(self) -> str:
        payload = json.dumps(
            self.model_dump(mode="json", exclude={"policy_sha256"}),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(payload).hexdigest()


class TeiRuntimeIdentity(BaseModel):
    """Pinned effective runtime identity, including configured/observed distinctions."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    model_id: Literal["Qwen/Qwen3-Embedding-0.6B"] = Field(repr=False)
    model_revision: Literal["97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3"] = Field(repr=False)
    tei_version: Literal["1.9.3"]
    model_dtype: Literal["float32"]
    pooling: Literal["last_token"]
    dimensions: Literal[1024]
    max_batch_tokens: Literal[1024]
    max_client_batch_size: Literal[4]
    auto_truncate: Literal[True]
    tokenization_workers: Literal[1]
    configured_max_batch_requests: Literal[1]
    observed_max_batch_requests: Literal[4]
    application_max_concurrent_requests: Literal[1]
    application_execution_mode: Literal["sequential"]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def identity_sha256(self) -> str:
        payload = json.dumps(
            self.model_dump(mode="json", exclude={"identity_sha256"}),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(payload).hexdigest()


QWEN3_LOCAL_TEST_RESOURCE_POLICY = TeiResourcePolicy(
    max_batch_tokens=1024,
    max_batch_requests=1,
    max_concurrent_requests=1,
    tokenization_workers=1,
    max_client_batch_size=4,
    auto_truncate=True,
)
QWEN3_PINNED_RUNTIME_IDENTITY = TeiRuntimeIdentity(
    model_id="Qwen/Qwen3-Embedding-0.6B",
    model_revision="97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3",
    tei_version="1.9.3",
    model_dtype="float32",
    pooling="last_token",
    dimensions=1024,
    max_batch_tokens=1024,
    max_client_batch_size=4,
    auto_truncate=True,
    tokenization_workers=1,
    configured_max_batch_requests=1,
    observed_max_batch_requests=4,
    application_max_concurrent_requests=1,
    application_execution_mode="sequential",
)


class TeiEmbeddingProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    endpoint: str = Field(repr=False)
    api_key: SecretStr = Field(repr=False)
    expected_model_id: str = Field(min_length=1, repr=False)
    expected_model_revision: str = Field(pattern=r"^[0-9a-f]{40}$", repr=False)
    expected_tei_version_minimum: str = Field(pattern=r"^1\.9\.\d+$")
    expected_tei_version_maximum: str = Field(pattern=r"^1\.9\.\d+$")
    expected_pooling: Literal["last-token"]
    dimensions: Literal[1024]
    connect_timeout_seconds: float = Field(strict=True, gt=0, le=60)
    read_timeout_seconds: float = Field(strict=True, gt=0, le=300)
    write_timeout_seconds: float = Field(strict=True, gt=0, le=60)
    pool_timeout_seconds: float = Field(strict=True, gt=0, le=60)
    maximum_response_bytes: int = Field(strict=True, ge=4096, le=16_777_216)
    maximum_tokenize_response_bytes: int = Field(strict=True, ge=4096, le=1_048_576)
    maximum_input_characters: int = Field(strict=True, ge=1, le=4000)
    maximum_input_bytes: int = Field(strict=True, ge=1, le=16_000)
    resource_policy: TeiResourcePolicy
    local_testing_mode: Literal[True]

    @field_validator("endpoint")
    @classmethod
    def exact_loopback_endpoint(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
            or parsed.port is None
        ):
            raise ValueError("local TEI endpoint must be an exact loopback HTTP origin")
        return value.rstrip("/")

    @model_validator(mode="after")
    def ordered_version_range(self) -> Self:
        if _version(self.expected_tei_version_minimum) > _version(
            self.expected_tei_version_maximum
        ):
            raise ValueError("TEI version range is invalid")
        return self


class _EmbeddingModelInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    pooling: Literal["last_token"]


class _ModelTypeInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    embedding: _EmbeddingModelInfo


class _TeiInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    model_id: str
    model_sha: str
    model_dtype: str
    served_model_name: str
    model_type: _ModelTypeInfo
    max_concurrent_requests: int
    max_input_length: int
    max_batch_tokens: int
    max_batch_requests: int | None
    max_client_batch_size: int
    auto_truncate: bool
    tokenization_workers: int
    version: str
    sha: str | None
    docker_label: str | None


class _Token(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: int = Field(strict=True, ge=0)
    text: str = Field(strict=True, repr=False)
    special: bool
    start: int | None = Field(default=None, strict=True, ge=0)
    stop: int | None = Field(default=None, strict=True, ge=0)

    @model_validator(mode="after")
    def consistent_offsets(self) -> Self:
        if (self.start is None) != (self.stop is None):
            raise ValueError("token offsets are inconsistent")
        if self.start is not None and self.stop is not None and self.stop < self.start:
            raise ValueError("token offsets are inconsistent")
        return self


def _version(value: str) -> tuple[int, int, int]:
    return tuple(int(item) for item in value.split("."))  # type: ignore[return-value]


class TeiEmbeddingProvider:
    __slots__ = ("_client", "_config", "_opened", "_runtime_identity")

    def __init__(self, config: TeiEmbeddingProviderConfig) -> None:
        self._config = config
        self._client: httpx.AsyncClient | None = None
        self._opened = False
        self._runtime_identity: TeiRuntimeIdentity | None = None

    @property
    def runtime_identity(self) -> TeiRuntimeIdentity:
        if self._runtime_identity is None:
            raise TeiProviderUnavailable("embedding provider identity is unavailable")
        return self._runtime_identity

    async def __aenter__(self) -> Self:
        await self.open()
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.close()

    async def open(self) -> None:
        if self._opened:
            raise TeiProviderUnavailable("embedding provider lifecycle is invalid")
        timeout = httpx.Timeout(
            connect=self._config.connect_timeout_seconds,
            read=self._config.read_timeout_seconds,
            write=self._config.write_timeout_seconds,
            pool=self._config.pool_timeout_seconds,
        )
        self._client = httpx.AsyncClient(
            base_url=self._config.endpoint,
            headers={"Authorization": f"Bearer {self._config.api_key.get_secret_value()}"},
            timeout=timeout,
            trust_env=False,
            follow_redirects=False,
        )
        try:
            payload = await self._request("GET", "/info")
            info = _TeiInfo.model_validate_json(payload)
            runtime_identity = self._validate_info(info)
        except asyncio.CancelledError:
            await self.close()
            raise
        except Exception:
            await self.close()
            raise TeiProviderUnavailable("embedding provider identity is unavailable") from None
        self._opened = True
        self._runtime_identity = runtime_identity

    async def close(self) -> None:
        client, self._client, self._opened = self._client, None, False
        self._runtime_identity = None
        if client is not None:
            await client.aclose()

    async def embed(self, request: EmbeddingBatchRequest) -> EmbeddingBatchResult:
        if not self._opened or self._client is None:
            raise TeiProviderUnavailable("embedding provider is unavailable")
        if len(request.inputs) > self._config.resource_policy.max_client_batch_size:
            raise TeiProviderUnavailable("embedding request is invalid")
        if request.profile.dimensions != self._config.dimensions:
            raise TeiProviderUnavailable("embedding profile is incompatible")
        transformed = tuple(
            self._transform(item.input_kind, item.text, request) for item in request.inputs
        )
        try:
            total_tokens = 0
            for text in transformed:
                token_count = await self._token_count(text)
                if token_count > self._config.resource_policy.max_batch_tokens:
                    raise ValueError
                total_tokens += token_count
                if total_tokens > self._config.resource_policy.max_batch_tokens:
                    raise ValueError
            vectors = []
            for item, text in zip(request.inputs, transformed, strict=True):
                raw = await self._request(
                    "POST",
                    "/embed",
                    json_body={"inputs": [text], "truncate": False, "normalize": True},
                )
                decoded = json.loads(raw)
                if (
                    not isinstance(decoded, list)
                    or len(decoded) != 1
                    or not isinstance(decoded[0], list)
                ):
                    raise ValueError
                vectors.append(
                    EmbeddingVector(
                        input_id=item.input_id,
                        values=self._validated_vector(decoded[0]),
                    )
                )
            return EmbeddingBatchResult(
                profile_sha256=request.profile.profile_sha256, vectors=tuple(vectors)
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            raise TeiProviderUnavailable("embedding generation is unavailable") from None

    def _transform(
        self, kind: EmbeddingInputKind, text: str, request: EmbeddingBatchRequest
    ) -> str:
        if (
            len(text) > self._config.maximum_input_characters
            or len(text.encode("utf-8")) > self._config.maximum_input_bytes
        ):
            raise TeiProviderUnavailable("embedding request is invalid")
        if kind is EmbeddingInputKind.DOCUMENT:
            return text
        if request.profile.query_instruction != QWEN3_QUERY_INSTRUCTION:
            raise TeiProviderUnavailable("embedding profile is incompatible")
        return f"Instruct: {QWEN3_QUERY_INSTRUCTION}\nQuery: {text}"

    async def _token_count(self, transformed: str) -> int:
        raw = await self._request(
            "POST",
            "/tokenize",
            json_body={"inputs": transformed, "add_special_tokens": True},
            maximum_bytes=self._config.maximum_tokenize_response_bytes,
        )
        decoded = json.loads(raw)
        if (
            not isinstance(decoded, list)
            or len(decoded) != 1
            or not isinstance(decoded[0], list)
            or not decoded[0]
        ):
            raise ValueError
        tokens = tuple(_Token.model_validate(item) for item in decoded[0])
        identities = tuple(
            (item.id, item.text, item.special, item.start, item.stop) for item in tokens
        )
        if len(set(identities)) != len(identities):
            raise ValueError
        previous_stop = 0
        for token in tokens:
            if token.start is None or token.stop is None:
                if not token.special:
                    raise ValueError
                continue
            if token.start < previous_stop:
                raise ValueError
            previous_stop = token.stop
        return len(tokens)

    def _validated_vector(self, value: Any) -> tuple[float, ...]:
        if not isinstance(value, list) or len(value) != self._config.dimensions:
            raise ValueError
        vector = EmbeddingVector(input_id="validation", values=tuple(value)).values
        norm = math.sqrt(sum(item * item for item in vector))
        if not math.isclose(norm, 1.0, rel_tol=1e-4, abs_tol=1e-4):
            raise ValueError
        return vector

    def _validate_info(self, info: _TeiInfo) -> TeiRuntimeIdentity:
        version = _version(info.version)
        if (
            info.model_id != self._config.expected_model_id
            or info.model_sha != self._config.expected_model_revision
            or not _version(self._config.expected_tei_version_minimum)
            <= version
            <= _version(self._config.expected_tei_version_maximum)
            or info.model_type.embedding.pooling.replace("_", "-") != self._config.expected_pooling
            or info.model_dtype != "float32"
            or info.auto_truncate is not self._config.resource_policy.auto_truncate
            or info.max_input_length < self._config.resource_policy.max_batch_tokens
            or info.max_batch_tokens != self._config.resource_policy.max_batch_tokens
            or info.max_concurrent_requests != self._config.resource_policy.max_concurrent_requests
            or info.max_client_batch_size != self._config.resource_policy.max_client_batch_size
            or info.tokenization_workers != self._config.resource_policy.tokenization_workers
        ):
            raise ValueError
        return TeiRuntimeIdentity.model_validate(
            {
                "model_id": info.model_id,
                "model_revision": info.model_sha,
                "tei_version": info.version,
                "model_dtype": info.model_dtype,
                "pooling": info.model_type.embedding.pooling,
                "dimensions": self._config.dimensions,
                "max_batch_tokens": info.max_batch_tokens,
                "max_client_batch_size": info.max_client_batch_size,
                "auto_truncate": info.auto_truncate,
                "tokenization_workers": info.tokenization_workers,
                "configured_max_batch_requests": (self._config.resource_policy.max_batch_requests),
                "observed_max_batch_requests": info.max_batch_requests,
                "application_max_concurrent_requests": (
                    self._config.resource_policy.max_concurrent_requests
                ),
                "application_execution_mode": "sequential",
            }
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: object | None = None,
        maximum_bytes: int | None = None,
    ) -> bytes:
        if self._client is None:
            raise TeiProviderUnavailable("embedding provider is unavailable")
        request = self._client.build_request(method, path, json=json_body)
        response = await self._client.send(request, stream=True)
        try:
            if (
                response.status_code != 200
                or response.headers.get("content-type", "").split(";")[0] != "application/json"
            ):
                raise ValueError
            chunks = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > (maximum_bytes or self._config.maximum_response_bytes):
                    raise ValueError
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            await response.aclose()
