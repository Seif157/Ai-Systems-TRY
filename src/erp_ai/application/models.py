"""Strict internal contracts for trusted application resolution."""

import base64
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from erp_ai.context import TrustedRequestContext
from erp_ai.context.models import Code, Identifier


class TrustedRequestReference(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    request_id: Identifier = Field(repr=False)
    resolver_reference: SecretStr = Field(repr=False, min_length=43, max_length=43)

    @field_validator("resolver_reference")
    @classmethod
    def canonical_reference(cls, value: SecretStr) -> SecretStr:
        encoded = value.get_secret_value()
        if "=" in encoded:
            raise ValueError("resolver reference must be canonical unpadded base64url")
        try:
            decoded = base64.urlsafe_b64decode(encoded + "=")
        except Exception:
            raise ValueError("resolver reference must be canonical unpadded base64url") from None
        canonical = base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")
        if len(decoded) != 32 or canonical != encoded:
            raise ValueError("resolver reference must be canonical unpadded base64url")
        return value


class TrustedRouteIntent(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    intent_contract_version: Literal[1]
    intent_code: Code = Field(repr=False)
    issued_at: datetime
    expires_at: datetime
    request_id: Identifier = Field(repr=False)
    customer_environment_id: Identifier = Field(repr=False)
    user_id: Identifier = Field(repr=False)
    authorization_snapshot_id: Identifier = Field(repr=False)

    @field_validator("issued_at", "expires_at")
    @classmethod
    def require_aware_datetime(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("intent timestamps must be timezone-aware")
        return value


class TrustedResolution(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    context: TrustedRequestContext = Field(repr=False)
    intent: TrustedRouteIntent = Field(repr=False)


class AuthorizationSnapshotDecision(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    status: Literal["current", "stale", "revoked", "mismatched"]
    request_id: Identifier | None = Field(default=None, repr=False)
    customer_environment_id: Identifier | None = Field(default=None, repr=False)
    user_id: Identifier | None = Field(default=None, repr=False)
    authorization_snapshot_id: Identifier | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def require_complete_optional_bindings(self) -> "AuthorizationSnapshotDecision":
        bindings = (
            self.request_id,
            self.customer_environment_id,
            self.user_id,
            self.authorization_snapshot_id,
        )
        if any(value is not None for value in bindings) and any(
            value is None for value in bindings
        ):
            raise ValueError("authorization decision bindings must be complete")
        return self
