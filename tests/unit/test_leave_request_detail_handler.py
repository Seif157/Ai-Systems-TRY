import asyncio
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from pydantic import BaseModel, ConfigDict

from erp_ai.capabilities.leave import (
    GetMyLeaveRequestHandler,
    GetMyLeaveRequestInput,
    GetMyLeaveRequestOutput,
    LeaveRequestDetailRecord,
    LeaveRequestHistoryRecord,
)
from erp_ai.context import TrustedRequestContext

REQUEST_ID = UUID("10000000-0000-4000-8000-000000000001")
EMPLOYEE_ID = UUID("10000000-0000-4000-8000-000000000002")
ENTITY_ID = UUID("10000000-0000-4000-8000-000000000003")


def history(sequence: int, **overrides: object) -> LeaveRequestHistoryRecord:
    payload: dict[str, object] = {
        "history_id": UUID(f"20000000-0000-4000-8000-{sequence:012d}"),
        "entity_type": "leave_request",
        "entity_id": REQUEST_ID,
        "from_status": None if sequence == 1 else "pending",
        "to_status": "pending" if sequence == 1 else "approved",
        "changed_at": datetime(2026, 8, 21 + sequence, 9, 0, tzinfo=ZoneInfo("Africa/Cairo")),
        "reason_code": "submitted" if sequence == 1 else "approved",
    }
    payload.update(overrides)
    return LeaveRequestHistoryRecord.model_validate(payload, strict=True)


def detail(**overrides: object) -> LeaveRequestDetailRecord:
    payload: dict[str, object] = {
        "request_id": REQUEST_ID,
        "employee_id": EMPLOYEE_ID,
        "legal_entity_id": ENTITY_ID,
        "leave_type_id": UUID("10000000-0000-4000-8000-000000000004"),
        "leave_type_code": "annual",
        "leave_type_name": "Annual Leave",
        "leave_type_name_local": "Synthetic Local Name",
        "start_date": date(2026, 8, 24),
        "end_date": date(2026, 8, 25),
        "working_days": Decimal("2.00"),
        "is_half_day": False,
        "half_day_period": None,
        "status": "approved",
        "submitted_at": datetime(2026, 8, 22, 9, 0, tzinfo=ZoneInfo("Africa/Cairo")),
        "updated_at": None,
        "working_days_calculation_version": "calendar_v1",
        "customer_environment_id": "customer_a",
        "status_history": (history(1), history(2)),
    }
    payload.update(overrides)
    return LeaveRequestDetailRecord.model_validate(payload, strict=True)


def context(*, employee_id: str | None = str(EMPLOYEE_ID)) -> TrustedRequestContext:
    return TrustedRequestContext(
        context_version=1,
        request_id="req_a",
        customer_environment_id="customer_a",
        user_id="user_a",
        employee_id=employee_id,
        roles=("hr",),
        permission_codes=("leave.request.read_self",),
        legal_entity_ids=(str(ENTITY_ID),),
        enabled_modules=("hr_core", "leave"),
        locale="en",
        timezone="Africa/Cairo",
        purpose="employee_self_service",
        issued_at=datetime(2026, 8, 22, 9, 0, tzinfo=ZoneInfo("Africa/Cairo")),
        authorization_snapshot_id="snapshot_a",
    )


class FakeDetailProvider:
    def __init__(self, record: LeaveRequestDetailRecord | None, *, raises: bool = False) -> None:
        self.record = record
        self.raises = raises
        self.calls: list[dict[str, object]] = []

    async def get_my_leave_request(self, **kwargs: object) -> LeaveRequestDetailRecord | None:
        self.calls.append(kwargs)
        if self.raises:
            raise RuntimeError("private detail provider failure")
        return self.record

    async def get_my_leave_balances(self, **kwargs: object) -> object:
        raise AssertionError(f"unexpected balance call: {kwargs}")

    async def list_my_leave_requests(self, **kwargs: object) -> object:
        raise AssertionError(f"unexpected list call: {kwargs}")


def run(
    handler: GetMyLeaveRequestHandler,
    trusted_context: TrustedRequestContext | None = None,
    request_id: UUID = REQUEST_ID,
) -> object:
    return asyncio.run(
        handler.execute(trusted_context or context(), GetMyLeaveRequestInput(request_id=request_id))
    )


def test_handler_uses_trusted_scope_and_maps_safe_detail() -> None:
    provider = FakeDetailProvider(detail())

    result = run(GetMyLeaveRequestHandler(provider))

    assert isinstance(result, GetMyLeaveRequestOutput)
    assert provider.calls == [
        {
            "customer_environment_id": "customer_a",
            "employee_id": str(EMPLOYEE_ID),
            "authorized_legal_entity_ids": (str(ENTITY_ID),),
            "request_id": REQUEST_ID,
        }
    ]
    assert tuple(item.to_status.value for item in result.status_timeline) == (
        "pending",
        "approved",
    )
    assert result.status_timeline[0].reason_code == "submitted"
    assert isinstance(result.working_days, Decimal)


@pytest.mark.parametrize(
    "provider_record",
    [
        None,
        detail(request_id=UUID("10000000-0000-4000-8000-000000000099")),
        detail(customer_environment_id="customer_b"),
        detail(employee_id=UUID("10000000-0000-4000-8000-000000000099")),
        detail(legal_entity_id=UUID("10000000-0000-4000-8000-000000000099")),
    ],
)
def test_unavailable_or_mismatched_record_is_rejected(
    provider_record: LeaveRequestDetailRecord | None,
) -> None:
    with pytest.raises(RuntimeError):
        run(GetMyLeaveRequestHandler(FakeDetailProvider(provider_record)))


def test_missing_employee_fails_before_provider() -> None:
    provider = FakeDetailProvider(detail())

    with pytest.raises(RuntimeError):
        run(GetMyLeaveRequestHandler(provider), context(employee_id=None))

    assert provider.calls == []


def test_empty_timeline_is_allowed_and_preserved() -> None:
    result = run(
        GetMyLeaveRequestHandler(FakeDetailProvider(detail(status="draft", status_history=())))
    )

    assert isinstance(result, GetMyLeaveRequestOutput)
    assert result.status_timeline == ()


def test_equal_timestamp_history_requires_id_ascending_and_preserves_order() -> None:
    timestamp = datetime(2026, 8, 22, 9, 0, tzinfo=ZoneInfo("Africa/Cairo"))
    first = history(1, changed_at=timestamp)
    second = history(2, changed_at=timestamp)
    result = run(
        GetMyLeaveRequestHandler(FakeDetailProvider(detail(status_history=(first, second))))
    )

    assert isinstance(result, GetMyLeaveRequestOutput)
    assert tuple(item.reason_code for item in result.status_timeline) == (
        "submitted",
        "approved",
    )

    with pytest.raises(RuntimeError, match="ordering"):
        run(GetMyLeaveRequestHandler(FakeDetailProvider(detail(status_history=(second, first)))))


@pytest.mark.parametrize(
    "timeline",
    [
        (history(2), history(1)),
        (history(1), history(1)),
        (history(1, entity_type="other"), history(2)),
        (
            history(1, entity_id=UUID("10000000-0000-4000-8000-000000000099")),
            history(2),
        ),
        (history(1), history(2, from_status="draft")),
    ],
)
def test_invalid_timeline_is_rejected(
    timeline: tuple[LeaveRequestHistoryRecord, ...],
) -> None:
    with pytest.raises(RuntimeError):
        run(GetMyLeaveRequestHandler(FakeDetailProvider(detail(status_history=timeline))))


def test_final_timeline_status_must_match_current_status() -> None:
    with pytest.raises(RuntimeError, match="final status"):
        run(GetMyLeaveRequestHandler(FakeDetailProvider(detail(status="returned"))))


def test_provider_exception_and_wrong_handler_inputs_are_rejected() -> None:
    with pytest.raises(RuntimeError, match="private detail"):
        run(GetMyLeaveRequestHandler(FakeDetailProvider(detail(), raises=True)))

    class WrongInput(BaseModel):
        model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    handler = GetMyLeaveRequestHandler(FakeDetailProvider(detail()))
    with pytest.raises(TypeError, match="unexpected"):
        asyncio.run(handler.execute(context(), WrongInput()))

    with pytest.raises(TypeError, match="LeaveReadProvider"):
        GetMyLeaveRequestHandler(object())  # type: ignore[arg-type]
