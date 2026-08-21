from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from erp_ai.capabilities import DataClassification, ToolDescriptor
from erp_ai.context import TrustedRequestContext
from erp_ai.tools.audit import create_tool_audit_event


def context() -> TrustedRequestContext:
    return TrustedRequestContext(
        context_version=1,
        request_id="req_a",
        customer_environment_id="customer_a",
        user_id="user_1",
        employee_id="employee_secret",
        roles=("employee",),
        permission_codes=("profile_read",),
        legal_entity_ids=("entity_secret",),
        enabled_modules=("hr_core",),
        locale="en",
        timezone="Africa/Cairo",
        purpose="employee_self_service",
        issued_at=datetime(2026, 8, 21, 12, 0, tzinfo=ZoneInfo("Africa/Cairo")),
        authorization_snapshot_id="snapshot_a",
    )


def descriptor() -> ToolDescriptor:
    return ToolDescriptor(
        tool_name="get_profile",
        version="1.0.0",
        operation="read",
        required_permissions_all=("profile_read",),
        required_roles_any=("employee",),
        allowed_purposes=("employee_self_service",),
        data_classification=DataClassification.RESTRICTED,
        audit_action="profile_read",
    )


def test_audit_event_contains_only_approved_metadata() -> None:
    event = create_tool_audit_event(
        context=context(),
        tool_name="get_profile",
        tool_version="1.0.0",
        outcome="success",
        internal_reason="execution_succeeded",
        descriptor=descriptor(),
    )
    payload = event.model_dump()

    assert event.audit_action == "profile_read"
    assert event.data_classification is DataClassification.RESTRICTED
    assert not {
        "arguments",
        "result",
        "employee_id",
        "roles",
        "permission_codes",
        "enabled_modules",
        "legal_entity_ids",
    } & set(payload)
    serialized = repr(payload)
    for sensitive in ("employee_secret", "profile_read", "entity_secret", "hr_core"):
        if sensitive != event.audit_action:
            assert sensitive not in serialized


def test_unknown_tool_audit_uses_safe_defaults() -> None:
    event = create_tool_audit_event(
        context=context(),
        tool_name="unknown_tool",
        tool_version="1.0.0",
        outcome="failure",
        internal_reason="tool_not_authorized_or_installed",
        descriptor=None,
    )

    assert event.audit_action == "tool.invocation_denied"
    assert event.data_classification is DataClassification.INTERNAL


def test_audit_event_is_immutable() -> None:
    event = create_tool_audit_event(
        context=context(),
        tool_name="get_profile",
        tool_version="1.0.0",
        outcome="success",
        internal_reason="execution_succeeded",
        descriptor=descriptor(),
    )

    with pytest.raises(ValidationError):
        event.outcome = "failure"  # type: ignore[misc]
