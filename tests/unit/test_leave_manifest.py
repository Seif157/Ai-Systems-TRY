from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from erp_ai.capabilities import CapabilityRegistry, DataClassification, evaluate_capability_access
from erp_ai.capabilities.leave import LEAVE_MANIFEST
from erp_ai.context import TrustedRequestContext


def context(
    *,
    modules: tuple[str, ...] = ("hr_core", "leave"),
    employee_id: str | None = "employee_1",
    permissions: tuple[str, ...] = ("leave.balance.read_self",),
    purpose: str = "employee_self_service",
    roles: tuple[str, ...] = ("manager",),
) -> TrustedRequestContext:
    return TrustedRequestContext(
        context_version=1,
        request_id="req_a",
        customer_environment_id="customer_a",
        user_id="user_1",
        employee_id=employee_id,
        roles=roles,
        permission_codes=permissions,
        legal_entity_ids=("entity_1",),
        enabled_modules=modules,
        locale="en",
        timezone="Africa/Cairo",
        purpose=purpose,
        issued_at=datetime(2026, 8, 22, 9, 0, tzinfo=ZoneInfo("Africa/Cairo")),
        authorization_snapshot_id="snapshot_a",
    )


def test_leave_manifest_matches_governed_contract() -> None:
    assert LEAVE_MANIFEST.capability_code == "leave"
    assert LEAVE_MANIFEST.version == "1.0.0"
    assert LEAVE_MANIFEST.required_modules == ("hr_core", "leave")

    tool = LEAVE_MANIFEST.tools[0]
    assert tool.tool_name == "get_my_leave_balances"
    assert tool.required_permissions_all == ("leave.balance.read_self",)
    assert tool.required_roles_any == ()
    assert tool.allowed_purposes == ("employee_self_service",)
    assert tool.requires_employee_context is True
    assert tool.data_classification is DataClassification.RESTRICTED
    assert tool.audit_action == "leave.balance.read_self"


@pytest.mark.parametrize("modules", [("hr_core",), ("leave",), ()])
def test_both_hr_core_and_leave_entitlements_are_required(
    modules: tuple[str, ...],
) -> None:
    decision = evaluate_capability_access(
        CapabilityRegistry([LEAVE_MANIFEST]), context(modules=modules)
    )

    assert decision.model_capabilities == ()
    assert decision.denials[0].reason == "required_module_disabled"


@pytest.mark.parametrize(
    "trusted_context",
    [context(employee_id=None), context(permissions=()), context(purpose="manager_service")],
)
def test_missing_employee_permission_or_purpose_hides_tool(
    trusted_context: TrustedRequestContext,
) -> None:
    decision = evaluate_capability_access(CapabilityRegistry([LEAVE_MANIFEST]), trusted_context)

    assert decision.model_capabilities[0].tools == ()


@pytest.mark.parametrize("role", ["manager", "hr", "employee"])
def test_literal_employee_role_is_not_required(role: str) -> None:
    decision = evaluate_capability_access(
        CapabilityRegistry([LEAVE_MANIFEST]), context(roles=(role,))
    )

    assert decision.model_capabilities[0].tools[0].tool_name == "get_my_leave_balances"
