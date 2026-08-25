import asyncio
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from erp_ai.capabilities import CapabilityRegistry, DataClassification
from erp_ai.capabilities.leave import (
    LEAVE_MANIFEST,
    GetMyLeaveRequestHandler,
    GetMyLeaveRequestOutput,
    LeaveRequestDetailRecord,
    LeaveRequestHistoryRecord,
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

REQUEST_ID = UUID("10000000-0000-4000-8000-000000000001")
EMPLOYEE_ID = UUID("10000000-0000-4000-8000-000000000002")
ENTITY_ID = UUID("10000000-0000-4000-8000-000000000003")


def detail(customer: str, **overrides: object) -> LeaveRequestDetailRecord:
    history = LeaveRequestHistoryRecord.model_validate(
        {
            "history_id": UUID("20000000-0000-4000-8000-000000000001"),
            "entity_type": "leave_request",
            "entity_id": REQUEST_ID,
            "from_status": None,
            "to_status": "pending",
            "changed_at": datetime(2026, 8, 22, 9, 0, tzinfo=ZoneInfo("Africa/Cairo")),
            "reason_code": "submitted",
        },
        strict=True,
    )
    payload: dict[str, object] = {
        "request_id": REQUEST_ID,
        "employee_id": EMPLOYEE_ID,
        "legal_entity_id": ENTITY_ID,
        "leave_type_id": UUID("10000000-0000-4000-8000-000000000004"),
        "leave_type_code": "annual",
        "leave_type_name": f"Annual {customer}",
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
        "customer_environment_id": customer,
        "status_history": (history,),
    }
    payload.update(overrides)
    return LeaveRequestDetailRecord.model_validate(payload, strict=True)


class FakeDetailProvider:
    def __init__(
        self,
        records: dict[tuple[str, str, UUID], LeaveRequestDetailRecord],
    ) -> None:
        self.records = records
        self.calls: list[dict[str, object]] = []
        self.raises = False

    async def get_my_leave_request(self, **kwargs: object) -> LeaveRequestDetailRecord | None:
        self.calls.append(kwargs)
        if self.raises:
            raise RuntimeError("private detail provider failure")
        key = (
            str(kwargs["customer_environment_id"]),
            str(kwargs["employee_id"]),
            kwargs["request_id"],
        )
        return self.records.get(key)  # type: ignore[arg-type]

    async def get_my_leave_balances(self, **kwargs: object) -> object:
        raise AssertionError(f"unexpected balance call: {kwargs}")

    async def list_my_leave_requests(self, **kwargs: object) -> object:
        raise AssertionError(f"unexpected list call: {kwargs}")


class RecordingAuditSink:
    def __init__(self) -> None:
        self.events: list[ToolAuditEvent] = []

    async def record(self, event: ToolAuditEvent) -> None:
        self.events.append(event)


def context(
    customer: str = "customer_a",
    *,
    employee_id: str | None = str(EMPLOYEE_ID),
    modules: tuple[str, ...] = ("hr_core", "leave"),
    permissions: tuple[str, ...] = ("leave.request.read_self",),
    purpose: str = "employee_self_service",
) -> TrustedRequestContext:
    return TrustedRequestContext(
        context_version=1,
        request_id=f"correlation_{customer}",
        customer_environment_id=customer,
        user_id=f"user_{customer}",
        employee_id=employee_id,
        roles=("manager",),
        permission_codes=permissions,
        legal_entity_ids=(str(ENTITY_ID),),
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
            "tool_name": "get_my_leave_request",
            "version": "1.0.0",
            "arguments": ({"request_id": str(REQUEST_ID)} if arguments is None else arguments),
        },
        strict=True,
    )


def gateway(provider: FakeDetailProvider, sink: RecordingAuditSink) -> ReadToolGateway:
    return ReadToolGateway(
        CapabilityRegistry([LEAVE_MANIFEST]),
        [GetMyLeaveRequestHandler(provider)],
        sink,
    )


def execute(
    tool_gateway: ReadToolGateway,
    trusted_context: TrustedRequestContext,
    tool_invocation: ToolInvocation | None = None,
) -> PublicToolSuccess | PublicToolFailure:
    return asyncio.run(tool_gateway.execute(trusted_context, tool_invocation or invocation()))


def test_complete_authorized_detail_flow_and_minimized_audit() -> None:
    provider = FakeDetailProvider(
        {("customer_a", str(EMPLOYEE_ID), REQUEST_ID): detail("customer_a")}
    )
    sink = RecordingAuditSink()

    result = execute(gateway(provider, sink), context())

    assert isinstance(result, PublicToolSuccess)
    assert isinstance(result.result, GetMyLeaveRequestOutput)
    assert result.result.leave_type_name == "Annual customer_a"
    assert provider.calls == [
        {
            "customer_environment_id": "customer_a",
            "employee_id": str(EMPLOYEE_ID),
            "authorized_legal_entity_ids": (str(ENTITY_ID),),
            "request_id": REQUEST_ID,
        }
    ]
    assert len(sink.events) == 1
    assert sink.events[0].data_classification is DataClassification.RESTRICTED
    assert sink.events[0].audit_action == "leave.request.detail.read_self"
    audit = sink.events[0].model_dump()
    assert not {
        "arguments",
        "timeline",
        "start_date",
        "end_date",
        "working_days",
        "employee_id",
        "roles",
        "permission_codes",
        "legal_entity_ids",
    } & set(audit)
    assert str(REQUEST_ID) not in repr(audit)
    assert "Annual customer_a" not in repr(audit)


@pytest.mark.parametrize(
    "arguments",
    [
        {"request_id": "not-a-uuid"},
        {"request_id": str(REQUEST_ID), "employee_id": str(EMPLOYEE_ID)},
        {"request_id": str(REQUEST_ID), "customer_environment_id": "customer_b"},
        {"request_id": str(REQUEST_ID), "legal_entity_ids": [str(ENTITY_ID)]},
        {"request_id": str(REQUEST_ID), "permissions": ["admin"]},
    ],
)
def test_invalid_or_injected_arguments_never_reach_provider(
    arguments: dict[str, object],
) -> None:
    provider = FakeDetailProvider({})

    result = execute(gateway(provider, RecordingAuditSink()), context(), invocation(arguments))

    assert isinstance(result, PublicToolFailure)
    assert result.safe_error_code is ToolErrorCode.INVALID_TOOL_ARGUMENTS
    assert provider.calls == []


@pytest.mark.parametrize(
    "trusted_context",
    [
        context(employee_id=None),
        context(modules=("hr_core",)),
        context(modules=("leave",)),
        context(permissions=()),
        context(purpose="manager_service"),
    ],
)
def test_authorization_denial_occurs_before_provider(
    trusted_context: TrustedRequestContext,
) -> None:
    provider = FakeDetailProvider({})
    tool_gateway = gateway(provider, RecordingAuditSink())

    assert tool_gateway.available_tools(trusted_context) == ()
    result = execute(tool_gateway, trusted_context)

    assert isinstance(result, PublicToolFailure)
    assert result.safe_error_code is ToolErrorCode.TOOL_UNAVAILABLE
    assert provider.calls == []


@pytest.mark.parametrize(
    "provider_record",
    [
        detail(
            "customer_a",
            request_id=UUID("10000000-0000-4000-8000-000000000099"),
        ),
        detail("customer_b"),
        detail(
            "customer_a",
            employee_id=UUID("10000000-0000-4000-8000-000000000099"),
        ),
        detail(
            "customer_a",
            legal_entity_id=UUID("10000000-0000-4000-8000-000000000099"),
        ),
    ],
)
def test_inaccessible_or_mismatched_record_has_same_safe_failure(
    provider_record: LeaveRequestDetailRecord,
) -> None:
    provider = FakeDetailProvider({("customer_a", str(EMPLOYEE_ID), REQUEST_ID): provider_record})

    result = execute(gateway(provider, RecordingAuditSink()), context())

    assert isinstance(result, PublicToolFailure)
    assert result.safe_error_code is ToolErrorCode.TOOL_EXECUTION_FAILED
    assert "mismatch" not in result.safe_message.lower()


def test_not_found_provider_exception_and_malformed_output_fail_safely() -> None:
    not_found = execute(gateway(FakeDetailProvider({}), RecordingAuditSink()), context())
    assert isinstance(not_found, PublicToolFailure)
    assert not_found.safe_error_code is ToolErrorCode.TOOL_EXECUTION_FAILED

    failing_provider = FakeDetailProvider({})
    failing_provider.raises = True
    exception_result = execute(gateway(failing_provider, RecordingAuditSink()), context())
    assert isinstance(exception_result, PublicToolFailure)
    assert exception_result.safe_error_code is ToolErrorCode.TOOL_EXECUTION_FAILED
    assert "private" not in exception_result.safe_message.lower()

    malformed_provider = FakeDetailProvider({})
    malformed_provider.records[("customer_a", str(EMPLOYEE_ID), REQUEST_ID)] = object()  # type: ignore[assignment]
    malformed = execute(gateway(malformed_provider, RecordingAuditSink()), context())
    assert isinstance(malformed, PublicToolFailure)
    assert malformed.safe_error_code is ToolErrorCode.TOOL_EXECUTION_FAILED


def test_identical_request_uuid_remains_customer_isolated() -> None:
    provider = FakeDetailProvider(
        {
            ("customer_a", str(EMPLOYEE_ID), REQUEST_ID): detail("customer_a"),
            ("customer_b", str(EMPLOYEE_ID), REQUEST_ID): detail("customer_b"),
        }
    )
    tool_gateway = gateway(provider, RecordingAuditSink())

    result_a = execute(tool_gateway, context("customer_a"))
    result_b = execute(tool_gateway, context("customer_b"))

    assert isinstance(result_a, PublicToolSuccess)
    assert isinstance(result_b, PublicToolSuccess)
    assert result_a.result.leave_type_name == "Annual customer_a"
    assert result_b.result.leave_type_name == "Annual customer_b"


def test_customer_cannot_receive_detail_stored_only_for_another_customer() -> None:
    provider = FakeDetailProvider(
        {("customer_b", str(EMPLOYEE_ID), REQUEST_ID): detail("customer_b")}
    )

    result = execute(gateway(provider, RecordingAuditSink()), context("customer_a"))

    assert isinstance(result, PublicToolFailure)
    assert result.safe_error_code is ToolErrorCode.TOOL_EXECUTION_FAILED
