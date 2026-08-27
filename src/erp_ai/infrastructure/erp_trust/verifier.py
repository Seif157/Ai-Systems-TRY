"""Local Ed25519 ERP assertion authenticator."""

import asyncio
import base64
import hmac
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Protocol

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import SecretStr

from erp_ai.application import TrustedRequestReference
from erp_ai.transport.http import TrustedIngressAuthenticationRequest
from erp_ai.transport.http.errors import IngressAuthenticationDenied

from .assertions import parse_compact_jws, valid_body_digest
from .config import ErpAssertionVerifierConfig


class AssertionClock(Protocol):
    def now(self) -> datetime: ...


@dataclass(frozen=True, slots=True, init=False)
class ErpSignedAssertionAuthenticator:
    config: ErpAssertionVerifierConfig = field(repr=False)
    clock: AssertionClock = field(repr=False)
    _public_keys: MappingProxyType[str, Ed25519PublicKey] = field(repr=False)

    def __init__(self, config: ErpAssertionVerifierConfig, clock: AssertionClock) -> None:
        config = ErpAssertionVerifierConfig.model_validate(config, strict=True)
        parsed = {
            key.kid: Ed25519PublicKey.from_public_bytes(key.public_key.get_secret_value())
            for key in config.keys
        }
        object.__setattr__(self, "config", config)
        object.__setattr__(self, "clock", clock)
        object.__setattr__(self, "_public_keys", MappingProxyType(parsed))

    async def authenticate(
        self, request: TrustedIngressAuthenticationRequest
    ) -> TrustedRequestReference:
        try:
            request = TrustedIngressAuthenticationRequest.model_validate(request, strict=True)
            now = self.clock.now()
            if now.tzinfo is None or now.utcoffset() is None:
                raise ValueError("invalid clock")
            parsed = parse_compact_jws(
                request.bearer_assertion.get_secret_value(),
                self.config.maximum_token_bytes,
                self.config.maximum_segment_bytes,
            )
            header, payload = parsed.header, parsed.payload
            if header["alg"] != "EdDSA" or header["typ"] != "erp-ai-request+jws":
                raise ValueError("invalid assertion profile")
            kid = header["kid"]
            if not isinstance(kid, str):
                raise ValueError("invalid kid")
            configured_key = next(
                (candidate for candidate in self.config.keys if candidate.kid == kid), None
            )
            public_key = self._public_keys.get(kid)
            if configured_key is None or public_key is None:
                raise ValueError("unknown kid")
            self._validate_payload(
                payload,
                request,
                now,
                configured_key.activates_at,
                configured_key.retires_at,
            )
            public_key.verify(parsed.signature, parsed.signing_input)
            reference = TrustedRequestReference(
                request_id=request.request_id,
                resolver_reference=SecretStr(str(payload["resolver_ref"])),
            )
            return TrustedRequestReference.model_validate(reference, strict=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            raise IngressAuthenticationDenied from None

    def _validate_payload(
        self,
        payload: dict[str, object],
        request: TrustedIngressAuthenticationRequest,
        now: datetime,
        activates_at: datetime,
        retires_at: datetime,
    ) -> None:
        strict_ints = (payload["v"], payload["iat"], payload["exp"])
        if any(type(value) is not int for value in strict_ints) or payload["v"] != 1:
            raise ValueError("invalid numeric claims")
        iat = datetime.fromtimestamp(payload["iat"], tz=UTC)  # type: ignore[arg-type]
        exp = datetime.fromtimestamp(payload["exp"], tz=UTC)  # type: ignore[arg-type]
        if exp <= iat or exp - iat > self.config.maximum_lifetime:
            raise ValueError("invalid lifetime")
        if (
            iat > now + self.config.maximum_clock_skew
            or exp <= now - self.config.maximum_clock_skew
        ):
            raise ValueError("assertion outside time window")
        if iat < activates_at or iat >= retires_at or exp > retires_at:
            raise ValueError("assertion outside key window")
        self._uuid4(payload["jti"])
        reference = payload["resolver_ref"]
        if not isinstance(reference, str) or len(reference) != 43:
            raise ValueError("invalid resolver reference")
        decoded = base64.urlsafe_b64decode(reference + "=")
        if (
            len(decoded) != 32
            or base64.urlsafe_b64encode(decoded).rstrip(b"=").decode() != reference
        ):
            raise ValueError("invalid resolver reference")
        bindings = (
            (payload["iss"], self.config.issuer.get_secret_value()),
            (payload["aud"], self.config.audience.get_secret_value()),
            (payload["method"], request.method),
            (payload["path"], request.route_path),
            (payload["body_sha256"], request.body_digest_sha256),
        )
        if not valid_body_digest(payload["body_sha256"]):
            raise ValueError("invalid body digest")
        if any(
            not isinstance(left, str) or not hmac.compare_digest(left, right)
            for left, right in bindings
        ):
            raise ValueError("assertion binding mismatch")

    @staticmethod
    def _uuid4(value: object) -> None:
        if not isinstance(value, str) or not re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", value
        ):
            raise ValueError("invalid jti")
