import pytest
from pydantic import ValidationError

from erp_ai.api import ChatRequest


def test_accepts_minimal_public_request() -> None:
    request = ChatRequest.model_validate({"message": "What is the leave policy?"}, strict=True)

    assert request.message == "What is the leave policy?"
    assert request.stream is False


@pytest.mark.parametrize(
    "trusted_field",
    [
        "customer_environment_id",
        "user_id",
        "employee_id",
        "roles",
        "legal_entity_ids",
        "enabled_modules",
        "locale",
        "purpose",
    ],
)
def test_rejects_trusted_fields(trusted_field: str) -> None:
    payload: dict[str, object] = {"message": "Show my leave balance", trusted_field: "forged"}

    with pytest.raises(ValidationError):
        ChatRequest.model_validate(payload, strict=True)


def test_rejects_any_unknown_field() -> None:
    with pytest.raises(ValidationError):
        ChatRequest.model_validate({"message": "Hello", "unexpected": True}, strict=True)


def test_public_package_exposes_no_command_interface() -> None:
    import erp_ai.api as public_api

    assert public_api.__all__ == ["ChatRequest"]
    assert not any(
        "command" in name.lower() or "write" in name.lower() for name in public_api.__all__
    )
