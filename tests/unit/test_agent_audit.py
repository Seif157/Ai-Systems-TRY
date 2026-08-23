from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from erp_ai.context import TrustedRequestContext
from erp_ai.orchestration.audit import create_agent_audit_event


def context() -> TrustedRequestContext:
    return TrustedRequestContext(
        context_version=1,
        request_id="request_1",
        customer_environment_id="customer_1",
        user_id="user_1",
        employee_id="employee_secret",
        roles=("role_secret",),
        permission_codes=("permission.secret",),
        legal_entity_ids=("entity_secret",),
        enabled_modules=("hr_core",),
        locale="en",
        timezone="Africa/Cairo",
        purpose="employee_self_service",
        issued_at=datetime(2026, 8, 23, tzinfo=ZoneInfo("Africa/Cairo")),
        authorization_snapshot_id="snapshot_secret",
    )


def test_agent_audit_has_exact_redacted_schema_and_is_frozen() -> None:
    event = create_agent_audit_event(context(), outcome="success", internal_reason="completed")
    assert set(event.model_dump()) == {
        "request_id",
        "customer_environment_id",
        "user_id",
        "purpose",
        "action",
        "outcome",
        "internal_reason",
    }
    serialized = repr(event.model_dump())
    for secret in (
        "employee_secret",
        "role_secret",
        "permission.secret",
        "entity_secret",
        "hr_core",
        "snapshot_secret",
    ):
        assert secret not in serialized
    with pytest.raises(ValidationError):
        event.outcome = "failure"  # type: ignore[misc]
