from collections.abc import Iterable

import pytest
from pydantic import ValidationError

from erp_ai.context import resolve_trusted_context, to_audit_record
from tests.conftest import FakeTrustedContextProvider


def _sensitive_values(claims: dict[str, object]) -> Iterable[object]:
    yield claims["employee_id"]
    for field in ("roles", "permission_codes", "legal_entity_ids", "enabled_modules"):
        values = claims[field]
        assert isinstance(values, list)
        yield from values


def test_sensitive_values_are_absent_from_context_repr(valid_claims: dict[str, object]) -> None:
    context = resolve_trusted_context(FakeTrustedContextProvider(valid_claims))
    representation = repr(context)

    for sensitive_value in _sensitive_values(valid_claims):
        assert repr(sensitive_value) not in representation


def test_audit_record_contains_counts_not_sensitive_values(
    valid_claims: dict[str, object],
) -> None:
    context = resolve_trusted_context(FakeTrustedContextProvider(valid_claims))
    record = to_audit_record(context)
    serialized = record.model_dump()

    assert record.employee_linked is True
    assert record.role_count == 2
    assert record.permission_count == 2
    assert record.legal_entity_count == 2
    assert record.enabled_module_count == 2
    assert not {
        "employee_id",
        "roles",
        "permission_codes",
        "legal_entity_ids",
        "enabled_modules",
    } & set(serialized)

    serialized_text = repr(serialized)
    for sensitive_value in _sensitive_values(valid_claims):
        assert repr(sensitive_value) not in serialized_text


def test_audit_record_is_immutable(valid_claims: dict[str, object]) -> None:
    context = resolve_trusted_context(FakeTrustedContextProvider(valid_claims))
    record = to_audit_record(context)

    with pytest.raises(ValidationError):
        record.role_count = 999  # type: ignore[misc]
