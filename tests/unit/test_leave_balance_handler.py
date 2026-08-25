import asyncio
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from pydantic import BaseModel, ConfigDict

from erp_ai.capabilities.leave import (
    GetMyLeaveBalancesHandler,
    GetMyLeaveBalancesInput,
    GetMyLeaveBalancesOutput,
    LeaveBalanceRecord,
)
from erp_ai.context import TrustedRequestContext


def record(**overrides: object) -> LeaveBalanceRecord:
    payload: dict[str, object] = {
        "employee_id": "employee_1",
        "legal_entity_id": "entity_1",
        "leave_type_id": "type_annual",
        "leave_type_code": "annual",
        "leave_type_name": "Annual Leave",
        "leave_type_name_local": "Synthetic Local Name",
        "fiscal_year": 2026,
        "opening_days": Decimal("10.00"),
        "accrued_days": Decimal("5.00"),
        "used_days": Decimal("3.00"),
        "pending_days": Decimal("1.00"),
        "available_days": Decimal("-7.25"),
        "calculated_at": datetime(2026, 8, 22, 9, 0, tzinfo=ZoneInfo("Africa/Cairo")),
        "source_watermark": "watermark_1",
        "calculation_version": "1.0.0",
    }
    payload.update(overrides)
    return LeaveBalanceRecord.model_validate(payload, strict=True)


def context(*, employee_id: str | None = "employee_1") -> TrustedRequestContext:
    return TrustedRequestContext(
        context_version=1,
        request_id="req_a",
        customer_environment_id="customer_a",
        user_id="user_1",
        employee_id=employee_id,
        roles=("manager",),
        permission_codes=("leave.balance.read_self",),
        legal_entity_ids=("entity_1", "entity_2"),
        enabled_modules=("hr_core", "leave"),
        locale="en",
        timezone="Africa/Cairo",
        purpose="employee_self_service",
        issued_at=datetime(2026, 8, 22, 9, 0, tzinfo=ZoneInfo("Africa/Cairo")),
        authorization_snapshot_id="snapshot_a",
    )


class FakeLeaveProvider:
    def __init__(self, records: tuple[LeaveBalanceRecord, ...], *, raises: bool = False) -> None:
        self.records = records
        self.raises = raises
        self.calls: list[tuple[str, str, tuple[str, ...]]] = []

    async def get_my_leave_balances(
        self,
        *,
        customer_environment_id: str,
        employee_id: str,
        authorized_legal_entity_ids: tuple[str, ...],
    ) -> tuple[LeaveBalanceRecord, ...]:
        self.calls.append((customer_environment_id, employee_id, authorized_legal_entity_ids))
        if self.raises:
            raise RuntimeError("private provider failure")
        return self.records

    async def list_my_leave_requests(self, **kwargs: object) -> object:
        raise AssertionError(f"unexpected request-list call: {kwargs}")

    async def get_my_leave_request(self, **kwargs: object) -> object:
        raise AssertionError(f"unexpected request-detail call: {kwargs}")


def run(handler: GetMyLeaveBalancesHandler, trusted_context: TrustedRequestContext) -> object:
    return asyncio.run(handler.execute(trusted_context, GetMyLeaveBalancesInput()))


def test_handler_passes_only_trusted_scope_and_explicitly_maps_output() -> None:
    provider = FakeLeaveProvider((record(),))

    result = run(GetMyLeaveBalancesHandler(provider), context())

    assert isinstance(result, GetMyLeaveBalancesOutput)
    assert provider.calls == [("customer_a", "employee_1", ("entity_1", "entity_2"))]
    assert result.balances[0].available_days == Decimal("-7.25")
    assert not {
        "employee_id",
        "legal_entity_id",
        "leave_type_id",
        "source_watermark",
    } & set(result.balances[0].model_dump())


@pytest.mark.parametrize(
    "bad_record",
    [record(employee_id="employee_2"), record(legal_entity_id="entity_3")],
)
def test_handler_rejects_any_ownership_or_scope_mismatch(
    bad_record: LeaveBalanceRecord,
) -> None:
    handler = GetMyLeaveBalancesHandler(FakeLeaveProvider((record(), bad_record)))

    with pytest.raises(RuntimeError):
        run(handler, context())


def test_handler_rejects_duplicate_entity_type_year_record() -> None:
    duplicate = record(leave_type_code="annual_duplicate")

    with pytest.raises(RuntimeError, match="duplicate"):
        run(GetMyLeaveBalancesHandler(FakeLeaveProvider((record(), duplicate))), context())


def test_handler_returns_empty_output_without_invention() -> None:
    result = run(GetMyLeaveBalancesHandler(FakeLeaveProvider(())), context())

    assert isinstance(result, GetMyLeaveBalancesOutput)
    assert result.balances == ()


def test_handler_does_not_recalculate_available_days() -> None:
    authoritative = record(
        opening_days=Decimal("1.00"),
        accrued_days=Decimal("2.00"),
        used_days=Decimal("3.00"),
        pending_days=Decimal("4.00"),
        available_days=Decimal("99.99"),
    )

    result = run(GetMyLeaveBalancesHandler(FakeLeaveProvider((authoritative,))), context())

    assert isinstance(result, GetMyLeaveBalancesOutput)
    assert result.balances[0].available_days == Decimal("99.99")


def test_missing_employee_fails_before_provider_execution() -> None:
    provider = FakeLeaveProvider((record(),))

    with pytest.raises(RuntimeError):
        run(GetMyLeaveBalancesHandler(provider), context(employee_id=None))

    assert provider.calls == []


def test_provider_exception_is_not_converted_to_output() -> None:
    handler = GetMyLeaveBalancesHandler(FakeLeaveProvider((), raises=True))

    with pytest.raises(RuntimeError, match="private provider failure"):
        run(handler, context())


def test_handler_rejects_wrong_input_model_and_provider() -> None:
    class WrongInput(BaseModel):
        model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    handler = GetMyLeaveBalancesHandler(FakeLeaveProvider(()))
    with pytest.raises(TypeError, match="unexpected"):
        asyncio.run(handler.execute(context(), WrongInput()))

    with pytest.raises(TypeError, match="LeaveReadProvider"):
        GetMyLeaveBalancesHandler(object())  # type: ignore[arg-type]
