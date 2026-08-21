import pytest
from pydantic import ValidationError

from erp_ai.capabilities import CapabilityManifest, DataClassification, ToolDescriptor


def tool_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "tool_name": "get_my_profile",
        "version": "1.0.0",
        "operation": "read",
        "required_permissions_all": ["profile_read"],
        "required_roles_any": ["employee"],
        "allowed_purposes": ["employee_self_service"],
        "data_classification": "restricted",
        "audit_action": "profile_viewed",
    }
    payload.update(overrides)
    return payload


def manifest_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "capability_code": "hr_core",
        "version": "1.0.0",
        "required_modules": ["hr_core"],
        "tools": [tool_payload()],
    }
    payload.update(overrides)
    return payload


def test_models_normalize_and_freeze_collections() -> None:
    tool = ToolDescriptor.model_validate(
        tool_payload(
            required_permissions_all=["profile_read", "employee_read"],
            required_roles_any=["Manager", "employee"],
            allowed_purposes=["Manager_Self_Service", "employee_self_service"],
            audit_action="profile_viewed",
        ),
        strict=True,
    )
    manifest = CapabilityManifest.model_validate(
        manifest_payload(required_modules=["LEAVE", "hr_core"], tools=[tool]), strict=True
    )

    assert tool.required_permissions_all == ("employee_read", "profile_read")
    assert tool.required_roles_any == ("employee", "manager")
    assert tool.allowed_purposes == ("employee_self_service", "manager_self_service")
    assert tool.audit_action == "profile_viewed"
    assert manifest.required_modules == ("hr_core", "leave")
    assert isinstance(manifest.tools, tuple)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tool_name", ""),
        ("tool_name", "invalid-tool"),
        ("required_permissions_all", ["leave_read", "leave_read"]),
        ("required_roles_any", ["employee", "EMPLOYEE"]),
        ("allowed_purposes", ["employee_self_service", " EMPLOYEE_SELF_SERVICE "]),
        ("audit_action", ""),
        ("audit_action", "invalid-action"),
    ],
)
def test_tool_rejects_invalid_or_duplicate_codes(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        ToolDescriptor.model_validate(tool_payload(**{field: value}), strict=True)


@pytest.mark.parametrize(
    "modules",
    [[], ["invalid-module"], ["leave", " LEAVE "]],
)
def test_manifest_rejects_invalid_or_duplicate_module_codes(modules: list[str]) -> None:
    with pytest.raises(ValidationError):
        CapabilityManifest.model_validate(manifest_payload(required_modules=modules), strict=True)


@pytest.mark.parametrize("policy_code", ["hr.profile.read_self", "leave.balance.read_self"])
def test_dotted_permission_and_audit_codes_are_scoped_to_policy_fields(
    policy_code: str,
) -> None:
    tool = ToolDescriptor.model_validate(
        tool_payload(
            required_permissions_all=[policy_code],
            audit_action=policy_code,
        ),
        strict=True,
    )

    assert tool.required_permissions_all == (policy_code,)
    assert tool.audit_action == policy_code


def test_permission_collection_rejects_non_collection_input() -> None:
    with pytest.raises(ValidationError):
        ToolDescriptor.model_validate(
            tool_payload(required_permissions_all="hr.profile.read_self"), strict=True
        )


@pytest.mark.parametrize(
    "permission",
    [".hr.profile", "hr.profile.", "hr..profile", "hr. profile", "HR.profile", " hr.profile"],
)
@pytest.mark.parametrize("field", ["required_permissions_all", "audit_action"])
def test_rejects_noncanonical_dotted_policy_codes(field: str, permission: str) -> None:
    value: object = [permission] if field == "required_permissions_all" else permission
    with pytest.raises(ValidationError):
        ToolDescriptor.model_validate(tool_payload(**{field: value}), strict=True)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("required_roles_any", ["hr.manager"]),
        ("allowed_purposes", ["employee.self_service"]),
    ],
)
def test_dotted_codes_are_rejected_from_role_and_purpose_fields(
    field: str, value: list[str]
) -> None:
    with pytest.raises(ValidationError):
        ToolDescriptor.model_validate(tool_payload(**{field: value}), strict=True)


@pytest.mark.parametrize(
    ("field", "value"),
    [("capability_code", "hr.core"), ("required_modules", ["hr.core"])],
)
def test_dotted_codes_are_rejected_from_manifest_namespaces(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        CapabilityManifest.model_validate(manifest_payload(**{field: value}), strict=True)


def test_manifest_rejects_duplicate_tools() -> None:
    with pytest.raises(ValidationError, match="duplicate tool"):
        CapabilityManifest.model_validate(
            manifest_payload(tools=[tool_payload(), tool_payload(version="2.0.0")]), strict=True
        )


@pytest.mark.parametrize("version", ["1.0.0", "2.4.13", "0.0.0"])
@pytest.mark.parametrize("model", ["tool", "manifest"])
def test_accepts_complete_release_versions(version: str, model: str) -> None:
    if model == "tool":
        result = ToolDescriptor.model_validate(tool_payload(version=version), strict=True)
    else:
        result = CapabilityManifest.model_validate(manifest_payload(version=version), strict=True)

    assert result.version == version


@pytest.mark.parametrize(
    "version", ["1", "1.0", "01.0.0", "1.01.0", "1.0.01", "1.0.0-alpha", "1.0.0+build"]
)
@pytest.mark.parametrize("model", ["tool", "manifest"])
def test_rejects_incomplete_or_extended_versions(version: str, model: str) -> None:
    with pytest.raises(ValidationError):
        if model == "tool":
            ToolDescriptor.model_validate(tool_payload(version=version), strict=True)
        else:
            CapabilityManifest.model_validate(manifest_payload(version=version), strict=True)


@pytest.mark.parametrize("classification", list(DataClassification))
def test_accepts_every_data_classification(classification: DataClassification) -> None:
    tool = ToolDescriptor.model_validate(
        tool_payload(data_classification=classification.value), strict=True
    )

    assert tool.data_classification is classification


def test_accepts_data_classification_enum_instance() -> None:
    tool = ToolDescriptor.model_validate(
        tool_payload(data_classification=DataClassification.INTERNAL), strict=True
    )

    assert tool.data_classification is DataClassification.INTERNAL


@pytest.mark.parametrize("classification", ["secret", 123])
def test_rejects_invalid_data_classification(classification: object) -> None:
    with pytest.raises(ValidationError, match="classification"):
        ToolDescriptor.model_validate(tool_payload(data_classification=classification), strict=True)


@pytest.mark.parametrize("purposes", [[], ["*"], ["invalid-purpose"]])
def test_rejects_empty_or_invalid_purposes(purposes: list[str]) -> None:
    with pytest.raises(ValidationError):
        ToolDescriptor.model_validate(tool_payload(allowed_purposes=purposes), strict=True)


@pytest.mark.parametrize("model", ["tool", "manifest"])
def test_models_reject_unknown_fields(model: str) -> None:
    with pytest.raises(ValidationError):
        if model == "tool":
            ToolDescriptor.model_validate(tool_payload(unknown=True), strict=True)
        else:
            CapabilityManifest.model_validate(manifest_payload(unknown=True), strict=True)


@pytest.mark.parametrize(
    ("field", "value"),
    [("required_modules", "hr_core"), ("tools", "get_profile")],
)
def test_manifest_rejects_wrong_collection_types(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        CapabilityManifest.model_validate(manifest_payload(**{field: value}), strict=True)
