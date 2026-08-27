import asyncio
import base64
import gzip
import json
import ssl
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import SecretBytes, SecretStr, ValidationError

from erp_ai.application import TrustedRequestReference
from erp_ai.infrastructure.erp_trust import (
    ErpAssertionVerificationKey,
    ErpAssertionVerifierConfig,
    ErpAuthorizationSnapshotVerifier,
    ErpSignedAssertionAuthenticator,
    ErpTrustedRequestResolver,
    ErpTrustHttpClient,
    ErpTrustHttpConfig,
    ErpTrustResolutionDenied,
    ErpTrustUnavailable,
    SnapshotVerificationUnavailable,
)
from erp_ai.infrastructure.erp_trust.assertions import (
    HEADER_FIELDS,
    PAYLOAD_FIELDS,
    decode_segment,
    parse_compact_jws,
    strict_object,
)
from erp_ai.infrastructure.erp_trust.config import decode_public_key
from erp_ai.transport.http import TrustedIngressAuthenticationRequest
from erp_ai.transport.http.errors import IngressAuthenticationDenied

NOW = datetime(2026, 8, 27, 12, tzinfo=UTC)
REQUEST_ID = "123e4567-e89b-42d3-a456-426614174000"
REFERENCE = base64.urlsafe_b64encode(b"r" * 32).rstrip(b"=").decode()


class Clock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return self.value


class AsyncChunks(httpx.AsyncByteStream):
    def __init__(self, *chunks: bytes) -> None:
        self.chunks = chunks

    async def __aiter__(self):  # type: ignore[no-untyped-def]
        for chunk in self.chunks:
            yield chunk


def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def key_config() -> tuple[Ed25519PrivateKey, ErpAssertionVerifierConfig]:
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    key = ErpAssertionVerificationKey(
        kid="erp_2026_a",
        public_key=SecretBytes(public),
        activates_at=NOW - timedelta(days=1),
        retires_at=NOW + timedelta(days=1),
    )
    return private, ErpAssertionVerifierConfig(
        issuer=SecretStr("https://erp.invalid"),
        audience=SecretStr("erp-ai"),
        keys=[key],
        maximum_lifetime=timedelta(seconds=60),
        maximum_clock_skew=timedelta(seconds=5),
    )


def payload(**updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "v": 1,
        "iss": "https://erp.invalid",
        "aud": "erp-ai",
        "jti": str(uuid4()),
        "iat": int(NOW.timestamp()),
        "exp": int(NOW.timestamp()) + 60,
        "method": "POST",
        "path": "/v1/chat",
        "body_sha256": "a" * 64,
        "resolver_ref": REFERENCE,
    }
    value.update(updates)
    return value


def token(private: Ed25519PrivateKey, body: dict[str, object], **header_updates: object) -> str:
    header: dict[str, object] = {"alg": "EdDSA", "kid": "erp_2026_a", "typ": "erp-ai-request+jws"}
    header.update(header_updates)
    first = b64(json.dumps(header, separators=(",", ":")).encode())
    second = b64(json.dumps(body, separators=(",", ":")).encode())
    signing_input = f"{first}.{second}".encode()
    return f"{first}.{second}.{b64(private.sign(signing_input))}"


def ingress(assertion: str) -> TrustedIngressAuthenticationRequest:
    return TrustedIngressAuthenticationRequest(
        request_id=REQUEST_ID,
        method="POST",
        route_path="/v1/chat",
        body_digest_sha256="a" * 64,
        bearer_assertion=SecretStr(assertion),
    )


def test_valid_assertion_returns_only_bound_opaque_reference() -> None:
    private, config = key_config()
    clock = Clock()
    authenticator = ErpSignedAssertionAuthenticator(config, clock)
    result = asyncio.run(authenticator.authenticate(ingress(token(private, payload()))))
    assert result.request_id == REQUEST_ID
    assert result.resolver_reference.get_secret_value() == REFERENCE
    assert set(result.model_dump()) == {"request_id", "resolver_reference"}
    assert REFERENCE not in repr(result)
    assert clock.calls == 1
    parsed = parse_compact_jws(token(private, payload()), 4096, 3072)
    assert REFERENCE not in repr(parsed)


def test_reference_contract_rejects_legacy_and_constructed_invalid_values() -> None:
    with pytest.raises(ValidationError):
        TrustedRequestReference.model_validate(
            {"request_id": REQUEST_ID, "resolver_handle": REFERENCE}, strict=True
        )
    for invalid in ("!" * 43, "a" * 43, "a" * 42 + "=", "é" * 43, "short"):
        with pytest.raises(ValidationError) as caught:
            TrustedRequestReference(request_id=REQUEST_ID, resolver_reference=SecretStr(invalid))
        if len(invalid) >= 43:
            assert invalid not in str(caught.value)
    constructed = TrustedRequestReference.model_construct(
        request_id=REQUEST_ID, resolver_reference=SecretStr("!" * 43)
    )
    with pytest.raises(ValidationError):
        TrustedRequestReference.model_validate(constructed, strict=True)
    valid = TrustedRequestReference(request_id=REQUEST_ID, resolver_reference=SecretStr(REFERENCE))
    assert valid.model_dump(mode="json")["resolver_reference"] == "**********"


@pytest.mark.parametrize(
    ("change", "header"),
    [
        ({"iss": "wrong"}, {}),
        ({"aud": "wrong"}, {}),
        ({"method": "GET"}, {}),
        ({"path": "/wrong"}, {}),
        ({"body_sha256": "b" * 64}, {}),
        ({"jti": "wrong"}, {}),
        ({"resolver_ref": "a" * 43}, {}),
        ({"v": True}, {}),
        ({"iat": 1.0}, {}),
        ({"exp": "1"}, {}),
        ({"extra": 1}, {}),
        ({}, {"alg": "none"}),
        ({}, {"alg": "HS256"}),
        ({}, {"alg": "RS256"}),
        ({}, {"alg": "ES256"}),
        ({}, {"alg": "eddsa"}),
        ({}, {"alg": " EdDSA"}),
        ({}, {"typ": "wrong"}),
        ({}, {"kid": "unknown"}),
        ({}, {"jku": "https://bad.invalid"}),
    ],
)
def test_assertion_claim_and_header_failures_are_generic(
    change: dict[str, object], header: dict[str, object]
) -> None:
    private, config = key_config()
    with pytest.raises(IngressAuthenticationDenied) as caught:
        asyncio.run(
            ErpSignedAssertionAuthenticator(config, Clock()).authenticate(
                ingress(token(private, payload(**change), **header))
            )
        )
    assert str(caught.value) == ""


@pytest.mark.parametrize(
    "change",
    [
        {"exp": int(NOW.timestamp())},
        {"iat": int(NOW.timestamp()) + 6, "exp": int(NOW.timestamp()) + 60},
        {"iat": int(NOW.timestamp()), "exp": int(NOW.timestamp()) + 61},
        {"iat": -1, "exp": 1},
    ],
)
def test_assertion_time_failures(change: dict[str, object]) -> None:
    private, config = key_config()
    with pytest.raises(IngressAuthenticationDenied):
        asyncio.run(
            ErpSignedAssertionAuthenticator(config, Clock()).authenticate(
                ingress(token(private, payload(**change)))
            )
        )


def test_tampering_invalid_clock_and_constructed_input_fail() -> None:
    private, config = key_config()
    valid = token(private, payload())
    tampered = valid[:-1] + ("A" if valid[-1] != "A" else "B")
    for request, clock in (
        (ingress(tampered), Clock()),
        (ingress(valid), Clock(datetime(2026, 1, 1))),
        (TrustedIngressAuthenticationRequest.model_construct(), Clock()),
    ):
        with pytest.raises(IngressAuthenticationDenied):
            asyncio.run(ErpSignedAssertionAuthenticator(config, clock).authenticate(request))


def test_parser_rejects_noncanonical_and_malformed_inputs() -> None:
    bad = (
        "a.b",
        "a.b.c.d",
        "=.a.a",
        "é.a.a",
        "a" * 5000,
    )
    for value in bad:
        with pytest.raises((ValueError, UnicodeEncodeError)):
            parse_compact_jws(value, 4096, 3072)
    for value in ("", "a=", "a+", "a" * 100):
        with pytest.raises(ValueError):
            decode_segment(value, 10)
    with pytest.raises(ValueError):
        decode_segment("AB", 10)
    with pytest.raises(ValueError):
        strict_object(b"\xef\xbb\xbf{}", HEADER_FIELDS)
    with pytest.raises((ValueError, UnicodeDecodeError)):
        strict_object(b"\xff", PAYLOAD_FIELDS)
    with pytest.raises(ValueError):
        strict_object(b'{"alg":"x","alg":"y"}', HEADER_FIELDS)
    with pytest.raises(ValueError):
        strict_object(b'{"alg":"x","\\u0061lg":"y"}', HEADER_FIELDS)
    for raw in (b"{} {}", b"[]", b"null", b'"scalar"', b"Infinity", b"-Infinity"):
        with pytest.raises(ValueError):
            strict_object(raw, HEADER_FIELDS)
    with pytest.raises(ValueError):
        strict_object(b"NaN", HEADER_FIELDS)
    header = b64(b'{"alg":"EdDSA","kid":"k","typ":"erp-ai-request+jws"}')
    body = b64(json.dumps(payload(), separators=(",", ":")).encode())
    with pytest.raises(ValueError):
        parse_compact_jws(f"{header}.{body}.{b64(b'short')}", 4096, 3072)


def test_keyring_is_immutable_strict_and_repr_safe() -> None:
    _, config = key_config()
    assert isinstance(config.keys, tuple)
    assert "https://erp.invalid" not in repr(config)
    raw = b"k" * 32
    common = {
        "public_key": SecretBytes(raw),
        "activates_at": NOW,
        "retires_at": NOW + timedelta(days=1),
    }
    for kid in ("", "UPPER", "../bad", "https://bad", "http_key", "www_key", "a" * 65):
        with pytest.raises(ValidationError):
            ErpAssertionVerificationKey(kid=kid, **common)
    with pytest.raises(ValidationError):
        ErpAssertionVerificationKey(**(common | {"kid": "ok", "public_key": SecretBytes(b"x")}))
    with pytest.raises(ValidationError):
        ErpAssertionVerificationKey(
            **(common | {"kid": "ok", "activates_at": NOW.replace(tzinfo=None)})
        )
    with pytest.raises(ValidationError):
        ErpAssertionVerificationKey(**(common | {"kid": "ok", "retires_at": NOW}))
    key = ErpAssertionVerificationKey(kid="same", **common)
    with pytest.raises(ValidationError):
        ErpAssertionVerifierConfig(
            issuer=SecretStr("i"),
            audience=SecretStr("a"),
            keys=[key, key],
            maximum_lifetime=timedelta(seconds=1),
            maximum_clock_skew=timedelta(0),
        )
    for lifetime, skew in (
        (timedelta(minutes=5, microseconds=1), timedelta(0)),
        (timedelta(seconds=1), timedelta(minutes=1, microseconds=1)),
    ):
        with pytest.raises(ValidationError):
            ErpAssertionVerifierConfig(
                issuer=SecretStr("i"),
                audience=SecretStr("a"),
                keys=[key],
                maximum_lifetime=lifetime,
                maximum_clock_skew=skew,
            )
    with pytest.raises(ValidationError):
        ErpAssertionVerifierConfig(
            issuer=SecretStr("bad\nissuer"),
            audience=SecretStr("a"),
            keys=[key],
            maximum_lifetime=timedelta(seconds=1),
            maximum_clock_skew=timedelta(0),
        )
    source = [key]
    copied = ErpAssertionVerifierConfig(
        issuer=SecretStr("i"),
        audience=SecretStr("a"),
        keys=source,
        maximum_lifetime=timedelta(seconds=1),
        maximum_clock_skew=timedelta(0),
    )
    source.clear()
    assert copied.keys == (key,)
    with pytest.raises(ValidationError):
        ErpAssertionVerifierConfig(
            issuer=SecretStr("i"),
            audience=SecretStr("a"),
            keys=[key],
            maximum_lifetime=timedelta(0),
            maximum_clock_skew=timedelta(0),
        )
    encoded = b64(raw)
    assert decode_public_key(encoded) == raw
    for bad in (encoded + "=", "!", b64(b"short")):
        if bad == b64(b"short"):
            assert decode_public_key(bad) == b"short"
        else:
            with pytest.raises(ValueError):
                decode_public_key(bad)
    with pytest.raises(ValueError):
        decode_public_key("é")


def http_config(origin: str = "https://erp-trust.invalid") -> ErpTrustHttpConfig:
    return ErpTrustHttpConfig(
        origin=SecretStr(origin),
        connect_timeout_seconds=1.0,
        read_timeout_seconds=2.0,
        write_timeout_seconds=1.0,
        pool_timeout_seconds=1.0,
        maximum_connections=2,
        maximum_keepalive_connections=1,
        maximum_response_bytes=4096,
    )


def test_http_configuration_and_tls_validation() -> None:
    for origin in (
        "http://bad",
        "https://user@bad",
        "https://bad/path",
        "https://bad?q=1",
        "https://bad#fragment",
        "https://%62ad",
        "https://[::1]",
    ):
        with pytest.raises(ValidationError):
            http_config(origin)
    with pytest.raises(ValueError):
        ErpTrustHttpClient(http_config(), None)
    context = ssl.create_default_context()
    context.check_hostname = False
    with pytest.raises(ValueError):
        ErpTrustHttpClient(http_config(), context)
    with pytest.raises(ValueError):
        ErpTrustHttpClient(
            http_config(),
            SimpleNamespace(
                verify_mode=ssl.CERT_REQUIRED,
                check_hostname=True,
                minimum_version=ssl.TLSVersion.TLSv1_1,
            ),  # type: ignore[arg-type]
        )
    with pytest.raises(ValidationError):
        ErpTrustHttpConfig(**(http_config().model_dump() | {"maximum_keepalive_connections": 3}))
    assert http_config("https://ERP-TRUST.invalid:443/").origin.get_secret_value() == (
        "https://erp-trust.invalid"
    )


def test_exact_time_key_boundaries_and_rotation() -> None:
    private, base = key_config()

    async def accepted(
        body: dict[str, object], config: ErpAssertionVerifierConfig, now: datetime
    ) -> None:
        result = await ErpSignedAssertionAuthenticator(config, Clock(now)).authenticate(
            ingress(token(private, body))
        )
        assert result.request_id == REQUEST_ID

    asyncio.run(accepted(payload(), base, NOW))
    asyncio.run(
        accepted(
            payload(iat=int(NOW.timestamp()) + 5, exp=int(NOW.timestamp()) + 60),
            base,
            NOW,
        )
    )
    boundary_key = ErpAssertionVerificationKey(
        kid="erp_2026_a",
        public_key=base.keys[0].public_key,
        activates_at=NOW,
        retires_at=NOW + timedelta(seconds=60),
    )
    boundary_config = base.model_copy(update={"keys": (boundary_key,)})
    asyncio.run(accepted(payload(), boundary_config, NOW))
    expired_boundary = payload(iat=int(NOW.timestamp()) - 60, exp=int(NOW.timestamp()) - 5)
    with pytest.raises(IngressAuthenticationDenied):
        asyncio.run(
            ErpSignedAssertionAuthenticator(base, Clock()).authenticate(
                ingress(token(private, expired_boundary))
            )
        )

    second = Ed25519PrivateKey.generate()
    second_public = second.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    rotated = ErpAssertionVerificationKey(
        kid="erp_2026_b",
        public_key=SecretBytes(second_public),
        activates_at=NOW - timedelta(minutes=1),
        retires_at=NOW + timedelta(minutes=1),
    )
    rotation_config = base.model_copy(update={"keys": (*base.keys, rotated)})
    rotated_token = token(second, payload(), kid="erp_2026_b")
    result = asyncio.run(
        ErpSignedAssertionAuthenticator(rotation_config, Clock()).authenticate(
            ingress(rotated_token)
        )
    )
    assert result.request_id == REQUEST_ID
    with pytest.raises(IngressAuthenticationDenied):
        asyncio.run(
            ErpSignedAssertionAuthenticator(rotation_config, Clock()).authenticate(
                ingress(token(private, payload(), kid="erp_2026_b"))
            )
        )


def json_response(payload: object, status: int = 200, **headers: str) -> httpx.Response:
    return httpx.Response(
        status,
        stream=AsyncChunks(json.dumps(payload, separators=(",", ":")).encode()),
        headers={"content-type": "application/json", **headers},
    )


async def opened(handler: Any, *, maximum: int = 4096) -> ErpTrustHttpClient:
    config = http_config().model_copy(update={"maximum_response_bytes": maximum})
    client = ErpTrustHttpClient(
        config, ssl.create_default_context(), test_transport=httpx.MockTransport(handler)
    )
    await client.open()
    return client


def context_payload() -> dict[str, object]:
    return {
        "context_version": 1,
        "request_id": REQUEST_ID,
        "customer_environment_id": "customer_a",
        "user_id": "user_a",
        "employee_id": "employee_a",
        "roles": ["employee"],
        "permission_codes": ["hr.profile.read_self"],
        "legal_entity_ids": ["entity_a"],
        "enabled_modules": ["hr_core"],
        "locale": "en",
        "timezone": "Africa/Cairo",
        "purpose": "employee_self_service",
        "issued_at": NOW.isoformat(),
        "authorization_snapshot_id": "snapshot_a",
    }


def intent_payload() -> dict[str, object]:
    return {
        "intent_contract_version": 1,
        "intent_code": "general",
        "issued_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(seconds=30)).isoformat(),
        "request_id": REQUEST_ID,
        "customer_environment_id": "customer_a",
        "user_id": "user_a",
        "authorization_snapshot_id": "snapshot_a",
    }


def test_resolver_and_snapshot_verifier_exact_contracts() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/resolve"):
            return json_response(
                {
                    "contract_version": 1,
                    "request_id": REQUEST_ID,
                    "trusted_request_context": context_payload(),
                    "trusted_route_intent": intent_payload(),
                }
            )
        return json_response(
            {
                "contract_version": 1,
                "request_id": REQUEST_ID,
                "customer_environment_id": "customer_a",
                "user_id": "user_a",
                "authorization_snapshot_id": "snapshot_a",
                "status": "current",
            }
        )

    async def run() -> None:
        client = await opened(handler)
        reference = TrustedRequestReference(
            request_id=REQUEST_ID, resolver_reference=SecretStr(REFERENCE)
        )
        resolution = await ErpTrustedRequestResolver(client).resolve(reference)
        decision = await ErpAuthorizationSnapshotVerifier(client).verify(resolution.context)
        assert decision.status == "current"
        assert [request.url.path for request in seen] == [
            "/internal/ai/v1/resolve",
            "/internal/ai/v1/authorization-snapshots/verify",
        ]
        for request in seen:
            assert request.headers["accept-encoding"] == "identity"
            assert request.url.scheme == "https"
            assert request.url.host == "erp-trust.invalid"
            assert request.url.query == b""
            assert "cookie" not in request.headers
        assert set(json.loads(seen[0].content)) == {
            "contract_version",
            "request_id",
            "resolver_reference",
        }
        assert set(json.loads(seen[1].content)) == {
            "contract_version",
            "request_id",
            "customer_environment_id",
            "user_id",
            "authorization_snapshot_id",
        }
        await client.close()
        with pytest.raises(ErpTrustUnavailable):
            await client.post_json("/internal/ai/v1/resolve", {})

    asyncio.run(run())


@pytest.mark.parametrize("status", [404, 409])
def test_resolver_denials(status: int) -> None:
    async def run() -> None:
        client = await opened(lambda _: json_response({}, status))
        with pytest.raises(ErpTrustResolutionDenied):
            await ErpTrustedRequestResolver(client).resolve(
                TrustedRequestReference(
                    request_id=REQUEST_ID, resolver_reference=SecretStr(REFERENCE)
                )
            )

    asyncio.run(run())


@pytest.mark.parametrize(
    "response",
    [
        *(json_response({}, status) for status in (201, 202, 204, 301, 429, 500, 503)),
        httpx.Response(200, stream=AsyncChunks(b"{}"), headers={"content-type": "text/plain"}),
        httpx.Response(
            200,
            stream=AsyncChunks(b'{"x":1,"x":2}'),
            headers={"content-type": "application/json"},
        ),
    ],
)
def test_http_and_resolver_fail_closed(response: httpx.Response) -> None:
    async def run() -> None:
        client = await opened(lambda _: response)
        with pytest.raises(ErpTrustUnavailable):
            await ErpTrustedRequestResolver(client).resolve(
                TrustedRequestReference(
                    request_id=REQUEST_ID, resolver_reference=SecretStr(REFERENCE)
                )
            )

    asyncio.run(run())


def test_response_limit_snapshot_binding_and_cancellation() -> None:
    async def run() -> None:
        client = await opened(lambda _: json_response({"padding": "x" * 100}), maximum=10)
        with pytest.raises(ErpTrustUnavailable):
            await client.post_json("/internal/ai/v1/resolve", {})
        await client.close()
        bad = await opened(
            lambda _: json_response(
                {
                    "contract_version": 1,
                    "request_id": "wrong",
                    "customer_environment_id": "customer_a",
                    "user_id": "user_a",
                    "authorization_snapshot_id": "snapshot_a",
                    "status": "current",
                }
            )
        )
        from erp_ai.context import TrustedRequestContext

        context = TrustedRequestContext.model_validate_json(json.dumps(context_payload()))
        with pytest.raises(SnapshotVerificationUnavailable):
            await ErpAuthorizationSnapshotVerifier(bad).verify(context)
        cancelled = await opened(lambda _: (_ for _ in ()).throw(asyncio.CancelledError()))
        with pytest.raises(asyncio.CancelledError):
            await cancelled.post_json("/internal/ai/v1/resolve", {})

    asyncio.run(run())


@pytest.mark.parametrize("status", ["current", "stale", "revoked", "mismatched"])
def test_snapshot_status_contract_accepts_every_known_decision(status: str) -> None:
    async def run() -> None:
        client = await opened(
            lambda _: json_response(
                {
                    "contract_version": 1,
                    "request_id": REQUEST_ID,
                    "customer_environment_id": "customer_a",
                    "user_id": "user_a",
                    "authorization_snapshot_id": "snapshot_a",
                    "status": status,
                }
            )
        )
        from erp_ai.context import TrustedRequestContext

        context = TrustedRequestContext.model_validate_json(json.dumps(context_payload()))
        decision = await ErpAuthorizationSnapshotVerifier(client).verify(context)
        assert decision.status == status

    asyncio.run(run())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request_id", "wrong"),
        ("customer_environment_id", "wrong"),
        ("user_id", "wrong"),
        ("authorization_snapshot_id", "wrong"),
        ("status", "unknown"),
    ],
)
def test_snapshot_mismatch_and_unknown_status_fail_generically(field: str, value: str) -> None:
    async def run() -> None:
        response: dict[str, object] = {
            "contract_version": 1,
            "request_id": REQUEST_ID,
            "customer_environment_id": "customer_a",
            "user_id": "user_a",
            "authorization_snapshot_id": "snapshot_a",
            "status": "current",
        }
        response[field] = value
        client = await opened(lambda _: json_response(response))
        from erp_ai.context import TrustedRequestContext

        context = TrustedRequestContext.model_validate_json(json.dumps(context_payload()))
        with pytest.raises(SnapshotVerificationUnavailable) as caught:
            await ErpAuthorizationSnapshotVerifier(client).verify(context)
        assert str(caught.value) == ""

    asyncio.run(run())


def test_raw_response_boundaries_duplicate_content_type_and_cookie_isolation() -> None:
    requests: list[httpx.Request] = []
    call = 0

    def cookie_handler(request: httpx.Request) -> httpx.Response:
        nonlocal call
        requests.append(request)
        call += 1
        if call == 1:
            return httpx.Response(
                200,
                stream=AsyncChunks(b"{}"),
                headers={"content-type": "application/json", "set-cookie": "bad=value"},
            )
        return json_response({})

    async def run() -> None:
        exact = await opened(
            lambda _: httpx.Response(
                200,
                stream=AsyncChunks(b"{", b"}"),
                headers={"content-type": "application/json"},
            ),
            maximum=2,
        )
        assert await exact.post_json("/internal/ai/v1/resolve", {}) == (200, {})
        oversized = await opened(
            lambda _: httpx.Response(
                200,
                stream=AsyncChunks(b"{}", b" "),
                headers={"content-type": "application/json"},
            ),
            maximum=2,
        )
        with pytest.raises(ErpTrustUnavailable):
            await oversized.post_json("/internal/ai/v1/resolve", {})
        duplicate = await opened(
            lambda _: httpx.Response(
                200,
                stream=AsyncChunks(b"{}"),
                headers=[
                    ("content-type", "application/json"),
                    ("content-type", "application/json"),
                ],
            )
        )
        with pytest.raises(ErpTrustUnavailable):
            await duplicate.post_json("/internal/ai/v1/resolve", {})
        cookies = await opened(cookie_handler)
        with pytest.raises(ErpTrustUnavailable):
            await cookies.post_json("/internal/ai/v1/resolve", {})
        assert await cookies.post_json("/internal/ai/v1/resolve", {}) == (200, {})
        assert all("cookie" not in request.headers for request in requests)

    asyncio.run(run())


def test_lifecycle_is_serialized_isolated_and_defensively_validated() -> None:
    async def run() -> None:
        first = ErpTrustHttpClient(
            http_config(),
            ssl.create_default_context(),
            test_transport=httpx.MockTransport(lambda _: json_response({})),
        )
        results = await asyncio.gather(first.open(), first.open(), return_exceptions=True)
        assert sum(result is None for result in results) == 1
        assert sum(isinstance(result, ErpTrustUnavailable) for result in results) == 1
        second = ErpTrustHttpClient(
            http_config(),
            ssl.create_default_context(),
            test_transport=httpx.MockTransport(lambda _: json_response({})),
        )
        await second.open()
        assert first._client is not second._client
        await asyncio.gather(first.close(), first.close())
        with pytest.raises(ErpTrustUnavailable):
            await first.post_json("/internal/ai/v1/resolve", {})
        assert await second.post_json("/internal/ai/v1/resolve", {}) == (200, {})
        await second.close()

    asyncio.run(run())
    invalid = ErpTrustHttpConfig.model_construct(
        **(http_config().model_dump() | {"origin": SecretStr("http://unsafe")})
    )
    with pytest.raises(ValidationError):
        ErpTrustHttpClient(
            invalid,
            ssl.create_default_context(),
            test_transport=httpx.MockTransport(lambda _: json_response({})),
        )


def test_final_url_mismatch_and_open_cancellation_fail_closed(monkeypatch: Any) -> None:
    async def run() -> None:
        client = await opened(lambda _: json_response({}))
        assert client._client is not None
        original = client._client.build_request

        def wrong_url(*args: Any, **kwargs: Any) -> httpx.Request:
            request = original(*args, **kwargs)
            request.url = httpx.URL("https://other.invalid/internal/ai/v1/resolve")
            return request

        monkeypatch.setattr(client._client, "build_request", wrong_url)
        with pytest.raises(ErpTrustUnavailable):
            await client.post_json("/internal/ai/v1/resolve", {})

    asyncio.run(run())

    def cancelled_client(*args: Any, **kwargs: Any) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(httpx, "AsyncClient", cancelled_client)
    candidate = ErpTrustHttpClient(
        http_config(),
        ssl.create_default_context(),
        test_transport=httpx.MockTransport(lambda _: json_response({})),
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(candidate.open())


def test_remaining_fail_closed_lifecycle_and_adapter_paths(monkeypatch: Any) -> None:
    private, config = key_config()

    class CancelClock:
        def now(self) -> datetime:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            ErpSignedAssertionAuthenticator(config, CancelClock()).authenticate(
                ingress(token(private, payload()))
            )
        )
    for change in (
        {"body_sha256": "z" * 64},
        {"resolver_ref": "short"},
    ):
        with pytest.raises(IngressAuthenticationDenied):
            asyncio.run(
                ErpSignedAssertionAuthenticator(config, Clock()).authenticate(
                    ingress(token(private, payload(**change)))
                )
            )
    before_activation = payload(
        iat=int((NOW - timedelta(days=1, seconds=1)).timestamp()),
        exp=int((NOW - timedelta(days=1) + timedelta(seconds=29)).timestamp()),
    )
    with pytest.raises(IngressAuthenticationDenied):
        asyncio.run(
            ErpSignedAssertionAuthenticator(config, Clock(NOW - timedelta(days=1))).authenticate(
                ingress(token(private, before_activation))
            )
        )
    bad_header = token(private, payload(), kid=1)
    with pytest.raises(IngressAuthenticationDenied):
        asyncio.run(
            ErpSignedAssertionAuthenticator(config, Clock()).authenticate(ingress(bad_header))
        )

    async def run() -> None:
        client = await opened(lambda _: json_response({}))
        with pytest.raises(ErpTrustUnavailable):
            await client.open()
        with pytest.raises(ErpTrustUnavailable):
            await client.post_json("/not-approved", {})
        await client.close()

        encoded = await opened(
            lambda _: httpx.Response(
                200,
                stream=AsyncChunks(gzip.compress(b"{}")),
                headers={"content-type": "application/json", "content-encoding": "gzip"},
            )
        )
        with pytest.raises(ErpTrustUnavailable):
            await encoded.post_json("/internal/ai/v1/resolve", {})

        cookies = await opened(lambda _: json_response({}, **{"set-cookie": "private=value"}))
        with pytest.raises(ErpTrustUnavailable):
            await cookies.post_json("/internal/ai/v1/resolve", {})
        assert cookies._client is not None
        assert not cookies._client.cookies

        constant = await opened(
            lambda _: httpx.Response(
                200,
                stream=AsyncChunks(b"NaN"),
                headers={"content-type": "application/json"},
            )
        )
        with pytest.raises(ErpTrustUnavailable):
            await constant.post_json("/internal/ai/v1/resolve", {})

        failed = await opened(lambda _: (_ for _ in ()).throw(RuntimeError("private")))
        with pytest.raises(ErpTrustUnavailable):
            await failed.post_json("/internal/ai/v1/resolve", {})

        mismatch = await opened(
            lambda _: json_response(
                {
                    "contract_version": 1,
                    "request_id": "different",
                    "trusted_request_context": context_payload(),
                    "trusted_route_intent": intent_payload(),
                }
            )
        )
        reference = TrustedRequestReference(
            request_id=REQUEST_ID, resolver_reference=SecretStr(REFERENCE)
        )
        with pytest.raises(ErpTrustUnavailable):
            await ErpTrustedRequestResolver(mismatch).resolve(reference)
        with pytest.raises(ErpTrustUnavailable):
            await ErpTrustedRequestResolver(mismatch).resolve(
                TrustedRequestReference.model_construct()
            )

        unavailable = await opened(lambda _: json_response({}, 503))
        from erp_ai.context import TrustedRequestContext

        trusted = TrustedRequestContext.model_validate_json(json.dumps(context_payload()))
        with pytest.raises(SnapshotVerificationUnavailable):
            await ErpAuthorizationSnapshotVerifier(unavailable).verify(trusted)
        with pytest.raises(SnapshotVerificationUnavailable):
            await ErpAuthorizationSnapshotVerifier(unavailable).verify(
                TrustedRequestContext.model_construct()
            )

        cancelled = await opened(lambda _: (_ for _ in ()).throw(asyncio.CancelledError()))
        with pytest.raises(asyncio.CancelledError):
            await ErpTrustedRequestResolver(cancelled).resolve(reference)
        with pytest.raises(asyncio.CancelledError):
            await ErpAuthorizationSnapshotVerifier(cancelled).verify(trusted)

    asyncio.run(run())

    def broken_client(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("startup failure")

    monkeypatch.setattr(httpx, "AsyncClient", broken_client)
    candidate = ErpTrustHttpClient(
        http_config(),
        ssl.create_default_context(),
        test_transport=httpx.MockTransport(lambda _: json_response({})),
    )
    with pytest.raises(ErpTrustUnavailable):
        asyncio.run(candidate.open())


def test_sensitive_values_are_absent_from_repr_and_errors() -> None:
    marker = "cmVzb2x2ZXJfcmVmZXJlbmNlX21hcmtlcl8xMjM0NTY"
    reference = TrustedRequestReference(request_id=REQUEST_ID, resolver_reference=SecretStr(marker))
    assert marker not in repr(reference)
    with pytest.raises(ValidationError) as caught:
        TrustedRequestReference(request_id=REQUEST_ID, resolver_reference=SecretStr("bad"))
    assert "bad" not in str(caught.value)
