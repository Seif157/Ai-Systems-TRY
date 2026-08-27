"""Strict server-owned HTTP transport configuration."""

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

_HOST_PATTERN = re.compile(r"^(?:[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?)(?::([1-9][0-9]{0,4}))?$")


class InternalHttpTransportConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)

    allowed_hosts: tuple[str, ...] = Field(min_length=1, repr=False)
    require_https: bool = True
    maximum_body_bytes: int = Field(default=16_384, strict=True, ge=256, le=1_048_576)
    maximum_authorization_bytes: int = Field(default=4_096, strict=True, ge=32, le=16_384)

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def freeze_hosts(cls, value: Any) -> Any:
        if isinstance(value, list):
            value = tuple(value)
        if isinstance(value, tuple) and any(
            type(host) is not str or host != host.strip() for host in value
        ):
            raise ValueError("allowed hosts must be exact host values")
        return value

    @field_validator("allowed_hosts")
    @classmethod
    def validate_hosts(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(host.lower() for host in value)
        for host in normalized:
            match = _HOST_PATTERN.fullmatch(host)
            if match is None or ".." in host:
                raise ValueError("allowed hosts must be exact host values")
            if match.group(1) is not None and int(match.group(1)) > 65_535:
                raise ValueError("allowed hosts must be exact host values")
        if len(normalized) != len(set(normalized)):
            raise ValueError("duplicate allowed hosts are forbidden")
        return normalized
