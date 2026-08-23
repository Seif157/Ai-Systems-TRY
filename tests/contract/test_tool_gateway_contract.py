from erp_ai.tools import ToolErrorCode
from erp_ai.tools import audit as audit_module
from erp_ai.tools.errors import SAFE_ERROR_MESSAGES
from erp_ai.tools.gateway import RESERVED_ARGUMENT_NAMES


def test_public_error_codes_are_stable_and_have_safe_messages() -> None:
    assert {code.value for code in ToolErrorCode} == {
        "TOOL_UNAVAILABLE",
        "INVALID_TOOL_ARGUMENTS",
        "READ_ONLY_VIOLATION",
        "TOOL_EXECUTION_FAILED",
        "INVALID_TOOL_OUTPUT",
        "AUDIT_UNAVAILABLE",
    }
    assert set(SAFE_ERROR_MESSAGES) == set(ToolErrorCode)


def test_trusted_context_and_release_fields_except_record_selector_are_reserved() -> None:
    expected = {
        "context_version",
        "customer_environment_id",
        "user_id",
        "employee_id",
        "roles",
        "permission_codes",
        "legal_entity_ids",
        "enabled_modules",
        "locale",
        "timezone",
        "purpose",
        "issued_at",
        "authorization_snapshot_id",
        "read_only_mode",
    }
    assert expected == RESERVED_ARGUMENT_NAMES
    assert "request_id" not in RESERVED_ARGUMENT_NAMES


def test_safe_messages_contain_no_internal_diagnostics() -> None:
    serialized = " ".join(SAFE_ERROR_MESSAGES.values()).lower()

    for forbidden in (
        "permission",
        "role",
        "module",
        "stack",
        "validation",
        "exception",
        "capability",
    ):
        assert forbidden not in serialized


def test_no_production_noop_audit_sink_exists() -> None:
    assert not any("noop" in name.lower() for name in vars(audit_module))
