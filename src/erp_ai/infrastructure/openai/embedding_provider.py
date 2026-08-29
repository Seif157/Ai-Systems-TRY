"""Customer-bound OpenAI Embeddings API provider."""

import asyncio
import hashlib
import json
import math
from dataclasses import dataclass, field

from erp_ai.context.models import Identifier
from erp_ai.knowledge.embeddings import (
    EmbeddingBatchRequest,
    EmbeddingBatchResult,
    EmbeddingInputKind,
    EmbeddingProvider,
    EmbeddingVector,
)

from .client import OpenAIHttpClient, strict_json_loads
from .contracts import OPENAI_EMBEDDINGS_PATH
from .errors import OpenAIProviderUnavailable
from .privacy import OpenAIProjectRouter


@dataclass(frozen=True, slots=True)
class OpenAIEmbeddingProvider(EmbeddingProvider):  # pragma: no cover - provider boundary
    """One immutable customer/purpose binding satisfying the existing protocol."""

    router: OpenAIProjectRouter = field(repr=False)
    client: OpenAIHttpClient = field(repr=False)
    customer_environment_id: Identifier = field(repr=False)
    purpose: str = field(repr=False)

    async def embed(self, request: EmbeddingBatchRequest) -> EmbeddingBatchResult:
        try:
            request = EmbeddingBatchRequest.model_validate(request, strict=True)
            if len(request.inputs) != 1:
                raise OpenAIProviderUnavailable
            item = request.inputs[0]
            if (
                item.input_kind is not EmbeddingInputKind.QUERY
                or item.data_classification not in request.profile.allowed_data_classifications
                or hashlib.sha256(item.text.encode("utf-8")).hexdigest() != item.content_sha256
            ):
                raise OpenAIProviderUnavailable
            approved = self.router.authorize(
                self.customer_environment_id,
                item.data_classification,
                self.purpose,
                OPENAI_EMBEDDINGS_PATH,
            )
            route = approved.route
            if (
                request.profile.provider_id != "openai"
                or request.profile.model_id != route.embedding_model
                or request.profile.model_revision != route.embedding_revision
                or request.profile.dimensions != route.embedding_dimensions
            ):
                raise OpenAIProviderUnavailable
            transformed = f"Instruct: {request.profile.query_instruction}\nQuery: {item.text}"
            body = json.dumps(
                {
                    "model": route.embedding_model,
                    "input": transformed,
                    "dimensions": route.embedding_dimensions,
                    "encoding_format": "float",
                },
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            if (
                len(body) > route.limits.maximum_input_bytes
                or len(body) > route.limits.maximum_input_tokens
            ):
                raise OpenAIProviderUnavailable
            raw = await self.client.post(route, OPENAI_EMBEDDINGS_PATH, body)
            root = strict_json_loads(raw)
            if not isinstance(root, dict) or root.get("model") != route.embedding_model:
                raise OpenAIProviderUnavailable
            data = root.get("data")
            if not isinstance(data, list) or len(data) != 1:
                raise OpenAIProviderUnavailable
            value = data[0]
            if (
                not isinstance(value, dict)
                or set(value) != {"object", "index", "embedding"}
                or value.get("object") != "embedding"
                or type(value.get("index")) is not int
                or value.get("index") != 0
            ):
                raise OpenAIProviderUnavailable
            vector_raw = value.get("embedding")
            if not isinstance(vector_raw, list) or len(vector_raw) != route.embedding_dimensions:
                raise OpenAIProviderUnavailable
            if any(type(number) not in (int, float) for number in vector_raw):
                raise OpenAIProviderUnavailable
            vector = EmbeddingVector(input_id=item.input_id, values=tuple(vector_raw))
            norm = math.sqrt(sum(number * number for number in vector.values))
            if not math.isfinite(norm) or norm == 0:
                raise OpenAIProviderUnavailable
            return EmbeddingBatchResult(
                profile_sha256=request.profile.profile_sha256, vectors=(vector,)
            )
        except asyncio.CancelledError:
            raise
        except OpenAIProviderUnavailable:
            raise
        except Exception:
            raise OpenAIProviderUnavailable from None
