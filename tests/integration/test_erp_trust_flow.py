"""Synthetic adapter integration without external network or production secrets."""

import asyncio
import base64
import json
import ssl
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import SecretBytes, SecretStr

from erp_ai.infrastructure.erp_trust import (
    ErpAssertionVerificationKey,
    ErpAssertionVerifierConfig,
    ErpAuthorizationSnapshotVerifier,
    ErpSignedAssertionAuthenticator,
    ErpTrustedRequestResolver,
    ErpTrustHttpClient,
    ErpTrustHttpConfig,
)
from erp_ai.transport.http import TrustedIngressAuthenticationRequest


class AsyncBody(httpx.AsyncByteStream):
    def __init__(self, value: bytes) -> None:
        self.value = value

    async def __aiter__(self):  # type: ignore[no-untyped-def]
        yield self.value


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def test_signed_reference_resolution_and_snapshot_verification_flow() -> None:
    now = datetime(2026, 8, 27, 12, tzinfo=UTC)
    request_id = "123e4567-e89b-42d3-a456-426614174000"
    resolver_reference = _b64(b"s" * 32)
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )

    class Clock:
        def now(self) -> datetime:
            return now

    config = ErpAssertionVerifierConfig(
        issuer=SecretStr("erp-test"),
        audience=SecretStr("ai-test"),
        keys=[
            ErpAssertionVerificationKey(
                kid="test_key",
                public_key=SecretBytes(public),
                activates_at=now - timedelta(hours=1),
                retires_at=now + timedelta(hours=1),
            )
        ],
        maximum_lifetime=timedelta(seconds=60),
        maximum_clock_skew=timedelta(seconds=5),
    )
    header = {"alg": "EdDSA", "kid": "test_key", "typ": "erp-ai-request+jws"}
    payload = {
        "v": 1,
        "iss": "erp-test",
        "aud": "ai-test",
        "jti": str(uuid4()),
        "iat": int(now.timestamp()),
        "exp": int(now.timestamp()) + 60,
        "method": "POST",
        "path": "/v1/chat",
        "body_sha256": "a" * 64,
        "resolver_ref": resolver_reference,
    }
    first = _b64(json.dumps(header, separators=(",", ":")).encode())
    second = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{first}.{second}".encode()
    assertion = f"{first}.{second}.{_b64(private.sign(signing_input))}"

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/resolve"):
            response = {
                "contract_version": 1,
                "request_id": request_id,
                "trusted_request_context": {
                    "context_version": 1,
                    "request_id": request_id,
                    "customer_environment_id": "synthetic_customer",
                    "user_id": "synthetic_user",
                    "employee_id": None,
                    "roles": ["employee"],
                    "permission_codes": [],
                    "legal_entity_ids": ["synthetic_entity"],
                    "enabled_modules": [],
                    "locale": "en",
                    "timezone": "Africa/Cairo",
                    "purpose": "general",
                    "issued_at": now.isoformat(),
                    "authorization_snapshot_id": "synthetic_snapshot",
                },
                "trusted_route_intent": {
                    "intent_contract_version": 1,
                    "intent_code": "general",
                    "issued_at": now.isoformat(),
                    "expires_at": (now + timedelta(seconds=30)).isoformat(),
                    "request_id": request_id,
                    "customer_environment_id": "synthetic_customer",
                    "user_id": "synthetic_user",
                    "authorization_snapshot_id": "synthetic_snapshot",
                },
            }
        else:
            response = {
                "contract_version": 1,
                "request_id": request_id,
                "customer_environment_id": "synthetic_customer",
                "user_id": "synthetic_user",
                "authorization_snapshot_id": "synthetic_snapshot",
                "status": "current",
            }
        return httpx.Response(
            200,
            stream=AsyncBody(json.dumps(response, separators=(",", ":")).encode()),
            headers={"content-type": "application/json"},
        )

    async def run() -> None:
        reference = await ErpSignedAssertionAuthenticator(config, Clock()).authenticate(
            TrustedIngressAuthenticationRequest(
                request_id=request_id,
                method="POST",
                route_path="/v1/chat",
                body_digest_sha256="a" * 64,
                bearer_assertion=SecretStr(assertion),
            )
        )
        client = ErpTrustHttpClient(
            ErpTrustHttpConfig(
                origin=SecretStr("https://erp.invalid"),
                contract_version=1,
                connect_timeout_seconds=1.0,
                read_timeout_seconds=1.0,
                write_timeout_seconds=1.0,
                pool_timeout_seconds=1.0,
                maximum_connections=1,
                maximum_keepalive_connections=1,
                maximum_response_bytes=16384,
            ),
            ssl.create_default_context(),
            test_transport=httpx.MockTransport(handler),
        )
        await client.open()
        resolution = await ErpTrustedRequestResolver(client).resolve(reference)
        decision = await ErpAuthorizationSnapshotVerifier(client).verify(resolution.context)
        assert decision.status == "current"
        await client.close()

    asyncio.run(run())
