import asyncio
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from erp_ai.capabilities import CapabilityRegistry, DataClassification
from erp_ai.capabilities.leave import (
    LEAVE_MANIFEST,
    GetMyLeaveBalancesHandler,
    GetMyLeaveBalancesOutput,
    LeaveBalanceRecord,
)
from erp_ai.context import TrustedRequestContext
from erp_ai.tools import (
    PublicToolFailure,
    PublicToolSuccess,
    ReadToolGateway,
    ToolAuditEvent,
    ToolErrorCode,
    ToolInvocation,
)


def balance(customer: str, **overrides: object) -> LeaveBalanceRecord:
    payload: dict[str, object] = {
        "employee_id": "employee_1",
        "legal_entity_id": "entity_1",
        "leave_type_id": "type_annual",
        "leave_type_code": "annual",
        "leave_type_name": f"Annual {customer}",
        "leave_type_name_local": "Synthetic Local Name",
        "fiscal_year": 2026,
        "opening_days": Decimal("10.00"),
        "accrued_days": Decimal("5.50"),
        "used_days": Decimal("3.00"),
        "pending_days": Decimal("1.00"),
        "available_days": Decimal("11.50"),
        "calculated_at": datetime(2026, 8, 22, 9, 0, tzinfo=ZoneInfo("Africa/Cairo")),
        "source_watermark": f"watermark_{customer}",
        "calculation_version": "1.0.0",
    }
    payload.update(overrides)
    return LeaveBalanceRecord.model_validate(payload, strict=True)


class FakeLeaveProvider:
    def __init__(self, records: dict[tuple[str, str], tuple[LeaveBalanceRecord, ...]]) -> None:
        self.records = records
        self.calls: list[tuple[str, str, tuple[str, ...]]] = []
        self.raises = False

    async def get_my_leave_balances(
        self,
        *,
        customer_environment_id: str,
        employee_id: str,
        authorized_legal_entity_ids: tuple[str, ...],
    ) -> tuple[LeaveBalanceRecord, ...]:
        self.calls.append((customer_environment_id, employee_id, authorized_legal_entity_ids))
        if self.raises:
            raise RuntimeError("private leave provider failure")
        return self.records.get((customer_environment_id, employee_id), ())

    async def list_my_leave_requests(self, **kwargs: object) -> object:
        raise AssertionError(f"unexpected request-list call: {kwargs}")

    async def get_my_leave_request(self, **kwargs: object) -> object:
        raise AssertionError(f"unexpected request-detail call: {kwargs}")


class RecordingAuditSink:
    def __init__(self) -> None:
        self.events: list[ToolAuditEvent] = []

    async def record(self, event: ToolAuditEvent) -> None:
        self.events.append(event)


def context(
    customer: str = "customer_a",
    *,
    employee_id: str | None = "employee_1",
    modules: tuple[str, ...] = ("hr_core", "leave"),
    permissions: tuple[str, ...] = ("leave.balance.read_self",),
    purpose: str = "employee_self_service",
    roles: tuple[str, ...] = ("manager",),
    entities: tuple[str, ...] = ("entity_1",),
) -> TrustedRequestContext:
    return TrustedRequestContext(
        context_version=1,
        request_id=f"req_{customer}",
        customer_environment_id=customer,
        user_id=f"user_{customer}",
        employee_id=employee_id,
        roles=roles,
        permission_codes=permissions,
        legal_entity_ids=entities,
        enabled_modules=modules,
        locale="en",
        timezone="Africa/Cairo",
        purpose=purpose,
        issued_at=datetime(2026, 8, 22, 9, 0, tzinfo=ZoneInfo("Africa/Cairo")),
        authorization_snapshot_id=f"snapshot_{customer}",
    )


def invocation(arguments: dict[str, object] | None = None) -> ToolInvocation:
    return ToolInvocation.model_validate(
        {
            "tool_name": "get_my_leave_balances",
            "version": "1.0.0",
            "arguments": {} if arguments is None else arguments,
        },
        strict=True,
    )


def gateway(provider: FakeLeaveProvider, sink: RecordingAuditSink) -> ReadToolGateway:
    return ReadToolGateway(
        CapabilityRegistry([LEAVE_MANIFEST]),
        [GetMyLeaveBalancesHandler(provider)],
        sink,
    )


def execute(
    tool_gateway: ReadToolGateway,
    trusted_context: TrustedRequestContext,
    tool_invocation: ToolInvocation | None = None,
) -> PublicToolSuccess | PublicToolFailure:
    return asyncio.run(tool_gateway.execute(trusted_context, tool_invocation or invocation()))


def test_complete_authorized_flow_returns_safe_decimal_output_and_audit() -> None:
    provider = FakeLeaveProvider({("customer_a", "employee_1"): (balance("a"),)})
    sink = RecordingAuditSink()

    result = execute(gateway(provider, sink), context())

    assert isinstance(result, PublicToolSuccess)
    assert isinstance(result.result, GetMyLeaveBalancesOutput)
    assert result.result.balances[0].leave_type_name == "Annual a"
    assert isinstance(result.result.balances[0].available_days, Decimal)
    assert provider.calls == [("customer_a", "employee_1", ("entity_1",))]
    assert len(sink.events) == 1
    assert sink.events[0].data_classification is DataClassification.RESTRICTED
    assert sink.events[0].audit_action == "leave.balance.read_self"
    audit = sink.events[0].model_dump()
    assert not {"balances", "available_days", "source_watermark", "employee_id"} & set(audit)
    assert "11.50" not in repr(audit)


@pytest.mark.parametrize(
    "arguments",
    [
        {"fiscal_year": 2025},
        {"employee_id": "forged"},
        {"customer_environment_id": "forged"},
        {"legal_entity_ids": ["forged"]},
    ],
)
def test_model_selected_scope_is_rejected(arguments: dict[str, object]) -> None:
    provider = FakeLeaveProvider({("customer_a", "employee_1"): (balance("a"),)})

    result = execute(gateway(provider, RecordingAuditSink()), context(), invocation(arguments))

    assert isinstance(result, PublicToolFailure)
    assert result.safe_error_code is ToolErrorCode.INVALID_TOOL_ARGUMENTS
    assert provider.calls == []


@pytest.mark.parametrize(
    "trusted_context",
    [
        context(modules=("hr_core",)),
        context(modules=("leave",)),
        context(employee_id=None),
        context(permissions=()),
        context(purpose="manager_service"),
    ],
)
def test_authorization_denial_occurs_before_provider(
    trusted_context: TrustedRequestContext,
) -> None:
    provider = FakeLeaveProvider({("customer_a", "employee_1"): (balance("a"),)})
    tool_gateway = gateway(provider, RecordingAuditSink())

    assert tool_gateway.available_tools(trusted_context) == ()
    result = execute(tool_gateway, trusted_context)

    assert isinstance(result, PublicToolFailure)
    assert result.safe_error_code is ToolErrorCode.TOOL_UNAVAILABLE
    assert provider.calls == []


def test_empty_provider_result_is_a_successful_empty_collection() -> None:
    result = execute(gateway(FakeLeaveProvider({}), RecordingAuditSink()), context())

    assert isinstance(result, PublicToolSuccess)
    assert result.result.balances == ()


@pytest.mark.parametrize(
    "record",
    [balance("a", employee_id="employee_2"), balance("a", legal_entity_id="entity_2")],
)
def test_any_provider_scope_violation_fails_complete_response(
    record: LeaveBalanceRecord,
) -> None:
    provider = FakeLeaveProvider({("customer_a", "employee_1"): (balance("a"), record)})

    result = execute(gateway(provider, RecordingAuditSink()), context())

    assert isinstance(result, PublicToolFailure)
    assert result.safe_error_code is ToolErrorCode.TOOL_EXECUTION_FAILED
    assert "mismatch" not in result.safe_message.lower()


def test_duplicate_provider_record_returns_safe_failure() -> None:
    provider = FakeLeaveProvider({("customer_a", "employee_1"): (balance("a"), balance("a"))})

    result = execute(gateway(provider, RecordingAuditSink()), context())

    assert isinstance(result, PublicToolFailure)
    assert result.safe_error_code is ToolErrorCode.TOOL_EXECUTION_FAILED
    assert "duplicate" not in result.safe_message.lower()


def test_provider_exception_returns_safe_failure() -> None:
    provider = FakeLeaveProvider({})
    provider.raises = True

    result = execute(gateway(provider, RecordingAuditSink()), context())

    assert isinstance(result, PublicToolFailure)
    assert result.safe_error_code is ToolErrorCode.TOOL_EXECUTION_FAILED
    assert "private" not in result.safe_message.lower()


def test_invalid_provider_data_returns_safe_failure() -> None:
    provider = FakeLeaveProvider({})
    provider.records[("customer_a", "employee_1")] = (object(),)  # type: ignore[assignment]

    result = execute(gateway(provider, RecordingAuditSink()), context())

    assert isinstance(result, PublicToolFailure)
    assert result.safe_error_code is ToolErrorCode.TOOL_EXECUTION_FAILED
    assert "object" not in result.safe_message.lower()


def test_output_order_is_deterministic() -> None:
    annual = balance("a")
    sick = balance("a", leave_type_id="type_sick", leave_type_code="sick", leave_type_name="Sick")
    provider = FakeLeaveProvider({("customer_a", "employee_1"): (sick, annual)})

    result = execute(gateway(provider, RecordingAuditSink()), context())

    assert isinstance(result, PublicToolSuccess)
    assert tuple(item.leave_type_code for item in result.result.balances) == ("annual", "sick")


def test_customer_cannot_receive_another_customers_balances() -> None:
    provider = FakeLeaveProvider({("customer_b", "employee_1"): (balance("b"),)})

    result = execute(gateway(provider, RecordingAuditSink()), context("customer_a"))

    assert isinstance(result, PublicToolSuccess)
    assert result.result.balances == ()
    assert provider.calls == [("customer_a", "employee_1", ("entity_1",))]


def test_identical_employee_ids_are_isolated_across_customers() -> None:
    provider = FakeLeaveProvider(
        {
            ("customer_a", "employee_1"): (balance("a"),),
            ("customer_b", "employee_1"): (balance("b"),),
        }
    )
    tool_gateway = gateway(provider, RecordingAuditSink())

    result_a = execute(tool_gateway, context("customer_a"))
    result_b = execute(tool_gateway, context("customer_b"))

    assert isinstance(result_a, PublicToolSuccess)
    assert isinstance(result_b, PublicToolSuccess)
    assert result_a.result.balances[0].leave_type_name == "Annual a"
    assert result_b.result.balances[0].leave_type_name == "Annual b"
