"""Immutable configuration for ERP assertion and mTLS trust adapters."""

import base64
import re
import ssl
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretBytes,
    SecretStr,
    field_validator,
    model_validator,
)

_KID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_SAFE_CLAIM = re.compile(r"^[\x21-\x7e]+$")
_MAXIMUM_ASSERTION_LIFETIME = timedelta(minutes=5)
_MAXIMUM_CLOCK_SKEW = timedelta(minutes=1)


class ErpAssertionVerificationKey(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    kid: str = Field(min_length=1, max_length=64)
    public_key: SecretBytes = Field(repr=False)
    activates_at: datetime
    retires_at: datetime

    @field_validator("kid")
    @classmethod
    def valid_kid(cls, value: str) -> str:
        if (
            not _KID.fullmatch(value)
            or "/" in value
            or ":" in value
            or "\\" in value
            or value.startswith(("http", "www"))
        ):
            raise ValueError("invalid verification key identifier")
        return value

    @field_validator("public_key")
    @classmethod
    def valid_key(cls, value: SecretBytes) -> SecretBytes:
        if len(value.get_secret_value()) != 32:
            raise ValueError("invalid verification public key")
        return value

    @field_validator("activates_at", "retires_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("verification key timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def ordered_window(self) -> "ErpAssertionVerificationKey":
        if self.retires_at <= self.activates_at:
            raise ValueError("verification key retirement must follow activation")
        return self


class ErpAssertionVerifierConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    issuer: SecretStr = Field(repr=False, min_length=1, max_length=256)
    audience: SecretStr = Field(repr=False, min_length=1, max_length=256)
    keys: tuple[ErpAssertionVerificationKey, ...] = Field(min_length=1, repr=False)
    maximum_lifetime: timedelta
    maximum_clock_skew: timedelta
    maximum_token_bytes: int = Field(default=4096, strict=True, ge=256, le=16384)
    maximum_segment_bytes: int = Field(default=3072, strict=True, ge=64, le=8192)

    @field_validator("issuer", "audience")
    @classmethod
    def safe_exact_claim(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if len(raw) > 256 or not _SAFE_CLAIM.fullmatch(raw):
            raise ValueError("assertion identity configuration is invalid")
        return value

    @field_validator("keys", mode="before")
    @classmethod
    def freeze_keys(cls, value: Any) -> Any:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def valid_config(self) -> "ErpAssertionVerifierConfig":
        kids = tuple(key.kid for key in self.keys)
        if len(kids) != len(set(kids)):
            raise ValueError("duplicate verification key identifiers")
        if (
            self.maximum_lifetime <= timedelta(0)
            or self.maximum_lifetime > _MAXIMUM_ASSERTION_LIFETIME
            or self.maximum_clock_skew < timedelta(0)
            or self.maximum_clock_skew > _MAXIMUM_CLOCK_SKEW
            or self.maximum_segment_bytes > self.maximum_token_bytes
        ):
            raise ValueError("invalid assertion time policy")
        return self


class ErpTrustHttpConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    origin: SecretStr = Field(repr=False)
    contract_version: int = Field(default=1, strict=True, ge=1, le=1)
    connect_timeout_seconds: float = Field(strict=True, gt=0, le=30)
    read_timeout_seconds: float = Field(strict=True, gt=0, le=60)
    write_timeout_seconds: float = Field(strict=True, gt=0, le=30)
    pool_timeout_seconds: float = Field(strict=True, gt=0, le=30)
    maximum_connections: int = Field(strict=True, ge=1, le=32)
    maximum_keepalive_connections: int = Field(strict=True, ge=0, le=32)
    maximum_response_bytes: int = Field(strict=True, ge=1, le=1_048_576)

    @field_validator("origin")
    @classmethod
    def fixed_https_origin(cls, value: SecretStr) -> SecretStr:
        parsed = urlsplit(value.get_secret_value())
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("ERP trust origin must be an exact HTTPS origin")
        if (
            "%" in parsed.netloc
            or not parsed.netloc.isascii()
            or ":" in parsed.hostname
            or parsed.hostname != parsed.hostname.lower()
        ):
            raise ValueError("ERP trust origin contains ambiguous host syntax")
        port = parsed.port
        normalized_port = "" if port in (None, 443) else f":{port}"
        return SecretStr(f"https://{parsed.hostname}{normalized_port}")

    @model_validator(mode="after")
    def pool_bounds(self) -> "ErpTrustHttpConfig":
        if self.maximum_keepalive_connections > self.maximum_connections:
            raise ValueError("keepalive pool cannot exceed connection pool")
        return self


def validate_production_ssl_context(context: ssl.SSLContext) -> None:
    """Fail closed when the externally provisioned mTLS context is unsafe."""

    if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
        raise ValueError("ERP trust TLS context must verify certificates and hostnames")
    if context.minimum_version < ssl.TLSVersion.TLSv1_2:
        raise ValueError("ERP trust TLS context requires TLS 1.2 or newer")


def decode_public_key(value: str) -> bytes:
    """Decode a canonical unpadded base64url public key for composition code."""

    if "=" in value:
        raise ValueError("public key encoding must be unpadded base64url")
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception:
        raise ValueError("invalid public key encoding") from None
    if base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != value:
        raise ValueError("invalid public key encoding")
    return decoded
