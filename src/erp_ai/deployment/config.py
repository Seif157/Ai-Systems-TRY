"""Strict bounded non-secret production configuration."""

import json
from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

DEPLOYMENT_CONFIG_PATH: Final = Path("/etc/erp-ai/runtime.json")
DEPLOYMENT_CONFIG_CONTRACT_VERSION: Final = "1.0.0"
MAXIMUM_CONFIG_BYTES: Final = 1_048_576
MAXIMUM_CONFIG_DEPTH: Final = 12

SecretReference = Annotated[
    str,
    StringConstraints(
        strict=True, min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._/-]*$"
    ),
]


class ServerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    bind_address: Literal["0.0.0.0", "127.0.0.1"]
    port: int = Field(strict=True, ge=1024, le=65535)
    workers: Literal[1]
    concurrency_limit: int = Field(strict=True, ge=1, le=1024)
    backlog: int = Field(strict=True, ge=1, le=4096)
    keep_alive_seconds: int = Field(strict=True, ge=1, le=30)
    startup_timeout_seconds: int = Field(strict=True, ge=1, le=300)
    graceful_shutdown_seconds: int = Field(strict=True, ge=1, le=300)


class StaticCustomerRoute(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)

    customer_environment_id: SecretReference = Field(repr=False)
    audit_runtime_dsn_reference: SecretReference = Field(repr=False)
    knowledge_runtime_dsn_reference: SecretReference = Field(repr=False)
    openai_credential_reference: SecretReference = Field(repr=False)
    openai_project_route_id: SecretReference = Field(repr=False)


class ProductionDeploymentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)

    contract_version: Literal["1.0.0"]
    deployment_version: SecretReference
    server: ServerSettings
    runtime_catalog_reference: SecretReference = Field(repr=False)
    erp_trust_config_reference: SecretReference = Field(repr=False)
    laravel_config_reference: SecretReference = Field(repr=False)
    audit_control_dsn_reference: SecretReference = Field(repr=False)
    customer_routes: tuple[StaticCustomerRoute, ...] = Field(min_length=1, repr=False)

    @field_validator("customer_routes", mode="before")
    @classmethod
    def freeze_routes(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("customer_routes")
    @classmethod
    def unique_routes(
        cls, value: tuple[StaticCustomerRoute, ...]
    ) -> tuple[StaticCustomerRoute, ...]:
        customers = tuple(route.customer_environment_id for route in value)
        project_routes = tuple(route.openai_project_route_id for route in value)
        if len(customers) != len(set(customers)) or len(project_routes) != len(set(project_routes)):
            raise ValueError("duplicate production routes are forbidden")
        return value


DEPLOYMENT_CONFIG_DESCRIPTOR: Final[dict[str, object]] = {
    "domain": "erp_ai.production_deployment_config",
    "version": DEPLOYMENT_CONFIG_CONTRACT_VERSION,
    "path": "/etc/erp-ai/runtime.json",
    "encoding": "strict_utf8_compact_json",
    "limits": {"bytes": MAXIMUM_CONFIG_BYTES, "depth": MAXIMUM_CONFIG_DEPTH},
    "server": [
        "bind_address",
        "port",
        "workers_one",
        "concurrency_limit",
        "backlog",
        "keep_alive_seconds",
        "startup_timeout_seconds",
        "graceful_shutdown_seconds",
    ],
    "security": [
        "unknown_fields_forbidden",
        "strict_types",
        "finite_values",
        "duplicate_keys_forbidden",
        "no_interpolation",
        "no_secret_values",
        "static_customer_routes",
    ],
}


def canonical_deployment_config_contract_bytes() -> bytes:
    return json.dumps(
        DEPLOYMENT_CONFIG_DESCRIPTOR,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False,
        allow_nan=False,
    ).encode("utf-8")


DEPLOYMENT_CONFIG_CONTRACT_DIGEST: Final = (
    "692bb923560244b3eb397fbefa38e3f00ce0165e0436f60dde5007077e63b544"
)


def _strict_json(raw: bytes) -> object:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError("invalid deployment configuration")
            result[key] = value
        return result

    def reject_constant(_: str) -> object:
        raise ValueError("invalid deployment configuration")

    return json.loads(
        raw.decode("utf-8", errors="strict"),
        object_pairs_hook=pairs,
        parse_constant=reject_constant,
    )


def _depth(value: object, level: int = 1) -> int:
    if isinstance(value, dict):
        return max((_depth(item, level + 1) for item in value.values()), default=level)
    if isinstance(value, list):
        return max((_depth(item, level + 1) for item in value), default=level)
    return level


def load_production_config(path: Path = DEPLOYMENT_CONFIG_PATH) -> ProductionDeploymentConfig:
    """Load exactly one bounded deployment-mounted file after explicit invocation."""

    try:
        raw = path.read_bytes()
        if not raw or len(raw) > MAXIMUM_CONFIG_BYTES:
            raise ValueError
        value = _strict_json(raw)
        if _depth(value) > MAXIMUM_CONFIG_DEPTH:
            raise ValueError
        return ProductionDeploymentConfig.model_validate_json(raw, strict=True)
    except Exception:
        raise ValueError("invalid deployment configuration") from None
