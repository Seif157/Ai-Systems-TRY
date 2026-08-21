"""Strict immutable contracts for capability and tool registration."""

import re
from enum import Enum
from typing import Annotated, Any, Literal

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
_VERSION_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")

Code = Annotated[
    str,
    BeforeValidator(lambda value: value.strip().lower() if isinstance(value, str) else value),
    StringConstraints(strict=True, pattern=_CODE_PATTERN),
]
Version = Annotated[
    str,
    BeforeValidator(lambda value: value.strip() if isinstance(value, str) else value),
    StringConstraints(strict=True, pattern=_VERSION_PATTERN),
]
PolicyCode = Annotated[
    str,
    StringConstraints(strict=True, pattern=_POLICY_CODE_PATTERN),
]


def _normalize_codes(value: Any) -> Any:
    if not isinstance(value, (list, tuple)):
        return value
    normalized = tuple(item.strip().lower() if isinstance(item, str) else item for item in value)
    if len(set(normalized)) != len(normalized):
        raise ValueError("duplicate codes are not allowed")
    return tuple(sorted(normalized))


class DataClassification(str, Enum):
    """Governed data sensitivity associated with a registered tool."""

    PUBLIC = "public"
    INTERNAL = "internal"
    RESTRICTED = "restricted"
    HIGHLY_RESTRICTED = "highly_restricted"


class ToolDescriptor(BaseModel):
    """Registration metadata for a typed tool; contains no executable implementation."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    tool_name: Code
    version: Version
    operation: Literal["read", "command"]
    required_permissions_all: tuple[PolicyCode, ...] = Field(repr=False)
    required_roles_any: tuple[Code, ...] = Field(repr=False)
    allowed_purposes: tuple[Code, ...] = Field(min_length=1, repr=False)
    data_classification: DataClassification
    audit_action: PolicyCode
    requires_employee_context: bool = False

    @field_validator("required_roles_any", "allowed_purposes", mode="before")
    @classmethod
    def normalize_authorization_codes(cls, value: Any) -> Any:
        return _normalize_codes(value)

    @field_validator("required_permissions_all", mode="before")
    @classmethod
    def validate_and_order_permissions(cls, value: Any) -> Any:
        if not isinstance(value, (list, tuple)):
            return value
        if len(set(value)) != len(value):
            raise ValueError("duplicate codes are not allowed")
        return tuple(sorted(value))

    @field_validator("data_classification", mode="before")
    @classmethod
    def normalize_data_classification(cls, value: Any) -> Any:
        if isinstance(value, str):
            try:
                return DataClassification(value.strip().lower())
            except ValueError as error:
                raise ValueError("invalid data classification") from error
        return value


class CapabilityManifest(BaseModel):
    """Validated, immutable declaration of one modular capability."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    capability_code: Code
    version: Version
    required_modules: tuple[Code, ...] = Field(min_length=1, repr=False)
    tools: tuple[ToolDescriptor, ...]

    @field_validator("required_modules", mode="before")
    @classmethod
    def normalize_required_modules(cls, value: Any) -> Any:
        return _normalize_codes(value)

    @field_validator("tools", mode="before")
    @classmethod
    def normalize_tools(cls, value: Any) -> Any:
        if isinstance(value, list):
            return tuple(value)
        return value

    @field_validator("tools")
    @classmethod
    def validate_and_order_tools(
        cls, value: tuple[ToolDescriptor, ...]
    ) -> tuple[ToolDescriptor, ...]:
        names = tuple(tool.tool_name for tool in value)
        if len(set(names)) != len(names):
            raise ValueError("duplicate tool names are not allowed")
        return tuple(sorted(value, key=lambda tool: tool.tool_name))
