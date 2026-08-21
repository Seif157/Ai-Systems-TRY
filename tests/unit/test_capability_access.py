from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from erp_ai.capabilities import (
    CapabilityManifest,
    CapabilityRegistry,
    ToolDescriptor,
    evaluate_capability_access,
)
from erp_ai.context import TrustedRequestContext


def tool(
    name: str,
    *,
    operation: str = "read",
    permissions: tuple[str, ...] = (),
    roles: tuple[str, ...] = (),
    purposes: tuple[str, ...] = ("employee_self_service",),
) -> ToolDescriptor:
    return ToolDescriptor.model_validate(
        {
            "tool_name": name,
            "version": "1.0.0",
            "operation": operation,
            "required_permissions_all": permissions,
            "required_roles_any": roles,
            "allowed_purposes": purposes,
            "data_classification": "restricted",
            "audit_action": f"{name}_invoked",
        },
        strict=True,
    )


@pytest.fixture
def registry() -> CapabilityRegistry:
    """Synthetic manifests only; these are not production capability registrations."""

    manifests = (
        CapabilityManifest(
            capability_code="payroll",
            version="1.0.0",
            required_modules=("payroll",),
            tools=(tool("get_payslip", permissions=("payroll_read",), roles=("employee",)),),
        ),
        CapabilityManifest(
            capability_code="leave",
            version="1.0.0",
            required_modules=("hr_core", "leave"),
            tools=(
                tool("create_leave_request", operation="command", permissions=("leave_write",)),
                tool(
                    "get_leave_balance",
                    permissions=("leave_read", "profile_read"),
                    roles=("employee",),
                ),
                tool("get_leave_summary", roles=("hr", "manager")),
                tool("get_team_leave", permissions=("leave_read",), roles=("manager",)),
            ),
        ),
        CapabilityManifest(
            capability_code="hr_core",
            version="1.0.0",
            required_modules=("hr_core",),
            tools=(
                tool("get_hr_help"),
                tool("get_profile", permissions=("profile_read",), roles=("employee",)),
            ),
        ),
    )
    return CapabilityRegistry(manifests)


def context(
    customer: str,
    *,
    modules: tuple[str, ...],
    permissions: tuple[str, ...] = ("profile_read", "leave_read", "leave_write"),
    roles: tuple[str, ...] = ("employee",),
    purpose: str = "employee_self_service",
) -> TrustedRequestContext:
    return TrustedRequestContext(
        context_version=1,
        request_id=f"req_{customer}",
        customer_environment_id=customer,
        user_id="user_1",
        employee_id="employee_1",
        roles=roles,
        permission_codes=permissions,
        legal_entity_ids=("entity_1",),
        enabled_modules=modules,
        locale="en",
        timezone="Africa/Cairo",
        purpose=purpose,
        issued_at=datetime(2026, 8, 21, 12, 0, tzinfo=ZoneInfo("Africa/Cairo")),
        authorization_snapshot_id=f"snapshot_{customer}",
    )


def capability_codes(decision: object) -> tuple[str, ...]:
    assert hasattr(decision, "model_capabilities")
    return tuple(item.capability_code for item in decision.model_capabilities)


def tool_names(decision: object, capability_code: str) -> tuple[str, ...]:
    assert hasattr(decision, "model_capabilities")
    capability = next(
        item for item in decision.model_capabilities if item.capability_code == capability_code
    )
    return tuple(item.tool_name for item in capability.tools)


def test_hr_core_context_sees_only_hr_core(registry: CapabilityRegistry) -> None:
    decision = evaluate_capability_access(registry, context("a", modules=("hr_core",)))

    assert capability_codes(decision) == ("hr_core",)


def test_hr_core_and_leave_context_sees_both_not_payroll(
    registry: CapabilityRegistry,
) -> None:
    decision = evaluate_capability_access(registry, context("a", modules=("leave", "hr_core")))

    assert capability_codes(decision) == ("hr_core", "leave")
    assert "payroll" not in capability_codes(decision)


def test_missing_permission_hides_tool(registry: CapabilityRegistry) -> None:
    decision = evaluate_capability_access(
        registry,
        context("a", modules=("hr_core", "leave"), permissions=("profile_read",)),
    )

    assert "get_leave_balance" not in tool_names(decision, "leave")
    assert any(denial.reason == "required_permission_missing" for denial in decision.denials)


def test_every_required_permission_must_be_present(registry: CapabilityRegistry) -> None:
    decision = evaluate_capability_access(
        registry,
        context("a", modules=("hr_core", "leave"), permissions=("leave_read",)),
    )

    assert "get_leave_balance" not in tool_names(decision, "leave")


@pytest.mark.parametrize("role", ["manager", "hr"])
def test_any_required_role_is_sufficient(registry: CapabilityRegistry, role: str) -> None:
    decision = evaluate_capability_access(
        registry, context("a", modules=("hr_core", "leave"), roles=(role,))
    )

    assert "get_leave_summary" in tool_names(decision, "leave")


def test_empty_permission_and_role_requirements_add_no_restriction(
    registry: CapabilityRegistry,
) -> None:
    decision = evaluate_capability_access(
        registry,
        context("a", modules=("hr_core",), permissions=(), roles=("unrelated_role",)),
    )

    assert "get_hr_help" in tool_names(decision, "hr_core")


def test_missing_role_hides_tool(registry: CapabilityRegistry) -> None:
    decision = evaluate_capability_access(
        registry, context("a", modules=("hr_core", "leave"), roles=("employee",))
    )

    assert "get_team_leave" not in tool_names(decision, "leave")
    assert any(denial.reason == "required_role_missing" for denial in decision.denials)


def test_commands_hidden_by_default_in_read_only_mode(registry: CapabilityRegistry) -> None:
    read_only = evaluate_capability_access(registry, context("a", modules=("hr_core", "leave")))
    commands_allowed = evaluate_capability_access(
        registry, context("a", modules=("hr_core", "leave")), read_only_mode=False
    )

    assert "create_leave_request" not in tool_names(read_only, "leave")
    assert "create_leave_request" in tool_names(commands_allowed, "leave")


def test_allowed_purpose_exposes_tool(registry: CapabilityRegistry) -> None:
    decision = evaluate_capability_access(registry, context("a", modules=("hr_core",)))

    assert "get_profile" in tool_names(decision, "hr_core")


def test_rejected_purpose_hides_tool_and_records_internal_denial(
    registry: CapabilityRegistry,
) -> None:
    decision = evaluate_capability_access(
        registry,
        context("a", modules=("hr_core",), purpose="manager_self_service"),
    )

    assert tool_names(decision, "hr_core") == ()
    assert any(denial.reason == "purpose_not_allowed" for denial in decision.denials)


def test_purpose_denial_absent_from_model_facing_output(
    registry: CapabilityRegistry,
) -> None:
    decision = evaluate_capability_access(
        registry,
        context("a", modules=("hr_core",), purpose="manager_self_service"),
    )
    serialized = repr(tuple(item.model_dump() for item in decision.model_capabilities))

    assert "purpose_not_allowed" not in serialized
    assert "get_profile" not in serialized


def test_results_are_immutable_and_deterministic(registry: CapabilityRegistry) -> None:
    trusted_context = context("a", modules=("leave", "hr_core"))
    first = evaluate_capability_access(registry, trusted_context)
    second = evaluate_capability_access(registry, trusted_context)

    assert first == second
    assert isinstance(first.model_capabilities, tuple)
    assert tuple(item.capability_code for item in first.model_capabilities) == ("hr_core", "leave")
    with pytest.raises(ValidationError):
        first.model_capabilities = ()  # type: ignore[misc]


def test_customer_contexts_do_not_contaminate_each_other(registry: CapabilityRegistry) -> None:
    customer_a = evaluate_capability_access(registry, context("a", modules=("hr_core", "leave")))
    customer_b = evaluate_capability_access(registry, context("b", modules=("hr_core",)))

    assert capability_codes(customer_a) == ("hr_core", "leave")
    assert capability_codes(customer_b) == ("hr_core",)
    assert capability_codes(
        evaluate_capability_access(registry, context("a", modules=("hr_core", "leave")))
    ) == ("hr_core", "leave")


def test_denied_information_absent_from_model_facing_output(
    registry: CapabilityRegistry,
) -> None:
    decision = evaluate_capability_access(registry, context("a", modules=("hr_core",)))
    model_payload = tuple(item.model_dump() for item in decision.model_capabilities)
    serialized = repr(model_payload)

    assert "leave" not in serialized
    assert "payroll" not in serialized
    assert "denial" not in serialized
    assert "required_module_disabled" not in serialized
