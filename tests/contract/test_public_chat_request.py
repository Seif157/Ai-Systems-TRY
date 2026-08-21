import pytest
from pydantic import ValidationError

from erp_ai.api import PublicChatRequest


def test_accepts_minimal_public_request() -> None:
    request = PublicChatRequest.model_validate(
        {"message": "What is the leave policy?"}, strict=True
    )

    assert request.message == "What is the leave policy?"
    assert request.stream is False
    assert request.preferred_response_language is None


def test_accepts_and_normalizes_preferred_response_language() -> None:
    request = PublicChatRequest.model_validate(
        {"message": "Explain my balance", "preferred_response_language": "ar-eg"}, strict=True
    )

    assert request.preferred_response_language == "ar-EG"


@pytest.mark.parametrize(
    "trusted_field",
    [
        "context_version",
        "request_id",
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
    ],
)
def test_rejects_trusted_fields(trusted_field: str) -> None:
    payload: dict[str, object] = {"message": "Show my leave balance", trusted_field: "forged"}

    with pytest.raises(ValidationError):
        PublicChatRequest.model_validate(payload, strict=True)


def test_rejects_any_unknown_field() -> None:
    with pytest.raises(ValidationError):
        PublicChatRequest.model_validate({"message": "Hello", "unexpected": True}, strict=True)


def test_rejects_read_only_mode_control() -> None:
    with pytest.raises(ValidationError):
        PublicChatRequest.model_validate(
            {"message": "Create leave", "read_only_mode": False}, strict=True
        )


@pytest.mark.parametrize("language", ["english", 123])
def test_rejects_invalid_preferred_response_language(language: object) -> None:
    with pytest.raises(ValidationError):
        PublicChatRequest.model_validate(
            {"message": "Hello", "preferred_response_language": language}, strict=True
        )


def test_public_package_exposes_no_command_interface() -> None:
    import erp_ai.api as public_api

    assert public_api.__all__ == ["PublicChatRequest"]
    assert not any(
        "command" in name.lower() or "write" in name.lower() for name in public_api.__all__
    )
