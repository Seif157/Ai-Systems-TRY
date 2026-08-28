"""Immutable server-owned Laravel ERP read-client configuration."""

import ssl
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from .contracts import (
    LARAVEL_ERP_READ_CONTRACT_DIGEST,
    LARAVEL_ERP_READ_CONTRACT_VERSION,
    LARAVEL_ERP_READ_SERVICE_IDENTITY,
)


class LaravelErpReadConfig(BaseModel):
    """One exact HTTPS origin and bounded HTTP policy; never public input."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    origin: SecretStr = Field(repr=False)
    connect_timeout_seconds: float = Field(strict=True, gt=0, le=30)
    read_timeout_seconds: float = Field(strict=True, gt=0, le=60)
    write_timeout_seconds: float = Field(strict=True, gt=0, le=30)
    pool_timeout_seconds: float = Field(strict=True, gt=0, le=30)
    maximum_connections: int = Field(strict=True, ge=1, le=32)
    maximum_keepalive_connections: int = Field(strict=True, ge=0, le=32)
    maximum_request_bytes: int = Field(strict=True, ge=512, le=65_536)
    maximum_response_bytes: int = Field(strict=True, ge=512, le=1_048_576)
    expected_service_identity: SecretStr = Field(
        default=SecretStr(LARAVEL_ERP_READ_SERVICE_IDENTITY), repr=False
    )
    expected_contract_version: SecretStr = Field(
        default=SecretStr(LARAVEL_ERP_READ_CONTRACT_VERSION), repr=False
    )
    expected_contract_digest: SecretStr = Field(
        default=SecretStr(LARAVEL_ERP_READ_CONTRACT_DIGEST), repr=False
    )

    @field_validator(
        "expected_service_identity", "expected_contract_version", "expected_contract_digest"
    )
    @classmethod
    def exact_contract_identity(cls, value: SecretStr, info: Any) -> SecretStr:
        expected = {
            "expected_service_identity": LARAVEL_ERP_READ_SERVICE_IDENTITY,
            "expected_contract_version": LARAVEL_ERP_READ_CONTRACT_VERSION,
            "expected_contract_digest": LARAVEL_ERP_READ_CONTRACT_DIGEST,
        }[info.field_name]
        if value.get_secret_value() != expected:
            raise ValueError("Laravel ERP contract identity is invalid")
        return value

    @field_validator("origin")
    @classmethod
    def exact_https_origin(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        parsed = urlsplit(raw)
        try:
            port = parsed.port
        except ValueError as error:
            raise ValueError("Laravel ERP origin is invalid") from error
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or "%" in parsed.netloc
            or not parsed.netloc.isascii()
            or parsed.netloc != parsed.netloc.lower()
            or ":" in parsed.hostname
            or parsed.hostname != parsed.hostname.lower()
        ):
            raise ValueError("Laravel ERP origin must be an exact HTTPS origin")
        suffix = "" if port in (None, 443) else f":{port}"
        return SecretStr(f"https://{parsed.hostname}{suffix}")

    @model_validator(mode="after")
    def valid_pool(self) -> "LaravelErpReadConfig":
        if self.maximum_keepalive_connections > self.maximum_connections:
            raise ValueError("keepalive pool cannot exceed connection pool")
        return self


def validate_laravel_ssl_context(context: Any) -> None:
    """Require certificate and hostname validation on an externally built context."""

    if not isinstance(context, ssl.SSLContext):
        raise TypeError("Laravel ERP SSL context is required")
    if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
        raise ValueError("Laravel ERP TLS context must verify certificates and hostnames")
    if context.minimum_version < ssl.TLSVersion.TLSv1_2:
        raise ValueError("Laravel ERP TLS context requires TLS 1.2 or newer")
