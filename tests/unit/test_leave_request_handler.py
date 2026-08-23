import asyncio
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from pydantic import BaseModel, ConfigDict

from erp_ai.capabilities.leave import (
    LeaveRequestPageRecord,
    LeaveRequestStatus,
    LeaveRequestSummaryRecord,
    ListMyLeaveRequestsHandler,
    ListMyLeaveRequestsInput,
    ListMyLeaveRequestsOutput,
)
from erp_ai.context import TrustedRequestContext

EMPLOYEE_ID = UUID("00000000-0000-4000-8000-000000000002")
ENTITY_ID = UUID("00000000-0000-4000-8000-000000000003")


def record(**overrides: object) -> LeaveRequestSummaryRecord:
    payload: dict[str, object] = {
        "request_id": UUID("00000000-0000-4000-8000-000000000001"),
        "employee_id": EMPLOYEE_ID,
        "legal_entity_id": ENTITY_ID,
        "leave_type_id": UUID("00000000-0000-4000-8000-000000000004"),
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
    return LeaveRequestSummaryRecord.model_validate(payload, strict=True)


def context(*, employee_id: str | None = str(EMPLOYEE_ID)) -> TrustedRequestContext:
    return TrustedRequestContext(
        context_version=1,
        request_id="req_a",
        customer_environment_id="customer_a",
        user_id="user_a",
        employee_id=employee_id,
        roles=("manager",),
        permission_codes=("leave.request.read_self",),
        legal_entity_ids=(str(ENTITY_ID),),
        enabled_modules=("hr_core", "leave"),
        locale="en",
        timezone="Africa/Cairo",
        purpose="employee_self_service",
        issued_at=datetime(2026, 8, 22, 9, 0, tzinfo=ZoneInfo("Africa/Cairo")),
        authorization_snapshot_id="snapshot_a",
    )


class FakeLeaveRequestProvider:
    def __init__(self, page: LeaveRequestPageRecord, *, raises: bool = False) -> None:
        self.page = page
        self.raises = raises
        self.calls: list[dict[str, object]] = []

    async def list_my_leave_requests(self, **kwargs: object) -> LeaveRequestPageRecord:
        self.calls.append(kwargs)
        if self.raises:
            raise RuntimeError("private provider failure")
        return self.page

    async def get_my_leave_balances(self, **kwargs: object) -> object:
        raise AssertionError(f"unexpected balance call: {kwargs}")


def run(
    handler: ListMyLeaveRequestsHandler,
    trusted_context: TrustedRequestContext,
    filters: ListMyLeaveRequestsInput | None = None,
) -> object:
    return asyncio.run(handler.execute(trusted_context, filters or ListMyLeaveRequestsInput()))


def test_handler_forwards_trusted_identifiers_and_validated_filters() -> None:
    page = LeaveRequestPageRecord(items=(record(),), next_cursor="opaque.next")
    provider = FakeLeaveRequestProvider(page)
    filters = ListMyLeaveRequestsInput(
        statuses=(LeaveRequestStatus.PENDING,),
        start_from=date(2026, 1, 1),
        start_to=date(2026, 12, 31),
        limit=10,
        cursor="opaque.current",
    )

    result = run(ListMyLeaveRequestsHandler(provider), context(), filters)

    assert isinstance(result, ListMyLeaveRequestsOutput)
    assert provider.calls == [
        {
            "customer_environment_id": "customer_a",
            "employee_id": str(EMPLOYEE_ID),
            "authorized_legal_entity_ids": (str(ENTITY_ID),),
            "statuses": (LeaveRequestStatus.PENDING,),
            "start_from": date(2026, 1, 1),
            "start_to": date(2026, 12, 31),
            "limit": 10,
            "cursor": "opaque.current",
        }
    ]
    assert result.next_cursor == "opaque.next"
    assert isinstance(result.requests[0].working_days, Decimal)
    assert not {"employee_id", "legal_entity_id", "leave_type_id"} & set(
        result.requests[0].model_dump()
    )


@pytest.mark.parametrize(
    "bad_record",
    [
        record(employee_id=UUID("00000000-0000-4000-8000-000000000099")),
        record(legal_entity_id=UUID("00000000-0000-4000-8000-000000000099")),
    ],
)
def test_handler_rejects_any_ownership_or_scope_violation(
    bad_record: LeaveRequestSummaryRecord,
) -> None:
    page = LeaveRequestPageRecord(items=(record(), bad_record))

    with pytest.raises(RuntimeError):
        run(ListMyLeaveRequestsHandler(FakeLeaveRequestProvider(page)), context())


def test_handler_rejects_duplicate_request_ids() -> None:
    page = LeaveRequestPageRecord(
        items=(record(), record(leave_type_code="sick", leave_type_name="Sick Leave"))
    )

    with pytest.raises(RuntimeError, match="duplicate"):
        run(ListMyLeaveRequestsHandler(FakeLeaveRequestProvider(page)), context())


def test_empty_page_without_cursor_is_successful() -> None:
    result = run(
        ListMyLeaveRequestsHandler(FakeLeaveRequestProvider(LeaveRequestPageRecord(items=()))),
        context(),
    )

    assert isinstance(result, ListMyLeaveRequestsOutput)
    assert result.requests == ()


def test_empty_page_with_cursor_is_rejected() -> None:
    page = LeaveRequestPageRecord(items=(), next_cursor="opaque.unexpected")

    with pytest.raises(RuntimeError, match="empty provider page"):
        run(ListMyLeaveRequestsHandler(FakeLeaveRequestProvider(page)), context())


def test_nonempty_final_page_without_cursor_is_successful() -> None:
    result = run(
        ListMyLeaveRequestsHandler(
            FakeLeaveRequestProvider(LeaveRequestPageRecord(items=(record(),)))
        ),
        context(),
    )

    assert isinstance(result, ListMyLeaveRequestsOutput)
    assert len(result.requests) == 1
    assert result.next_cursor is None


def test_provider_page_cannot_exceed_requested_limit() -> None:
    second = record(request_id=UUID("00000000-0000-4000-8000-000000000005"))
    page = LeaveRequestPageRecord(items=(record(), second))

    with pytest.raises(RuntimeError, match="limit"):
        run(
            ListMyLeaveRequestsHandler(FakeLeaveRequestProvider(page)),
            context(),
            ListMyLeaveRequestsInput(limit=1),
        )


def test_missing_employee_fails_before_provider() -> None:
    provider = FakeLeaveRequestProvider(LeaveRequestPageRecord(items=()))

    with pytest.raises(RuntimeError):
        run(ListMyLeaveRequestsHandler(provider), context(employee_id=None))

    assert provider.calls == []


def test_provider_exception_is_not_converted_to_output() -> None:
    provider = FakeLeaveRequestProvider(LeaveRequestPageRecord(items=()), raises=True)

    with pytest.raises(RuntimeError, match="private provider failure"):
        run(ListMyLeaveRequestsHandler(provider), context())


def test_handler_validates_canonical_order_and_preserves_provider_order() -> None:
    timestamp = datetime(2026, 8, 23, 9, 0, tzinfo=ZoneInfo("Africa/Cairo"))
    lower_id = record(submitted_at=timestamp)
    higher_id = record(
        request_id=UUID("00000000-0000-4000-8000-000000000005"),
        submitted_at=timestamp,
    )
    older = record(
        request_id=UUID("00000000-0000-4000-8000-000000000006"),
        submitted_at=datetime(2026, 8, 22, 9, 0, tzinfo=ZoneInfo("Africa/Cairo")),
    )
    page = LeaveRequestPageRecord(items=(lower_id, higher_id, older))

    result = run(ListMyLeaveRequestsHandler(FakeLeaveRequestProvider(page)), context())

    assert isinstance(result, ListMyLeaveRequestsOutput)
    assert tuple(item.request_id for item in result.requests) == (
        lower_id.request_id,
        higher_id.request_id,
        older.request_id,
    )


def test_out_of_order_submitted_at_is_rejected_without_reordering() -> None:
    newer = record(
        request_id=UUID("00000000-0000-4000-8000-000000000005"),
        submitted_at=datetime(2026, 8, 23, 9, 0, tzinfo=ZoneInfo("Africa/Cairo")),
    )
    page = LeaveRequestPageRecord(items=(record(), newer))

    with pytest.raises(RuntimeError, match="ordering"):
        run(ListMyLeaveRequestsHandler(FakeLeaveRequestProvider(page)), context())


def test_equal_submitted_at_requires_request_id_ascending() -> None:
    timestamp = datetime(2026, 8, 23, 9, 0, tzinfo=ZoneInfo("Africa/Cairo"))
    lower_id = record(submitted_at=timestamp)
    higher_id = record(
        request_id=UUID("00000000-0000-4000-8000-000000000005"),
        submitted_at=timestamp,
    )

    valid = run(
        ListMyLeaveRequestsHandler(
            FakeLeaveRequestProvider(LeaveRequestPageRecord(items=(lower_id, higher_id)))
        ),
        context(),
    )
    assert isinstance(valid, ListMyLeaveRequestsOutput)

    with pytest.raises(RuntimeError, match="ordering"):
        run(
            ListMyLeaveRequestsHandler(
                FakeLeaveRequestProvider(LeaveRequestPageRecord(items=(higher_id, lower_id)))
            ),
            context(),
        )


def test_handler_rejects_wrong_input_model_and_provider() -> None:
    class WrongInput(BaseModel):
        model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    handler = ListMyLeaveRequestsHandler(FakeLeaveRequestProvider(LeaveRequestPageRecord(items=())))
    with pytest.raises(TypeError, match="unexpected"):
        asyncio.run(handler.execute(context(), WrongInput()))

    with pytest.raises(TypeError, match="LeaveReadProvider"):
        ListMyLeaveRequestsHandler(object())  # type: ignore[arg-type]
