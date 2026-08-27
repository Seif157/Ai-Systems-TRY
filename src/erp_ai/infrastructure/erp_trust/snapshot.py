"""Mandatory ERP authorization-snapshot verifier."""

import asyncio
from dataclasses import dataclass, field

from erp_ai.application import AuthorizationSnapshotDecision
from erp_ai.context import TrustedRequestContext

from .errors import SnapshotVerificationUnavailable
from .http_client import SNAPSHOT_VERIFY_PATH, ErpTrustHttpClient
from .models import SnapshotVerifyRequest, SnapshotVerifyResponse


@dataclass(frozen=True, slots=True)
class ErpAuthorizationSnapshotVerifier:
    client: ErpTrustHttpClient = field(repr=False)

    async def verify(self, context: TrustedRequestContext) -> AuthorizationSnapshotDecision:
        try:
            context = TrustedRequestContext.model_validate(
                context.model_dump(mode="python"), strict=True
            )
            request = SnapshotVerifyRequest(
                contract_version=1,
                request_id=context.request_id,
                customer_environment_id=context.customer_environment_id,
                user_id=context.user_id,
                authorization_snapshot_id=context.authorization_snapshot_id,
            )
            status, raw = await self.client.post_json(
                SNAPSHOT_VERIFY_PATH, request.model_dump(mode="json")
            )
            if status != 200:
                raise SnapshotVerificationUnavailable
            response = SnapshotVerifyResponse.model_validate(raw, strict=True)
            bindings = (
                response.request_id == context.request_id,
                response.customer_environment_id == context.customer_environment_id,
                response.user_id == context.user_id,
                response.authorization_snapshot_id == context.authorization_snapshot_id,
            )
            if not all(bindings):
                raise SnapshotVerificationUnavailable
            decision = AuthorizationSnapshotDecision(
                status=response.status,
                request_id=response.request_id,
                customer_environment_id=response.customer_environment_id,
                user_id=response.user_id,
                authorization_snapshot_id=response.authorization_snapshot_id,
            )
            return AuthorizationSnapshotDecision.model_validate(decision, strict=True)
        except asyncio.CancelledError:
            raise
        except SnapshotVerificationUnavailable:
            raise
        except Exception:
            raise SnapshotVerificationUnavailable from None
