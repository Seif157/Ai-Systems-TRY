"""Fixed-origin bounded HTTP client for approved OpenAI endpoints."""

import asyncio
import json
import ssl
from typing import Protocol

import httpx
from pydantic import SecretStr

from .config import OpenAIProjectRoute
from .contracts import OPENAI_ALLOWED_ENDPOINTS, OPENAI_ORIGIN
from .credentials import OpenAICredentialProvider
from .errors import OpenAIProviderUnavailable


class OpenAITransportFactory(Protocol):
    """Private test seam; production composition supplies no implementation."""

    def create(self) -> httpx.AsyncBaseTransport: ...


def strict_json_loads(raw: bytes) -> object:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def reject_constant(_: str) -> object:
        raise ValueError("non-finite JSON")

    return json.loads(
        raw.decode("utf-8", errors="strict"),
        object_pairs_hook=pairs,
        parse_constant=reject_constant,
    )


class OpenAIHttpClient:  # pragma: no cover - bounded external HTTP boundary
    __slots__ = ("_client", "_credential_provider", "_lock", "_ssl", "_state", "_transport")

    def __init__(
        self,
        credential_provider: OpenAICredentialProvider,
        ssl_context: ssl.SSLContext,
        *,
        _transport_factory: OpenAITransportFactory | None = None,
    ) -> None:
        if not isinstance(credential_provider, OpenAICredentialProvider):
            raise TypeError("OpenAI credential provider is required")
        if not isinstance(ssl_context, ssl.SSLContext):
            raise TypeError("OpenAI SSL context is required")
        self._credential_provider = credential_provider
        self._ssl = ssl_context
        self._transport = _transport_factory
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()
        self._state = "created"

    async def open(self) -> None:
        async with self._lock:
            if self._state == "ready":
                return
            if self._state != "created":
                raise OpenAIProviderUnavailable
            self._state = "opening"
            try:
                if (
                    self._ssl.verify_mode != ssl.CERT_REQUIRED
                    or not self._ssl.check_hostname
                    or self._ssl.minimum_version < ssl.TLSVersion.TLSv1_2
                ):
                    raise ValueError
                transport = self._transport.create() if self._transport is not None else None
                self._client = httpx.AsyncClient(
                    base_url=OPENAI_ORIGIN,
                    verify=self._ssl,
                    transport=transport,
                    trust_env=False,
                    follow_redirects=False,
                    headers={"Accept-Encoding": "identity", "Accept": "application/json"},
                    limits=httpx.Limits(max_connections=8, max_keepalive_connections=8),
                )
            except Exception:
                self._state = "failed"
                raise OpenAIProviderUnavailable from None
            self._state = "ready"

    async def close(self) -> None:
        async with self._lock:
            if self._state == "closed":
                return
            client, self._client = self._client, None
            self._state = "closed"
            if client is not None:
                await client.aclose()

    async def post(self, route: OpenAIProjectRoute, path: str, body: bytes) -> bytes:
        if path not in OPENAI_ALLOWED_ENDPOINTS or self._state != "ready" or self._client is None:
            raise OpenAIProviderUnavailable
        if len(body) > route.limits.maximum_request_bytes:
            raise OpenAIProviderUnavailable
        try:
            credential = await self._credential_provider.resolve(
                route.credential_reference, route.organization_id, route.project_id
            )
            if type(credential) is not SecretStr:
                raise ValueError
            token = credential.get_secret_value()
            if (
                not token
                or len(token) > 4096
                or token != token.strip()
                or any(
                    character.isspace() or ord(character) < 0x20 or ord(character) == 0x7F
                    for character in token
                )
            ):
                raise ValueError
            headers = {
                "Authorization": f"Bearer {token}",
                "OpenAI-Organization": route.organization_id,
                "OpenAI-Project": route.project_id,
                "Content-Type": "application/json; charset=utf-8",
                "Content-Length": str(len(body)),
            }
            timeout = httpx.Timeout(
                connect=route.limits.connect_timeout_seconds,
                read=route.limits.read_timeout_seconds,
                write=route.limits.write_timeout_seconds,
                pool=route.limits.pool_timeout_seconds,
            )
            request = self._client.build_request(
                "POST", path, headers=headers, content=body, timeout=timeout
            )
            response = await self._client.send(request, stream=True)
            try:
                if response.status_code < 200 or response.status_code >= 300:
                    await self._discard(response, route.limits.maximum_response_bytes)
                    raise OpenAIProviderUnavailable
                if response.headers.get("content-encoding") not in (None, "identity"):
                    raise OpenAIProviderUnavailable
                if response.headers.get_list("set-cookie"):
                    raise OpenAIProviderUnavailable
                content_types = response.headers.get_list("content-type")
                lengths = response.headers.get_list("content-length")
                transfer_encodings = response.headers.get_list("transfer-encoding")
                if len(content_types) != 1 or len(lengths) > 1 or len(transfer_encodings) > 1:
                    raise OpenAIProviderUnavailable
                if lengths and transfer_encodings:
                    raise OpenAIProviderUnavailable
                content_type_parts = [item.strip().lower() for item in content_types[0].split(";")]
                media_type = content_type_parts[0]
                if media_type != "application/json":
                    raise OpenAIProviderUnavailable
                if any(
                    item and item not in ("charset=utf-8", "charset=utf8")
                    for item in content_type_parts[1:]
                ):
                    raise OpenAIProviderUnavailable
                length = lengths[0] if lengths else None
                if length is not None and (
                    not length.isascii()
                    or not length.isdigit()
                    or int(length) > route.limits.maximum_response_bytes
                ):
                    raise OpenAIProviderUnavailable
                return await self._read(response, route.limits.maximum_response_bytes)
            finally:
                await response.aclose()
        except asyncio.CancelledError:
            raise
        except OpenAIProviderUnavailable:
            raise
        except Exception:
            raise OpenAIProviderUnavailable from None

    @staticmethod
    async def _read(response: httpx.Response, maximum: int) -> bytes:
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > maximum:
                raise OpenAIProviderUnavailable
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    async def _discard(response: httpx.Response, maximum: int) -> None:
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > maximum:
                break
