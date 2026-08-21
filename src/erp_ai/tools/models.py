"""Strict immutable request and result envelopes for tool execution."""

from collections.abc import Mapping
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, Field, field_validator

from erp_ai.capabilities.models import Code, Version
from erp_ai.tools.errors import ToolErrorCode


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError("arguments must contain only JSON-compatible values")


class ToolInvocation(BaseModel):
    """Model-requested tool data; trusted context is deliberately absent."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, arbitrary_types_allowed=True
    )

    tool_name: Code
    version: Version
    arguments: Mapping[str, object] = Field(repr=False)

    @field_validator("arguments", mode="after")
    @classmethod
    def freeze_arguments(cls, value: Mapping[str, object]) -> Mapping[str, object]:
        frozen = _freeze(value)
        assert isinstance(frozen, Mapping)
        return frozen


class PublicToolSuccess(BaseModel):
    """Verified handler output safe for a public or model-facing adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    tool_name: str
    version: str
    result: BaseModel


class PublicToolFailure(BaseModel):
    """Failure details safe for a public or model-facing adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    tool_name: str
    version: str
    safe_error_code: ToolErrorCode
    safe_message: str


type PublicToolResult = PublicToolSuccess | PublicToolFailure
