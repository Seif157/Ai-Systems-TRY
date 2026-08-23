from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from erp_ai.capabilities.leave import (
    HalfDayPeriod,
    LeaveRequestPageRecord,
    LeaveRequestStatus,
    LeaveRequestSummary,
    LeaveRequestSummaryRecord,
    ListMyLeaveRequestsInput,
    ListMyLeaveRequestsOutput,
)

REQUEST_ID = UUID("00000000-0000-4000-8000-000000000001")
EMPLOYEE_ID = UUID("00000000-0000-4000-8000-000000000002")
ENTITY_ID = UUID("00000000-0000-4000-8000-000000000003")
LEAVE_TYPE_ID = UUID("00000000-0000-4000-8000-000000000004")


def record_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "request_id": REQUEST_ID,
        "employee_id": EMPLOYEE_ID,
        "legal_entity_id": ENTITY_ID,
        "leave_type_id": LEAVE_TYPE_ID,
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
        "working_days_calculation_version": "calendar_v1",
    }
    payload.update(overrides)
    return payload


def safe_summary(record: LeaveRequestSummaryRecord) -> LeaveRequestSummary:
    return LeaveRequestSummary(
        request_id=record.request_id,
        leave_type_code=record.leave_type_code,
        leave_type_name=record.leave_type_name,
        leave_type_name_local=record.leave_type_name_local,
        start_date=record.start_date,
        end_date=record.end_date,
        working_days=record.working_days,
        is_half_day=record.is_half_day,
        half_day_period=record.half_day_period,
        status=record.status,
        submitted_at=record.submitted_at,
        updated_at=record.updated_at,
        working_days_calculation_version=record.working_days_calculation_version,
    )


def test_input_defaults_are_immutable_and_strict() -> None:
    filters = ListMyLeaveRequestsInput()

    assert filters.statuses == ()
    assert filters.limit == 20
    assert filters.cursor is None
    with pytest.raises(ValidationError):
        filters.limit = 10  # type: ignore[misc]
    with pytest.raises(ValidationError):
        ListMyLeaveRequestsInput.model_validate({"employee_id": str(EMPLOYEE_ID)}, strict=True)


def test_status_filters_are_validated_ordered_and_immutable() -> None:
    filters = ListMyLeaveRequestsInput.model_validate(
        {"statuses": ["returned", "approved"]}, strict=True
    )

    assert filters.statuses == (
        LeaveRequestStatus.APPROVED,
        LeaveRequestStatus.RETURNED,
    )
    assert isinstance(filters.statuses, tuple)


@pytest.mark.parametrize("status", list(LeaveRequestStatus))
def test_every_request_status_is_supported(status: LeaveRequestStatus) -> None:
    record = LeaveRequestSummaryRecord.model_validate(
        record_payload(status=status.value), strict=True
    )

    assert record.status is status


@pytest.mark.parametrize("statuses", [["pending", "pending"], ["unknown"], "pending"])
def test_duplicate_invalid_or_non_collection_statuses_are_rejected(
    statuses: object,
) -> None:
    with pytest.raises(ValidationError):
        ListMyLeaveRequestsInput.model_validate({"statuses": statuses}, strict=True)


@pytest.mark.parametrize(
    ("start_from", "start_to"),
    [
        (date(2026, 1, 1), date(2026, 1, 1)),
        (date(2025, 1, 1), date(2026, 1, 2)),
        (None, date(2026, 1, 1)),
    ],
)
def test_valid_date_ranges(start_from: date | None, start_to: date | None) -> None:
    filters = ListMyLeaveRequestsInput(start_from=start_from, start_to=start_to)

    assert filters.start_from == start_from
    assert filters.start_to == start_to


def test_iso_date_filters_are_parsed_for_json_tool_arguments() -> None:
    filters = ListMyLeaveRequestsInput.model_validate(
        {"start_from": "2026-01-01", "start_to": "2026-12-31"}, strict=True
    )

    assert filters.start_from == date(2026, 1, 1)
    assert filters.start_to == date(2026, 12, 31)


def test_malformed_iso_date_filter_is_rejected() -> None:
    with pytest.raises(ValidationError, match="ISO"):
        ListMyLeaveRequestsInput.model_validate({"start_from": "01/01/2026"}, strict=True)


@pytest.mark.parametrize(
    ("start_from", "start_to"),
    [
        (date(2026, 2, 1), date(2026, 1, 1)),
        (date(2025, 1, 1), date(2026, 1, 3)),
    ],
)
def test_invalid_date_ranges(start_from: date, start_to: date) -> None:
    with pytest.raises(ValidationError):
        ListMyLeaveRequestsInput(start_from=start_from, start_to=start_to)


@pytest.mark.parametrize("limit", [1, 20, 50])
def test_limit_boundaries(limit: int) -> None:
    assert ListMyLeaveRequestsInput(limit=limit).limit == limit


@pytest.mark.parametrize("limit", [0, 51, "20"])
def test_invalid_limits(limit: object) -> None:
    with pytest.raises(ValidationError):
        ListMyLeaveRequestsInput.model_validate({"limit": limit}, strict=True)


def test_cursor_is_opaque_and_preserved_exactly() -> None:
    cursor = " signed.cursor/value== "

    assert ListMyLeaveRequestsInput(cursor=cursor).cursor == cursor


@pytest.mark.parametrize("cursor", ["", "   ", "x" * 513])
def test_empty_or_oversized_cursor_is_rejected(cursor: str) -> None:
    with pytest.raises(ValidationError):
        ListMyLeaveRequestsInput(cursor=cursor)


def test_record_requires_strict_uuids_and_forbids_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        LeaveRequestSummaryRecord.model_validate(
            record_payload(request_id=str(REQUEST_ID)), strict=True
        )
    with pytest.raises(ValidationError):
        LeaveRequestSummaryRecord.model_validate(
            record_payload(approval_request_id=REQUEST_ID), strict=True
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("leave_type_code", " "),
        ("leave_type_code", "x" * 21),
        ("leave_type_name", "x" * 101),
        ("leave_type_name_local", " "),
        ("working_days_calculation_version", " "),
    ],
)
def test_record_text_constraints(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        LeaveRequestSummaryRecord.model_validate(record_payload(**{field: value}), strict=True)


@pytest.mark.parametrize(
    "overrides",
    [
        {"end_date": date(2026, 8, 23)},
        {"working_days": Decimal("0")},
        {"working_days": Decimal("1.001")},
        {"working_days": Decimal("1000.00")},
    ],
)
def test_date_and_working_day_constraints(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        LeaveRequestSummaryRecord.model_validate(record_payload(**overrides), strict=True)


@pytest.mark.parametrize("period", list(HalfDayPeriod))
def test_valid_half_day_contract(period: HalfDayPeriod) -> None:
    record = LeaveRequestSummaryRecord.model_validate(
        record_payload(
            end_date=date(2026, 8, 24),
            working_days=Decimal("0.50"),
            is_half_day=True,
            half_day_period=period.value,
        ),
        strict=True,
    )

    assert record.half_day_period is period


@pytest.mark.parametrize(
    "overrides",
    [
        {"is_half_day": True, "working_days": Decimal("0.50"), "half_day_period": "first_half"},
        {
            "is_half_day": True,
            "end_date": date(2026, 8, 24),
            "working_days": Decimal("1.00"),
            "half_day_period": "first_half",
        },
        {
            "is_half_day": True,
            "end_date": date(2026, 8, 24),
            "working_days": Decimal("0.50"),
            "half_day_period": None,
        },
        {"is_half_day": False, "half_day_period": "second_half"},
    ],
)
def test_invalid_half_day_combinations(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        LeaveRequestSummaryRecord.model_validate(record_payload(**overrides), strict=True)


@pytest.mark.parametrize(
    "overrides",
    [
        {"submitted_at": datetime(2026, 8, 22, 9, 0)},
        {"updated_at": datetime(2026, 8, 22, 9, 0)},
    ],
)
def test_request_timestamps_must_be_timezone_aware(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        LeaveRequestSummaryRecord.model_validate(record_payload(**overrides), strict=True)


def test_page_and_safe_output_are_immutable_and_preserve_order() -> None:
    older = LeaveRequestSummaryRecord.model_validate(record_payload(), strict=True)
    newer = LeaveRequestSummaryRecord.model_validate(
        record_payload(
            request_id=UUID("00000000-0000-4000-8000-000000000005"),
            submitted_at=datetime(2026, 8, 23, 9, 0, tzinfo=ZoneInfo("Africa/Cairo")),
        ),
        strict=True,
    )
    page = LeaveRequestPageRecord.model_validate(
        {"items": [older, newer], "next_cursor": "cursor.1"}, strict=True
    )
    output = ListMyLeaveRequestsOutput.model_validate(
        {"requests": [safe_summary(older), safe_summary(newer)], "next_cursor": page.next_cursor},
        strict=True,
    )

    assert isinstance(page.items, tuple)
    assert tuple(item.request_id for item in output.requests) == (
        older.request_id,
        newer.request_id,
    )
    with pytest.raises(ValidationError):
        output.requests = ()  # type: ignore[misc]


def test_page_and_output_reject_wrong_collection_types() -> None:
    with pytest.raises(ValidationError):
        LeaveRequestPageRecord.model_validate({"items": "invalid"}, strict=True)
    with pytest.raises(ValidationError):
        ListMyLeaveRequestsOutput.model_validate({"requests": "invalid"}, strict=True)


def test_safe_summary_excludes_internal_and_sensitive_fields() -> None:
    prohibited = {
        "employee_id",
        "legal_entity_id",
        "leave_type_id",
        "approval_request_id",
        "reviewer_id",
        "review_notes",
        "medical_certificate",
        "secure_file_id",
        "reason",
        "correlation_id",
        "created_by",
        "status_history",
    }

    assert not prohibited & set(LeaveRequestSummary.model_fields)
