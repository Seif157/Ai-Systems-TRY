"""Bounded lifecycle-managed mTLS HTTP client for fixed ERP trust endpoints."""

import asyncio
import json
import ssl
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import ErpTrustHttpConfig, validate_production_ssl_context
from .errors import ErpTrustUnavailable

RESOLVE_PATH = "/internal/ai/v1/resolve"
SNAPSHOT_VERIFY_PATH = "/internal/ai/v1/authorization-snapshots/verify"


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _constant(_: str) -> object:
    raise ValueError("invalid JSON number")


@dataclass(slots=True, init=False)
class ErpTrustHttpClient:
    config: ErpTrustHttpConfig = field(repr=False)
    _ssl_context: ssl.SSLContext | None = field(repr=False)
    _transport: httpx.AsyncBaseTransport | None = field(repr=False)
    _client: httpx.AsyncClient | None = field(default=None, repr=False)
    _closed: bool = field(default=False, repr=False)
    _lifecycle_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def __init__(
        self,
        config: ErpTrustHttpConfig,
        ssl_context: ssl.SSLContext | None,
        *,
        test_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        config = ErpTrustHttpConfig.model_validate(config, strict=True)
        if ssl_context is None:
            raise ValueError("ERP trust client requires an SSL context")
        validate_production_ssl_context(ssl_context)
        object.__setattr__(self, "config", config)
        object.__setattr__(self, "_ssl_context", ssl_context)
        object.__setattr__(self, "_transport", test_transport)
        object.__setattr__(self, "_client", None)
        object.__setattr__(self, "_closed", False)
        object.__setattr__(self, "_lifecycle_lock", asyncio.Lock())

    async def open(self) -> None:
        async with self._lifecycle_lock:
            if self._closed or self._client is not None:
                raise ErpTrustUnavailable
            if self._ssl_context is None:
                raise ErpTrustUnavailable
            try:
                validate_production_ssl_context(self._ssl_context)
            except Exception:
                self._closed = True
                raise ErpTrustUnavailable from None
            timeout = httpx.Timeout(
                connect=self.config.connect_timeout_seconds,
                read=self.config.read_timeout_seconds,
                write=self.config.write_timeout_seconds,
                pool=self.config.pool_timeout_seconds,
            )
            try:
                client = httpx.AsyncClient(
                    base_url=self.config.origin.get_secret_value(),
                    verify=self._ssl_context if self._ssl_context is not None else True,
                    transport=self._transport,
                    timeout=timeout,
                    limits=httpx.Limits(
                        max_connections=self.config.maximum_connections,
                        max_keepalive_connections=self.config.maximum_keepalive_connections,
                    ),
                    follow_redirects=False,
                    trust_env=False,
                    headers={"Accept": "application/json", "Accept-Encoding": "identity"},
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                self._closed = True
                raise ErpTrustUnavailable from None
            self._client = client

    async def close(self) -> None:
        async with self._lifecycle_lock:
            client, self._client = self._client, None
            self._closed = True
        if client is not None:
            await client.aclose()

    async def post_json(self, path: str, payload: dict[str, object]) -> tuple[int, object]:
        client = self._client
        if path not in (RESOLVE_PATH, SNAPSHOT_VERIFY_PATH) or client is None or self._closed:
            raise ErpTrustUnavailable
        try:
            body = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ).encode()
            request = client.build_request(
                "POST", path, content=body, headers={"Content-Type": "application/json"}
            )
            expected_origin = httpx.URL(self.config.origin.get_secret_value())
            if (
                request.url.scheme != expected_origin.scheme
                or request.url.host != expected_origin.host
                or request.url.port != expected_origin.port
                or request.url.path != path
                or request.url.query
            ):
                raise ErpTrustUnavailable
            response = await client.send(request, stream=True)
            try:
                content_types = response.headers.get_list("content-type")
                if len(content_types) != 1:
                    raise ErpTrustUnavailable
                content_type = content_types[0].split(";", 1)[0].strip().lower()
                if "set-cookie" in response.headers:
                    raise ErpTrustUnavailable
                if response.headers.get("content-encoding") not in (None, "identity"):
                    raise ErpTrustUnavailable
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_raw():
                    size += len(chunk)
                    if size > self.config.maximum_response_bytes:
                        raise ErpTrustUnavailable
                    chunks.append(chunk)
                raw = b"".join(chunks)
                if content_type != "application/json":
                    raise ErpTrustUnavailable
                value: Any = json.loads(
                    raw.decode("utf-8", errors="strict"),
                    object_pairs_hook=_pairs,
                    parse_constant=_constant,
                )
                return response.status_code, value
            finally:
                client.cookies.clear()
                await response.aclose()
        except asyncio.CancelledError:
            raise
        except ErpTrustUnavailable:
            raise
        except Exception:
            raise ErpTrustUnavailable from None
