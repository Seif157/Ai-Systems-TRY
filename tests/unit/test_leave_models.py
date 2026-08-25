from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from erp_ai.capabilities.leave import (
    GetMyLeaveBalancesInput,
    GetMyLeaveBalancesOutput,
    LeaveBalanceItem,
    LeaveBalanceRecord,
)


def record_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "employee_id": "employee_1",
        "legal_entity_id": "entity_1",
        "leave_type_id": "type_annual",
        "leave_type_code": "annual",
        "leave_type_name": "Annual Leave",
        "leave_type_name_local": "Synthetic Local Name",
        "fiscal_year": 2026,
        "opening_days": Decimal("10.00"),
        "accrued_days": Decimal("5.50"),
        "used_days": Decimal("3.00"),
        "pending_days": Decimal("1.00"),
        "available_days": Decimal("11.50"),
        "calculated_at": datetime(2026, 8, 22, 9, 0, tzinfo=ZoneInfo("Africa/Cairo")),
        "source_watermark": "ledger_2026_08_22_001",
        "calculation_version": "1.0.0",
    }
    payload.update(overrides)
    return payload


def item_payload(**overrides: object) -> dict[str, object]:
    payload = record_payload(**overrides)
    for field in ("employee_id", "legal_entity_id", "leave_type_id", "source_watermark"):
        payload.pop(field)
    return payload


def test_empty_input_is_strict_frozen_and_accepts_only_empty_arguments() -> None:
    model = GetMyLeaveBalancesInput.model_validate({}, strict=True)
    assert model.model_dump() == {}

    with pytest.raises(ValidationError):
        GetMyLeaveBalancesInput.model_validate({"fiscal_year": 2026}, strict=True)
    with pytest.raises(ValidationError):
        model.extra = True  # type: ignore[attr-defined]


def test_record_and_safe_item_preserve_decimal_values() -> None:
    record = LeaveBalanceRecord.model_validate(record_payload(), strict=True)
    item = LeaveBalanceItem.model_validate(item_payload(), strict=True)

    assert isinstance(record.available_days, Decimal)
    assert isinstance(item.available_days, Decimal)
    assert not any(isinstance(value, float) for value in item.model_dump().values())


@pytest.mark.parametrize("field", ["opening_days", "accrued_days", "used_days", "pending_days"])
def test_component_values_must_be_nonnegative(field: str) -> None:
    with pytest.raises(ValidationError):
        LeaveBalanceRecord.model_validate(record_payload(**{field: Decimal("-0.01")}), strict=True)


def test_available_days_may_be_negative() -> None:
    record = LeaveBalanceRecord.model_validate(
        record_payload(available_days=Decimal("-12.25")), strict=True
    )

    assert record.available_days == Decimal("-12.25")


@pytest.mark.parametrize(
    "field",
    ["opening_days", "accrued_days", "used_days", "pending_days", "available_days"],
)
def test_day_values_reject_more_than_two_decimal_places(field: str) -> None:
    with pytest.raises(ValidationError):
        LeaveBalanceRecord.model_validate(record_payload(**{field: Decimal("1.001")}), strict=True)


@pytest.mark.parametrize("value", [Decimal("100000.00"), Decimal("-100000.00")])
def test_numeric_7_2_bounds_are_enforced(value: Decimal) -> None:
    with pytest.raises(ValidationError):
        LeaveBalanceRecord.model_validate(record_payload(available_days=value), strict=True)


@pytest.mark.parametrize("year", [999, 10000, "2026"])
def test_fiscal_year_must_be_a_strict_four_digit_integer(year: object) -> None:
    with pytest.raises(ValidationError):
        LeaveBalanceRecord.model_validate(record_payload(fiscal_year=year), strict=True)


@pytest.mark.parametrize("model", [LeaveBalanceRecord, LeaveBalanceItem])
def test_calculated_at_must_be_timezone_aware(model: type[object]) -> None:
    payload = (
        record_payload(calculated_at=datetime(2026, 8, 22, 9, 0))
        if model is LeaveBalanceRecord
        else item_payload(calculated_at=datetime(2026, 8, 22, 9, 0))
    )

    with pytest.raises(ValidationError, match="timezone-aware"):
        model.model_validate(payload, strict=True)  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("leave_type_code", " "),
        ("leave_type_code", "x" * 21),
        ("leave_type_name", " "),
        ("leave_type_name", "x" * 101),
        ("leave_type_name_local", " "),
        ("source_watermark", " "),
        ("calculation_version", " "),
    ],
)
def test_text_constraints(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        LeaveBalanceRecord.model_validate(record_payload(**{field: value}), strict=True)


def test_models_reject_unknown_fields_and_records_are_frozen() -> None:
    with pytest.raises(ValidationError):
        LeaveBalanceRecord.model_validate(record_payload(balance_id="secret"), strict=True)

    record = LeaveBalanceRecord.model_validate(record_payload(), strict=True)
    with pytest.raises(ValidationError):
        record.available_days = Decimal("0")  # type: ignore[misc]


def test_output_is_immutable_and_deterministically_ordered() -> None:
    annual = LeaveBalanceItem.model_validate(item_payload(), strict=True)
    sick = LeaveBalanceItem.model_validate(
        item_payload(leave_type_code="sick", leave_type_name="Sick Leave"), strict=True
    )
    output = GetMyLeaveBalancesOutput.model_validate({"balances": [sick, annual]}, strict=True)

    assert output.balances == (annual, sick)
    assert isinstance(output.balances, tuple)
    with pytest.raises(ValidationError):
        output.balances = ()  # type: ignore[misc]


def test_output_accepts_empty_tuple_and_rejects_wrong_collection() -> None:
    assert GetMyLeaveBalancesOutput(balances=()).balances == ()

    with pytest.raises(ValidationError):
        GetMyLeaveBalancesOutput.model_validate({"balances": "annual"}, strict=True)


def test_safe_item_excludes_internal_fields() -> None:
    prohibited = {
        "employee_id",
        "legal_entity_id",
        "leave_type_id",
        "balance_id",
        "source_watermark",
        "ledger_entry_id",
        "policy_id",
        "request_id",
    }

    assert not prohibited & set(LeaveBalanceItem.model_fields)
