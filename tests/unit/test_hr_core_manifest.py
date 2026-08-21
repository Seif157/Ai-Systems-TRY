from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from erp_ai.capabilities import DataClassification, evaluate_capability_access
from erp_ai.capabilities.hr_core import HR_CORE_MANIFEST
from erp_ai.capabilities.registry import CapabilityRegistry
from tests.conftest import FakeTrustedContextProvider


def claims() -> dict[str, object]:
    return {
        "context_version": 1,
        "request_id": "req_a",
        "customer_environment_id": "customer_a",
        "user_id": "user_1",
        "employee_id": "employee_1",
        "roles": ["employee"],
        "permission_codes": ["hr.profile.read_self"],
        "legal_entity_ids": ["entity_1"],
        "enabled_modules": ["hr_core"],
        "locale": "en",
        "timezone": "Africa/Cairo",
        "purpose": "employee_self_service",
        "issued_at": datetime(2026, 8, 22, 9, 0, tzinfo=ZoneInfo("Africa/Cairo")),
        "authorization_snapshot_id": "snapshot_a",
    }


def test_hr_core_manifest_matches_governed_contract() -> None:
    assert HR_CORE_MANIFEST.capability_code == "hr_core"
    assert HR_CORE_MANIFEST.version == "1.0.0"
    assert HR_CORE_MANIFEST.required_modules == ("hr_core",)
    assert len(HR_CORE_MANIFEST.tools) == 1

    tool = HR_CORE_MANIFEST.tools[0]
    assert tool.tool_name == "get_my_employee_profile"
    assert tool.required_permissions_all == ("hr.profile.read_self",)
    assert tool.required_roles_any == ()
    assert tool.allowed_purposes == ("employee_self_service",)
    assert tool.data_classification is DataClassification.RESTRICTED
    assert tool.audit_action == "hr.profile.read_self"
    assert tool.requires_employee_context is True


def test_missing_employee_context_hides_profile_tool() -> None:
    from erp_ai.context import resolve_trusted_context

    trusted_claims = claims()
    trusted_claims["employee_id"] = None
    context = resolve_trusted_context(FakeTrustedContextProvider(trusted_claims))
    decision = evaluate_capability_access(CapabilityRegistry([HR_CORE_MANIFEST]), context)

    assert decision.model_capabilities[0].tools == ()
    assert decision.denials[0].reason == "employee_context_required"


def test_context_accepts_canonical_dotted_permission_codes() -> None:
    from erp_ai.context import resolve_trusted_context

    trusted_claims = claims()
    trusted_claims["permission_codes"] = ["hr.profile.read_self"]
    context = resolve_trusted_context(FakeTrustedContextProvider(trusted_claims))

    assert context.permission_codes == ("hr.profile.read_self",)


@pytest.mark.parametrize(
    "permission",
    [".hr.profile", "hr.profile.", "hr..profile", "hr. profile", "HR.profile", " hr.profile"],
)
def test_context_rejects_malformed_dotted_permission(permission: str) -> None:
    from erp_ai.context import resolve_trusted_context

    trusted_claims = claims()
    trusted_claims["permission_codes"] = [permission]

    with pytest.raises(ValidationError):
        resolve_trusted_context(FakeTrustedContextProvider(trusted_claims))


def test_context_rejects_non_collection_permission_input() -> None:
    from erp_ai.context import resolve_trusted_context

    trusted_claims = claims()
    trusted_claims["permission_codes"] = "hr.profile.read_self"

    with pytest.raises(ValidationError):
        resolve_trusted_context(FakeTrustedContextProvider(trusted_claims))
