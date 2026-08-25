"""Immutable server-owned structured ERP database configuration."""

import base64
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from erp_ai.context.models import Identifier


class ErpDatabaseRouteConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    customer_environment_id: Identifier
    reader_dsn: SecretStr = Field(repr=False)
    expected_database_name: Identifier = Field(repr=False)


class ErpCursorKey(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    key_id: Identifier
    key_base64: SecretStr = Field(repr=False)

    @model_validator(mode="after")
    def validate_key(self) -> "ErpCursorKey":
        try:
            raw = base64.b64decode(self.key_base64.get_secret_value(), validate=True)
        except ValueError:
            raise ValueError("cursor key must be valid base64") from None
        if len(raw) < 32:
            raise ValueError("cursor key must decode to at least 32 bytes")
        return self

    def decoded(self) -> bytes:
        return base64.b64decode(self.key_base64.get_secret_value(), validate=True)


class ErpCursorKeyring(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    active: ErpCursorKey = Field(repr=False)
    previous: tuple[ErpCursorKey, ...] = Field(default=(), repr=False)
    ttl_seconds: int = Field(default=300, strict=True, ge=30, le=900)

    @field_validator("previous", mode="before")
    @classmethod
    def immutable_previous(cls, value: Any) -> Any:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def unique_keys(self) -> "ErpCursorKeyring":
        ids = (self.active.key_id, *(key.key_id for key in self.previous))
        if len(ids) != len(set(ids)):
            raise ValueError("cursor key IDs must be unique")
        return self


class StaticErpDatabaseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    routes: tuple[ErpDatabaseRouteConfig, ...] = Field(min_length=1, repr=False)
    cursor_keyring: ErpCursorKeyring = Field(repr=False)
    minimum_pool_size: int = Field(default=1, strict=True, ge=0, le=20)
    maximum_pool_size: int = Field(default=5, strict=True, ge=1, le=50)
    statement_timeout_ms: int = Field(default=5_000, strict=True, ge=100, le=60_000)
    lock_timeout_ms: int = Field(default=2_000, strict=True, ge=100, le=60_000)
    idle_transaction_timeout_ms: int = Field(default=10_000, strict=True, ge=100, le=120_000)

    @field_validator("routes", mode="before")
    @classmethod
    def immutable_routes(cls, value: Any) -> Any:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def valid_routes(self) -> "StaticErpDatabaseConfig":
        customers = tuple(route.customer_environment_id for route in self.routes)
        databases = tuple(route.expected_database_name for route in self.routes)
        if len(customers) != len(set(customers)):
            raise ValueError("duplicate ERP customer routes are forbidden")
        if len(databases) != len(set(databases)):
            raise ValueError("ERP customer routes must use separate databases")
        if self.minimum_pool_size > self.maximum_pool_size:
            raise ValueError("minimum pool size cannot exceed maximum pool size")
        return self
