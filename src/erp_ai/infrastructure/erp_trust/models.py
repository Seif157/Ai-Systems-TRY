"""Strict private ERP trust API contracts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from erp_ai.application import TrustedRouteIntent
from erp_ai.context import TrustedRequestContext
from erp_ai.context.models import Identifier


class ResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)
    contract_version: Literal[1]
    request_id: Identifier = Field(repr=False)
    resolver_reference: SecretStr = Field(repr=False, min_length=43, max_length=43)


class ResolveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)
    contract_version: Literal[1]
    request_id: Identifier = Field(repr=False)
    trusted_request_context: TrustedRequestContext = Field(repr=False)
    trusted_route_intent: TrustedRouteIntent = Field(repr=False)


class SnapshotVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)
    contract_version: Literal[1]
    request_id: Identifier = Field(repr=False)
    customer_environment_id: Identifier = Field(repr=False)
    user_id: Identifier = Field(repr=False)
    authorization_snapshot_id: Identifier = Field(repr=False)


class SnapshotVerifyResponse(SnapshotVerifyRequest):
    status: Literal["current", "stale", "revoked", "mismatched"]
