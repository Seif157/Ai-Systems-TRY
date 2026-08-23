"""Strict repr-safe static PostgreSQL route configuration."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from erp_ai.context.models import Identifier


class KnowledgeDatabaseRouteConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    customer_environment_id: Identifier
    reader_dsn: SecretStr = Field(repr=False)
    publisher_dsn: SecretStr = Field(repr=False)
    migration_dsn: SecretStr = Field(repr=False)


class StaticKnowledgeDatabaseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    routes: tuple[KnowledgeDatabaseRouteConfig, ...] = Field(min_length=1, repr=False)
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
    def valid_routes(self) -> "StaticKnowledgeDatabaseConfig":
        customers = tuple(route.customer_environment_id for route in self.routes)
        if len(set(customers)) != len(customers):
            raise ValueError("duplicate customer database routes are forbidden")
        if self.minimum_pool_size > self.maximum_pool_size:
            raise ValueError("minimum pool size cannot exceed maximum pool size")
        return self
