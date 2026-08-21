from datetime import datetime
from types import MappingProxyType
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from erp_ai.context import TrustedRequestContext, resolve_trusted_context
from tests.conftest import FakeTrustedContextProvider


def test_resolves_employee_context_and_normalizes_values(valid_claims: dict[str, object]) -> None:
    context = resolve_trusted_context(FakeTrustedContextProvider(valid_claims))

    assert context.locale == "ar-EG"
    assert context.roles == ("employee", "manager")
    assert context.permission_codes == ("leave_read", "profile_read")
    assert context.legal_entity_ids == ("entity-a", "entity-b")
    assert context.enabled_modules == ("hr_core", "leave")


def test_accepts_service_context_without_employee(valid_claims: dict[str, object]) -> None:
    valid_claims["employee_id"] = None
    valid_claims["locale"] = "en"

    context = resolve_trusted_context(FakeTrustedContextProvider(valid_claims))

    assert context.employee_id is None
    assert context.locale == "en"


@pytest.mark.parametrize(
    "field",
    [
        "context_version",
        "request_id",
        "customer_environment_id",
        "user_id",
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
def test_rejects_missing_required_claim(field: str, valid_claims: dict[str, object]) -> None:
    del valid_claims[field]

    with pytest.raises(ValidationError):
        resolve_trusted_context(FakeTrustedContextProvider(valid_claims))


@pytest.mark.parametrize("field", ["request_id", "customer_environment_id", "user_id"])
def test_rejects_blank_identifier(field: str, valid_claims: dict[str, object]) -> None:
    valid_claims[field] = "  "

    with pytest.raises(ValidationError):
        resolve_trusted_context(FakeTrustedContextProvider(valid_claims))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("roles", ["employee", " Employee "]),
        ("permission_codes", ["leave_read", "leave_read"]),
        ("enabled_modules", ["leave", "LEAVE"]),
        ("legal_entity_ids", ["entity-a", " entity-a "]),
    ],
)
def test_rejects_duplicates_after_normalization(
    field: str, value: list[str], valid_claims: dict[str, object]
) -> None:
    valid_claims[field] = value

    with pytest.raises(ValidationError, match="duplicate"):
        resolve_trusted_context(FakeTrustedContextProvider(valid_claims))


@pytest.mark.parametrize(
    ("field", "value"),
    [("roles", ["HR Admin"]), ("enabled_modules", ["leave-write"]), ("locale", "english")],
)
def test_rejects_malformed_codes(
    field: str, value: object, valid_claims: dict[str, object]
) -> None:
    valid_claims[field] = value

    with pytest.raises(ValidationError):
        resolve_trusted_context(FakeTrustedContextProvider(valid_claims))


def test_rejects_unknown_or_secret_fields(valid_claims: dict[str, object]) -> None:
    valid_claims["authorization_token"] = "must-not-enter-context"

    with pytest.raises(ValidationError):
        resolve_trusted_context(FakeTrustedContextProvider(valid_claims))


@pytest.mark.parametrize(
    ("field", "value"),
    [("roles", "employee"), ("legal_entity_ids", "entity-a"), ("locale", 123)],
)
def test_rejects_wrong_container_or_scalar_types(
    field: str, value: object, valid_claims: dict[str, object]
) -> None:
    valid_claims[field] = value

    with pytest.raises(ValidationError):
        resolve_trusted_context(FakeTrustedContextProvider(valid_claims))


def test_context_is_immutable(valid_claims: dict[str, object]) -> None:
    context = resolve_trusted_context(FakeTrustedContextProvider(valid_claims))

    with pytest.raises(ValidationError):
        context.customer_environment_id = "cust_env_b"  # type: ignore[misc]

    assert context.customer_environment_id == "cust_env_a"


def test_serialization_contains_only_declared_safe_fields(valid_claims: dict[str, object]) -> None:
    context = resolve_trusted_context(FakeTrustedContextProvider(MappingProxyType(valid_claims)))

    assert set(context.model_dump()) == set(TrustedRequestContext.model_fields)
    assert not {"token", "password", "credential", "connection"} & set(context.model_dump())


@pytest.mark.parametrize("version", [0, 2, "1"])
def test_context_version_accepts_only_integer_one(
    version: object, valid_claims: dict[str, object]
) -> None:
    valid_claims["context_version"] = version

    with pytest.raises(ValidationError):
        resolve_trusted_context(FakeTrustedContextProvider(valid_claims))


def test_permission_collection_is_immutable(valid_claims: dict[str, object]) -> None:
    context = resolve_trusted_context(FakeTrustedContextProvider(valid_claims))

    assert isinstance(context.permission_codes, tuple)
    with pytest.raises(ValidationError):
        context.permission_codes = ("admin",)  # type: ignore[misc]


def test_accepts_valid_iana_timezone(valid_claims: dict[str, object]) -> None:
    context = resolve_trusted_context(FakeTrustedContextProvider(valid_claims))

    assert context.timezone == "Africa/Cairo"


def test_rejects_invalid_iana_timezone(valid_claims: dict[str, object]) -> None:
    valid_claims["timezone"] = "Cairo/Invalid"

    with pytest.raises(ValidationError, match="IANA"):
        resolve_trusted_context(FakeTrustedContextProvider(valid_claims))


def test_accepts_timezone_aware_issued_at(valid_claims: dict[str, object]) -> None:
    issued_at = datetime(2026, 8, 21, 10, 0, tzinfo=ZoneInfo("UTC"))
    valid_claims["issued_at"] = issued_at

    context = resolve_trusted_context(FakeTrustedContextProvider(valid_claims))

    assert context.issued_at == issued_at


def test_rejects_naive_issued_at(valid_claims: dict[str, object]) -> None:
    valid_claims["issued_at"] = datetime(2026, 8, 21, 10, 0)

    with pytest.raises(ValidationError, match="timezone-aware"):
        resolve_trusted_context(FakeTrustedContextProvider(valid_claims))


@pytest.mark.parametrize("snapshot_id", ["", "   ", "contains spaces"])
def test_rejects_invalid_authorization_snapshot_id(
    snapshot_id: str, valid_claims: dict[str, object]
) -> None:
    valid_claims["authorization_snapshot_id"] = snapshot_id

    with pytest.raises(ValidationError):
        resolve_trusted_context(FakeTrustedContextProvider(valid_claims))


def test_fake_provider_returns_complete_context(valid_claims: dict[str, object]) -> None:
    context = resolve_trusted_context(FakeTrustedContextProvider(valid_claims))

    assert set(context.model_dump()) == set(TrustedRequestContext.model_fields)
