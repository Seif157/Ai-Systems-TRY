"""Strict static customer-to-project configuration."""

import re
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from erp_ai.capabilities import DataClassification
from erp_ai.capabilities.models import Code
from erp_ai.context.models import Identifier
from erp_ai.knowledge.ingestion.models import Digest

from .contracts import OPENAI_ALLOWED_ENDPOINTS, OPENAI_ATTESTATION_CONTRACT_VERSION

_MODEL_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,127}$")
_DATED_CHAT_PATTERN = re.compile(r"^.+-20\d{2}-\d{2}-\d{2}$")


class OpenAIRequestLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    connect_timeout_seconds: float = Field(strict=True, gt=0, le=30)
    read_timeout_seconds: float = Field(strict=True, gt=0, le=120)
    write_timeout_seconds: float = Field(strict=True, gt=0, le=30)
    pool_timeout_seconds: float = Field(strict=True, gt=0, le=30)
    maximum_request_bytes: int = Field(strict=True, ge=1024, le=1_048_576)
    maximum_response_bytes: int = Field(strict=True, ge=1024, le=1_048_576)
    maximum_input_bytes: int = Field(strict=True, ge=1, le=262_144)
    maximum_input_tokens: int = Field(strict=True, ge=1, le=1_000_000)
    maximum_output_tokens: int = Field(strict=True, ge=1, le=32_768)


class OpenAIProjectPrivacyAttestation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)

    contract_version: Literal["1.0.0"] = OPENAI_ATTESTATION_CONTRACT_VERSION
    organization_id: Identifier = Field(repr=False)
    project_id: Identifier = Field(repr=False)
    retention_mode: Literal["zero_data_retention"]
    training_data_sharing_opt_in: Literal[False]
    allowed_endpoints: tuple[Literal["/v1/responses", "/v1/embeddings"], ...]
    allowed_data_classifications: tuple[DataClassification, ...] = Field(repr=False)
    allowed_purposes: tuple[Code, ...] = Field(repr=False)
    approved_at: datetime
    expires_at: datetime
    policy_id: Identifier = Field(repr=False)
    policy_digest: Digest = Field(repr=False)

    @field_validator(
        "allowed_endpoints", "allowed_data_classifications", "allowed_purposes", mode="before"
    )
    @classmethod
    def freeze_unique(cls, value: object) -> object:
        if not isinstance(value, (list, tuple)):
            return value
        frozen = tuple(value)
        if len(set(frozen)) != len(frozen):
            raise ValueError("duplicate attestation values are forbidden")
        return frozen

    @model_validator(mode="after")
    def validate_attestation(self) -> Self:
        if self.approved_at.tzinfo is None or self.approved_at.utcoffset() is None:
            raise ValueError("attestation approval must be timezone-aware")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("attestation expiry must be timezone-aware")
        if self.expires_at <= self.approved_at:
            raise ValueError("attestation lifetime is invalid")
        if self.allowed_endpoints != OPENAI_ALLOWED_ENDPOINTS:
            raise ValueError("attestation endpoint allowlist is invalid")
        if DataClassification.HIGHLY_RESTRICTED in self.allowed_data_classifications:
            raise ValueError("highly restricted OpenAI traffic is not approved")
        return self


class OpenAIProjectRoute(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)

    customer_environment_id: Identifier = Field(repr=False)
    organization_id: Identifier = Field(repr=False)
    project_id: Identifier = Field(repr=False)
    credential_reference: Identifier = Field(repr=False)
    privacy_attestation_id: Identifier = Field(repr=False)
    chat_model: str = Field(repr=False)
    embedding_model: str = Field(repr=False)
    embedding_revision: Identifier = Field(repr=False)
    embedding_dimensions: int = Field(strict=True, ge=1, le=4096)
    maximum_attestation_lifetime_seconds: int = Field(strict=True, ge=1, le=31_536_000)
    allowed_data_classifications: tuple[DataClassification, ...] = Field(repr=False)
    allowed_purposes: tuple[Code, ...] = Field(repr=False)
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high"]
    reasoning_output_policy: Literal["reject"] = "reject"
    limits: OpenAIRequestLimits

    @field_validator("chat_model", "embedding_model")
    @classmethod
    def exact_model_identifier(cls, value: str) -> str:
        if not _MODEL_PATTERN.fullmatch(value) or value.endswith("latest"):
            raise ValueError("an exact approved model identifier is required")
        return value

    @field_validator("chat_model")
    @classmethod
    def dated_chat_snapshot(cls, value: str) -> str:
        if not _DATED_CHAT_PATTERN.fullmatch(value):
            raise ValueError("chat model must be an immutable dated snapshot")
        return value

    @field_validator("allowed_data_classifications", "allowed_purposes", mode="before")
    @classmethod
    def freeze_unique_sorted(cls, value: object) -> object:
        if not isinstance(value, (list, tuple)):
            return value
        frozen = tuple(value)
        if len(set(frozen)) != len(frozen):
            raise ValueError("duplicate route values are forbidden")
        return tuple(sorted(frozen, key=lambda item: getattr(item, "value", item)))


class OpenAIProductionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    routes: tuple[OpenAIProjectRoute, ...] = Field(min_length=1, repr=False)
    attestations: tuple[OpenAIProjectPrivacyAttestation, ...] = Field(min_length=1, repr=False)

    @field_validator("routes", "attestations", mode="before")
    @classmethod
    def freeze_collections(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def unique_and_bound(self) -> Self:
        customers = tuple(item.customer_environment_id for item in self.routes)
        projects = tuple((item.organization_id, item.project_id) for item in self.routes)
        attestation_ids = tuple(item.policy_id for item in self.attestations)
        if len(set(customers)) != len(customers) or len(set(projects)) != len(projects):
            raise ValueError("duplicate customer or project routes are forbidden")
        if len(set(attestation_ids)) != len(attestation_ids):
            raise ValueError("duplicate privacy attestations are forbidden")
        known = {item.policy_id: item for item in self.attestations}
        for route in self.routes:
            attestation = known.get(route.privacy_attestation_id)
            if (
                attestation is None
                or attestation.organization_id != route.organization_id
                or attestation.project_id != route.project_id
            ):
                raise ValueError("route privacy attestation binding is invalid")
        return self
