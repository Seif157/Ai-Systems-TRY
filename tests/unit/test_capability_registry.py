from dataclasses import FrozenInstanceError

import pytest

from erp_ai.capabilities import CapabilityManifest, CapabilityRegistry, ToolDescriptor


def make_tool(name: str) -> ToolDescriptor:
    return ToolDescriptor(
        tool_name=name,
        version="1.0.0",
        operation="read",
        required_permissions_all=(),
        required_roles_any=(),
        allowed_purposes=("employee_self_service",),
        data_classification="internal",
        audit_action="registry_test_read",
    )


def make_manifest(code: str, tool_name: str) -> CapabilityManifest:
    return CapabilityManifest(
        capability_code=code,
        version="1.0.0",
        required_modules=(code,),
        tools=(make_tool(tool_name),),
    )


def test_registry_has_deterministic_order_and_lookup() -> None:
    leave = make_manifest("leave", "get_leave")
    hr_core = make_manifest("hr_core", "get_profile")

    registry = CapabilityRegistry([leave, hr_core])

    assert tuple(item.capability_code for item in registry.manifests) == ("hr_core", "leave")
    assert registry.get("leave") is leave
    assert registry.get("missing") is None


def test_registry_rejects_duplicate_capability_codes() -> None:
    with pytest.raises(ValueError, match="duplicate capability"):
        CapabilityRegistry(
            [make_manifest("hr_core", "get_profile"), make_manifest("hr_core", "get_employee")]
        )


def test_registry_rejects_duplicate_tool_names_across_capabilities() -> None:
    with pytest.raises(ValueError, match="duplicate tool"):
        CapabilityRegistry(
            [make_manifest("hr_core", "shared_tool"), make_manifest("leave", "shared_tool")]
        )


def test_registry_rejects_unvalidated_entries() -> None:
    with pytest.raises(TypeError, match="validated"):
        CapabilityRegistry([{"capability_code": "forged"}])  # type: ignore[list-item]


def test_registry_is_immutable() -> None:
    registry = CapabilityRegistry([make_manifest("hr_core", "get_profile")])

    with pytest.raises(FrozenInstanceError):
        registry.manifests = ()  # type: ignore[misc]

    assert isinstance(registry.manifests, tuple)
