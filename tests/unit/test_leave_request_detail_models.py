from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from erp_ai.capabilities.leave import (
    GetMyLeaveRequestInput,
    GetMyLeaveRequestOutput,
    LeaveRequestDetailRecord,
    LeaveRequestHistoryRecord,
    LeaveRequestStatus,
    LeaveRequestStatusTransition,
)

REQUEST_ID = UUID("10000000-0000-4000-8000-000000000001")
HISTORY_ID = UUID("20000000-0000-4000-8000-000000000001")


def history_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "history_id": HISTORY_ID,
        "entity_type": "leave_request",
        "entity_id": REQUEST_ID,
        "from_status": None,
        "to_status": "pending",
        "changed_at": datetime(2026, 8, 22, 9, 0, tzinfo=ZoneInfo("Africa/Cairo")),
        "reason_code": "submitted",
    }
    payload.update(overrides)
    return payload


def detail_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "request_id": REQUEST_ID,
        "employee_id": UUID("10000000-0000-4000-8000-000000000002"),
        "legal_entity_id": UUID("10000000-0000-4000-8000-000000000003"),
        "leave_type_id": UUID("10000000-0000-4000-8000-000000000004"),
        "leave_type_code": "annual",
        "leave_type_name": "Annual Leave",
        "leave_type_name_local": "Synthetic Local Name",
        "start_date": date(2026, 8, 24),
        "end_date": date(2026, 8, 25),
        "working_days": Decimal("2.00"),
        "is_half_day": False,
        "half_day_period": None,
        "status": "pending",
        "submitted_at": datetime(2026, 8, 22, 9, 0, tzinfo=ZoneInfo("Africa/Cairo")),
        "updated_at": None,
        "working_days_calculation_version": "1.0.0",
        "customer_environment_id": "customer_a",
        "status_history": [
            LeaveRequestHistoryRecord.model_validate(history_payload(), strict=True)
        ],
    }
    payload.update(overrides)
    return payload


def test_detail_input_accepts_only_uuid_selector_and_is_frozen() -> None:
    selector = GetMyLeaveRequestInput.model_validate({"request_id": str(REQUEST_ID)}, strict=True)

    assert selector.request_id == REQUEST_ID
    with pytest.raises(ValidationError):
        selector.request_id = UUID(int=9)  # type: ignore[misc]
    with pytest.raises(ValidationError):
        GetMyLeaveRequestInput.model_validate(
            {"request_id": str(REQUEST_ID), "employee_id": "forged"}, strict=True
        )


def test_detail_input_rejects_invalid_or_non_uuid_values() -> None:
    with pytest.raises(ValidationError, match="valid UUID"):
        GetMyLeaveRequestInput.model_validate({"request_id": "not-a-uuid"}, strict=True)
    with pytest.raises(ValidationError):
        GetMyLeaveRequestInput.model_validate({"request_id": 123}, strict=True)


def test_history_record_is_strict_frozen_and_validated() -> None:
    history = LeaveRequestHistoryRecord.model_validate(history_payload(), strict=True)

    assert history.to_status is LeaveRequestStatus.PENDING
    assert history.reason_code == "submitted"
    with pytest.raises(ValidationError):
        history.entity_type = "other"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        LeaveRequestHistoryRecord.model_validate(
            history_payload(reason_text="must not enter contract"), strict=True
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"changed_at": datetime(2026, 8, 22, 9, 0)},
        {"to_status": "unknown"},
        {"reason_code": "free text"},
        {"reason_code": "x" * 51},
    ],
)
def test_invalid_history_values_are_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        LeaveRequestHistoryRecord.model_validate(history_payload(**overrides), strict=True)


def test_detail_record_accepts_empty_or_tuple_timeline_and_is_frozen() -> None:
    empty = LeaveRequestDetailRecord.model_validate(detail_payload(status_history=[]), strict=True)
    populated = LeaveRequestDetailRecord.model_validate(detail_payload(), strict=True)

    assert empty.status_history == ()
    assert isinstance(populated.status_history, tuple)
    with pytest.raises(ValidationError):
        populated.status_history = ()  # type: ignore[misc]


def test_detail_record_rejects_wrong_timeline_collection() -> None:
    with pytest.raises(ValidationError):
        LeaveRequestDetailRecord.model_validate(
            detail_payload(status_history="invalid"), strict=True
        )


def test_public_detail_and_timeline_are_explicit_allowlists() -> None:
    expected_detail = {
        "request_id",
        "leave_type_code",
        "leave_type_name",
        "leave_type_name_local",
        "start_date",
        "end_date",
        "working_days",
        "is_half_day",
        "half_day_period",
        "status",
        "submitted_at",
        "updated_at",
        "status_timeline",
    }
    expected_transition = {"from_status", "to_status", "changed_at", "reason_code"}
    prohibited = {
        "customer_environment_id",
        "employee_id",
        "legal_entity_id",
        "leave_type_id",
        "history_id",
        "changed_by_user_id",
        "reviewer_id",
        "approval_request_id",
        "correlation_id",
        "medical_certificate_id",
        "medical_certificate_path",
        "review_notes",
        "reason_text",
        "request_text",
        "working_days_calculation_version",
    }

    assert set(GetMyLeaveRequestOutput.model_fields) == expected_detail
    assert set(LeaveRequestStatusTransition.model_fields) == expected_transition
    assert not prohibited & set(GetMyLeaveRequestOutput.model_fields)
    assert not prohibited & set(LeaveRequestStatusTransition.model_fields)
