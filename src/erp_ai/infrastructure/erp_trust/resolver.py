"""Trusted resolver backed by one-time ERP references."""

import asyncio
import json
from dataclasses import dataclass, field

from erp_ai.application import TrustedRequestReference, TrustedResolution

from .errors import ErpTrustResolutionDenied, ErpTrustUnavailable
from .http_client import RESOLVE_PATH, ErpTrustHttpClient
from .models import ResolveRequest, ResolveResponse


@dataclass(frozen=True, slots=True)
class ErpTrustedRequestResolver:
    client: ErpTrustHttpClient = field(repr=False)

    async def resolve(self, reference: TrustedRequestReference) -> TrustedResolution:
        try:
            reference = TrustedRequestReference.model_validate(reference, strict=True)
            request = ResolveRequest(
                contract_version=1,
                request_id=reference.request_id,
                resolver_reference=reference.resolver_reference,
            )
            status, raw = await self.client.post_json(
                RESOLVE_PATH,
                {
                    "contract_version": 1,
                    "request_id": request.request_id,
                    "resolver_reference": request.resolver_reference.get_secret_value(),
                },
            )
            if status in (404, 409):
                raise ErpTrustResolutionDenied
            if status != 200:
                raise ErpTrustUnavailable
            response = ResolveResponse.model_validate_json(
                json.dumps(raw, ensure_ascii=False, separators=(",", ":")), strict=True
            )
            if response.request_id != reference.request_id:
                raise ErpTrustUnavailable
            resolution = TrustedResolution(
                context=response.trusted_request_context,
                intent=response.trusted_route_intent,
            )
            return TrustedResolution.model_validate(resolution, strict=True)
        except asyncio.CancelledError:
            raise
        except ErpTrustResolutionDenied:
            raise
        except ErpTrustUnavailable:
            raise
        except Exception:
            raise ErpTrustUnavailable from None
