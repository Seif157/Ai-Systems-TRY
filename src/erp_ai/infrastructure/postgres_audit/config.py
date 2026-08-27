"""Strict, immutable and repr-safe audit database configuration."""

from typing import Any

from psycopg.conninfo import conninfo_to_dict
from psycopg.errors import ProgrammingError
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from erp_ai.context.models import Identifier


class ControlAuditDatabaseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)

    writer_dsn: SecretStr = Field(repr=False)
    migration_dsn: SecretStr = Field(repr=False)
    expected_database_name: Identifier = Field(repr=False)
    expected_database_identity: Identifier = Field(repr=False)
    writer_role: Identifier = Field(repr=False)

    @field_validator("writer_dsn", "migration_dsn")
    @classmethod
    def valid_dsn(cls, value: SecretStr) -> SecretStr:
        try:
            parsed = conninfo_to_dict(value.get_secret_value())
        except ProgrammingError:
            raise ValueError("audit database DSN is invalid") from None
        if not parsed.get("dbname") or not parsed.get("user"):
            raise ValueError("audit database DSN requires database and user")
        return value


class CustomerAuditDatabaseRoute(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)

    customer_environment_id: Identifier = Field(repr=False)
    writer_dsn: SecretStr = Field(repr=False)
    migration_dsn: SecretStr = Field(repr=False)
    expected_database_name: Identifier = Field(repr=False)
    expected_database_identity: Identifier = Field(repr=False)
    writer_role: Identifier = Field(repr=False)

    @field_validator("writer_dsn", "migration_dsn")
    @classmethod
    def valid_dsn(cls, value: SecretStr) -> SecretStr:
        return ControlAuditDatabaseConfig.valid_dsn(value)


class StaticAuditDatabaseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)

    control: ControlAuditDatabaseConfig = Field(repr=False)
    customers: tuple[CustomerAuditDatabaseRoute, ...] = Field(min_length=1, repr=False)
    minimum_pool_size: int = Field(default=1, strict=True, ge=0, le=20)
    maximum_pool_size: int = Field(default=5, strict=True, ge=1, le=50)
    connection_timeout_seconds: float = Field(default=5.0, strict=True, gt=0, le=30)
    statement_timeout_ms: int = Field(default=5_000, strict=True, ge=100, le=60_000)
    lock_timeout_ms: int = Field(default=2_000, strict=True, ge=100, le=60_000)
    idle_transaction_timeout_ms: int = Field(default=10_000, strict=True, ge=100, le=120_000)

    @field_validator("customers", mode="before")
    @classmethod
    def immutable_customers(cls, value: Any) -> Any:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def unique_routes(self) -> "StaticAuditDatabaseConfig":
        customers = tuple(route.customer_environment_id for route in self.customers)
        names = (
            self.control.expected_database_name,
            *(r.expected_database_name for r in self.customers),
        )
        identities = (
            self.control.expected_database_identity,
            *(r.expected_database_identity for r in self.customers),
        )
        if len(customers) != len(set(customers)):
            raise ValueError("duplicate customer audit routes are forbidden")
        if len(names) != len(set(names)) or len(identities) != len(set(identities)):
            raise ValueError("audit databases and identities must be distinct")
        if self.minimum_pool_size > self.maximum_pool_size:
            raise ValueError("minimum pool size cannot exceed maximum pool size")
        return self


class RuntimeControlAuditDatabaseConfig(BaseModel):
    """Runtime-only control authority; migration credentials are excluded."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )
    writer_dsn: SecretStr = Field(repr=False)
    expected_database_name: Identifier = Field(repr=False)
    expected_database_identity: Identifier = Field(repr=False)
    writer_role: Identifier = Field(repr=False)

    @field_validator("writer_dsn")
    @classmethod
    def valid_dsn(cls, value: SecretStr) -> SecretStr:
        return ControlAuditDatabaseConfig.valid_dsn(value)


class RuntimeCustomerAuditDatabaseRoute(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )
    customer_environment_id: Identifier = Field(repr=False)
    writer_dsn: SecretStr = Field(repr=False)
    expected_database_name: Identifier = Field(repr=False)
    expected_database_identity: Identifier = Field(repr=False)
    writer_role: Identifier = Field(repr=False)

    @field_validator("writer_dsn")
    @classmethod
    def valid_dsn(cls, value: SecretStr) -> SecretStr:
        return ControlAuditDatabaseConfig.valid_dsn(value)


class RuntimeAuditDatabaseConfig(BaseModel):
    """The only PostgreSQL authority retained by a composed runtime."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )
    control: RuntimeControlAuditDatabaseConfig = Field(repr=False)
    customers: tuple[RuntimeCustomerAuditDatabaseRoute, ...] = Field(min_length=1, repr=False)
    minimum_pool_size: int = Field(default=1, strict=True, ge=0, le=20)
    maximum_pool_size: int = Field(default=5, strict=True, ge=1, le=50)
    connection_timeout_seconds: float = Field(default=5.0, strict=True, gt=0, le=30)
    statement_timeout_ms: int = Field(default=5_000, strict=True, ge=100, le=60_000)
    lock_timeout_ms: int = Field(default=2_000, strict=True, ge=100, le=60_000)
    idle_transaction_timeout_ms: int = Field(default=10_000, strict=True, ge=100, le=120_000)

    @field_validator("customers", mode="before")
    @classmethod
    def immutable_customers(cls, value: Any) -> Any:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def unique_routes(self) -> "RuntimeAuditDatabaseConfig":
        customers = tuple(route.customer_environment_id for route in self.customers)
        names = (
            self.control.expected_database_name,
            *(r.expected_database_name for r in self.customers),
        )
        identities = (
            self.control.expected_database_identity,
            *(r.expected_database_identity for r in self.customers),
        )
        if len(customers) != len(set(customers)):
            raise ValueError("duplicate customer audit routes are forbidden")
        if len(names) != len(set(names)) or len(identities) != len(set(identities)):
            raise ValueError("audit databases and identities must be distinct")
        if self.minimum_pool_size > self.maximum_pool_size:
            raise ValueError("minimum pool size cannot exceed maximum pool size")
        return self

    @classmethod
    def from_static(cls, config: StaticAuditDatabaseConfig) -> "RuntimeAuditDatabaseConfig":
        validated = StaticAuditDatabaseConfig.model_validate(
            config.model_dump(mode="python"), strict=True
        )
        return cls(
            control=RuntimeControlAuditDatabaseConfig(
                writer_dsn=validated.control.writer_dsn,
                expected_database_name=validated.control.expected_database_name,
                expected_database_identity=validated.control.expected_database_identity,
                writer_role=validated.control.writer_role,
            ),
            customers=tuple(
                RuntimeCustomerAuditDatabaseRoute(
                    customer_environment_id=route.customer_environment_id,
                    writer_dsn=route.writer_dsn,
                    expected_database_name=route.expected_database_name,
                    expected_database_identity=route.expected_database_identity,
                    writer_role=route.writer_role,
                )
                for route in validated.customers
            ),
            minimum_pool_size=validated.minimum_pool_size,
            maximum_pool_size=validated.maximum_pool_size,
            connection_timeout_seconds=validated.connection_timeout_seconds,
            statement_timeout_ms=validated.statement_timeout_ms,
            lock_timeout_ms=validated.lock_timeout_ms,
            idle_transaction_timeout_ms=validated.idle_transaction_timeout_ms,
        )
