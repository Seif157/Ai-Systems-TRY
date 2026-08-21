from types import MappingProxyType

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from erp_ai.tools import (
    PublicToolFailure,
    PublicToolSuccess,
    ToolErrorCode,
    ToolInvocation,
)


class OutputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    value: str


def test_invocation_is_strict_frozen_and_deeply_immutable() -> None:
    invocation = ToolInvocation.model_validate(
        {
            "tool_name": "get_profile",
            "version": "1.0.0",
            "arguments": {"filters": {"active": True}, "fields": ["name"]},
        },
        strict=True,
    )

    assert isinstance(invocation.arguments, MappingProxyType)
    assert isinstance(invocation.arguments["filters"], MappingProxyType)
    assert invocation.arguments["fields"] == ("name",)
    with pytest.raises(TypeError):
        invocation.arguments["extra"] = True  # type: ignore[index]
    with pytest.raises(ValidationError):
        invocation.version = "2.0.0"  # type: ignore[misc]


def test_invocation_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ToolInvocation.model_validate(
            {
                "tool_name": "get_profile",
                "version": "1.0.0",
                "arguments": {},
                "context": {},
            },
            strict=True,
        )


def test_invocation_rejects_mutable_non_json_values() -> None:
    with pytest.raises(ValidationError, match="JSON-compatible"):
        ToolInvocation.model_validate(
            {
                "tool_name": "get_profile",
                "version": "1.0.0",
                "arguments": {"mutable": {"value"}},
            },
            strict=True,
        )


def test_success_and_failure_results_are_immutable() -> None:
    success = PublicToolSuccess(
        tool_name="get_profile",
        version="1.0.0",
        result=OutputModel(value="ok"),
    )
    failure = PublicToolFailure(
        tool_name="get_profile",
        version="1.0.0",
        safe_error_code=ToolErrorCode.TOOL_UNAVAILABLE,
        safe_message="The requested tool is unavailable.",
    )

    with pytest.raises(ValidationError):
        success.tool_name = "changed"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        failure.safe_message = "changed"  # type: ignore[misc]


def test_public_result_serialization_contains_only_public_fields() -> None:
    success = PublicToolSuccess(
        tool_name="get_profile",
        version="1.0.0",
        result=OutputModel(value="ok"),
    )
    failure = PublicToolFailure(
        tool_name="get_profile",
        version="1.0.0",
        safe_error_code=ToolErrorCode.TOOL_UNAVAILABLE,
        safe_message="The requested tool is unavailable.",
    )

    assert set(success.model_dump()) == {"tool_name", "version", "result"}
    assert set(failure.model_dump()) == {
        "tool_name",
        "version",
        "safe_error_code",
        "safe_message",
    }
    serialized = repr((success.model_dump(), failure.model_dump()))
    for forbidden in (
        "audit",
        "internal_reason",
        "customer_environment_id",
        "user_id",
        "roles",
        "permissions",
        "enabled_modules",
        "purpose",
        "classification",
        "arguments",
    ):
        assert forbidden not in serialized
