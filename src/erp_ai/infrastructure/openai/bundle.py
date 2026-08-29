"""Explicit lifecycle and immutable direct-OpenAI provider bundle."""

import asyncio
import ssl
from dataclasses import dataclass, field

from erp_ai.application import TrustedClock
from erp_ai.context.models import Identifier

from .client import OpenAIHttpClient, OpenAITransportFactory
from .config import OpenAIProductionConfig
from .credentials import OpenAICredentialProvider
from .embedding_provider import OpenAIEmbeddingProvider
from .errors import OpenAIProviderUnavailable
from .model_provider import OpenAIResponsesModelProvider
from .privacy import OpenAIProjectRouter


class OpenAIProviderLifecycle:  # pragma: no cover - external resource lifecycle
    __slots__ = ("_client", "_lock", "_state")

    def __init__(self, client: OpenAIHttpClient) -> None:
        self._client = client
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
                await self._client.open()
            except asyncio.CancelledError:
                await self._client.close()
                self._state = "failed"
                raise
            except Exception:
                await self._client.close()
                self._state = "failed"
                raise OpenAIProviderUnavailable from None
            self._state = "ready"

    async def close(self) -> None:
        async with self._lock:
            if self._state == "closed":
                return
            try:
                await self._client.close()
            finally:
                self._state = "closed"


@dataclass(frozen=True, slots=True)
class OpenAIProductionBundle:
    router: OpenAIProjectRouter = field(repr=False)
    model_provider: OpenAIResponsesModelProvider = field(repr=False)
    lifecycle: OpenAIProviderLifecycle = field(repr=False)
    _client: OpenAIHttpClient = field(repr=False)

    def embedding_provider(
        self, customer_environment_id: Identifier, purpose: str
    ) -> OpenAIEmbeddingProvider:
        return OpenAIEmbeddingProvider(
            router=self.router,
            client=self._client,
            customer_environment_id=customer_environment_id,
            purpose=purpose,
        )


def build_openai_production_bundle(
    *,
    config: OpenAIProductionConfig,
    credential_provider: OpenAICredentialProvider,
    clock: TrustedClock,
    ssl_context: ssl.SSLContext,
    _transport_factory: OpenAITransportFactory | None = None,
) -> OpenAIProductionBundle:
    """Pure construction; credentials and network are untouched until an operation."""

    router = OpenAIProjectRouter(config, clock)
    client = OpenAIHttpClient(
        credential_provider, ssl_context, _transport_factory=_transport_factory
    )
    return OpenAIProductionBundle(
        router=router,
        model_provider=OpenAIResponsesModelProvider(router=router, client=client),
        lifecycle=OpenAIProviderLifecycle(client),
        _client=client,
    )
