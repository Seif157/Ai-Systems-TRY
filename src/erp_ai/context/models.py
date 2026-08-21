"""Immutable models for security-sensitive server-owned request context."""

import re
from datetime import datetime
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_POLICY_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
_LOCALE_PATTERN = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")


def _strip_string(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


Identifier = Annotated[
    str,
    BeforeValidator(_strip_string),
    StringConstraints(strict=True, min_length=1, max_length=128, pattern=r"^[^\s\x00-\x1f\x7f]+$"),
]
Code = Annotated[
    str,
    BeforeValidator(lambda value: value.strip().lower() if isinstance(value, str) else value),
    StringConstraints(strict=True, pattern=_CODE_PATTERN),
]
PolicyCode = Annotated[
    str,
    StringConstraints(strict=True, pattern=_POLICY_CODE_PATTERN),
]


class TrustedRequestContext(BaseModel):
    """Security context resolved by trusted application services, never public input."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    context_version: Literal[1]
    request_id: Identifier
    customer_environment_id: Identifier
    user_id: Identifier
    employee_id: Identifier | None = Field(default=None, repr=False)
    roles: tuple[Code, ...] = Field(min_length=1, repr=False)
    permission_codes: tuple[PolicyCode, ...] = Field(repr=False)
    legal_entity_ids: tuple[Identifier, ...] = Field(min_length=1, repr=False)
    enabled_modules: tuple[Code, ...] = Field(repr=False)
    locale: str
    timezone: str
    purpose: Code
    issued_at: datetime
    authorization_snapshot_id: Identifier

    @field_validator("roles", "enabled_modules", mode="before")
    @classmethod
    def normalize_codes(cls, value: Any) -> Any:
        if not isinstance(value, (list, tuple)):
            return value
        normalized = tuple(
            item.strip().lower() if isinstance(item, str) else item for item in value
        )
        if len(set(normalized)) != len(normalized):
            raise ValueError("duplicate values are not allowed")
        return tuple(sorted(normalized))

    @field_validator("permission_codes", mode="before")
    @classmethod
    def validate_and_order_permission_codes(cls, value: Any) -> Any:
        if not isinstance(value, (list, tuple)):
            return value
        if len(set(value)) != len(value):
            raise ValueError("duplicate values are not allowed")
        return tuple(sorted(value))

    @field_validator("legal_entity_ids", mode="before")
    @classmethod
    def normalize_identifiers(cls, value: Any) -> Any:
        if not isinstance(value, (list, tuple)):
            return value
        normalized = tuple(item.strip() if isinstance(item, str) else item for item in value)
        if len(set(normalized)) != len(normalized):
            raise ValueError("duplicate values are not allowed")
        return tuple(sorted(normalized))

    @field_validator("locale", mode="before")
    @classmethod
    def normalize_locale(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        parts = value.strip().split("-")
        normalized = "-".join([parts[0].lower(), *(part.upper() for part in parts[1:])])
        if not _LOCALE_PATTERN.fullmatch(normalized):
            raise ValueError("locale must be a valid language tag")
        return normalized

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("timezone must be a valid IANA timezone name") from error
        return value

    @field_validator("issued_at")
    @classmethod
    def validate_issued_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("issued_at must be timezone-aware")
        return value
