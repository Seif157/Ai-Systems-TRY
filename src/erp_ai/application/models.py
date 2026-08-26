"""Strict internal contracts for trusted application resolution."""

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
    resolver_handle: SecretStr = Field(repr=False, min_length=1, max_length=512)


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
