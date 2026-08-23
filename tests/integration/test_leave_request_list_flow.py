import asyncio
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from erp_ai.capabilities import CapabilityRegistry, DataClassification
from erp_ai.capabilities.leave import (
    LEAVE_MANIFEST,
    LeaveRequestPageRecord,
    LeaveRequestStatus,
    LeaveRequestSummaryRecord,
    ListMyLeaveRequestsHandler,
    ListMyLeaveRequestsOutput,
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

EMPLOYEE_ID = UUID("00000000-0000-4000-8000-000000000002")
ENTITY_ID = UUID("00000000-0000-4000-8000-000000000003")


def request_record(customer: str, **overrides: object) -> LeaveRequestSummaryRecord:
    payload: dict[str, object] = {
        "request_id": UUID("00000000-0000-4000-8000-000000000001"),
        "employee_id": EMPLOYEE_ID,
        "legal_entity_id": ENTITY_ID,
        "leave_type_id": UUID("00000000-0000-4000-8000-000000000004"),
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
        "working_days_calculation_version": "calendar_v1",
    }
    payload.update(overrides)
    return LeaveRequestSummaryRecord.model_validate(payload, strict=True)


class FakeLeaveRequestProvider:
    def __init__(self, pages: dict[tuple[str, str], LeaveRequestPageRecord]) -> None:
        self.pages = pages
        self.calls: list[dict[str, object]] = []
        self.raises = False

    async def list_my_leave_requests(self, **kwargs: object) -> LeaveRequestPageRecord:
        self.calls.append(kwargs)
        if self.raises:
            raise RuntimeError("private provider error containing sensitive values")
        key = (str(kwargs["customer_environment_id"]), str(kwargs["employee_id"]))
        return self.pages.get(key, LeaveRequestPageRecord(items=()))

    async def get_my_leave_balances(self, **kwargs: object) -> object:
        raise AssertionError(f"unexpected balance call: {kwargs}")

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
    employee_id: str | None = str(EMPLOYEE_ID),
    modules: tuple[str, ...] = ("hr_core", "leave"),
    permissions: tuple[str, ...] = ("leave.request.read_self",),
    purpose: str = "employee_self_service",
    roles: tuple[str, ...] = ("hr",),
) -> TrustedRequestContext:
    return TrustedRequestContext(
        context_version=1,
        request_id=f"req_{customer}",
        customer_environment_id=customer,
        user_id=f"user_{customer}",
        employee_id=employee_id,
        roles=roles,
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
            "tool_name": "list_my_leave_requests",
            "version": "1.0.0",
            "arguments": {} if arguments is None else arguments,
        },
        strict=True,
    )


def gateway(provider: FakeLeaveRequestProvider, sink: RecordingAuditSink) -> ReadToolGateway:
    return ReadToolGateway(
        CapabilityRegistry([LEAVE_MANIFEST]),
        [ListMyLeaveRequestsHandler(provider)],
        sink,
    )


def execute(
    tool_gateway: ReadToolGateway,
    trusted_context: TrustedRequestContext,
    tool_invocation: ToolInvocation | None = None,
) -> PublicToolSuccess | PublicToolFailure:
    return asyncio.run(tool_gateway.execute(trusted_context, tool_invocation or invocation()))


def test_complete_authorized_filtered_page_flow_and_audit() -> None:
    provider = FakeLeaveRequestProvider(
        {
            ("customer_a", str(EMPLOYEE_ID)): LeaveRequestPageRecord(
                items=(request_record("a"),), next_cursor="opaque.next.secret"
            )
        }
    )
    sink = RecordingAuditSink()
    arguments = {
        "statuses": ["pending"],
        "start_from": "2026-01-01",
        "start_to": "2026-12-31",
        "limit": 10,
        "cursor": "opaque.current.secret",
    }

    result = execute(gateway(provider, sink), context(), invocation(arguments))

    assert isinstance(result, PublicToolSuccess)
    assert isinstance(result.result, ListMyLeaveRequestsOutput)
    assert result.result.requests[0].leave_type_name == "Annual a"
    assert isinstance(result.result.requests[0].working_days, Decimal)
    assert result.result.next_cursor == "opaque.next.secret"
    assert provider.calls[0]["customer_environment_id"] == "customer_a"
    assert provider.calls[0]["employee_id"] == str(EMPLOYEE_ID)
    assert provider.calls[0]["authorized_legal_entity_ids"] == (str(ENTITY_ID),)
    assert provider.calls[0]["statuses"] == (LeaveRequestStatus.PENDING,)
    assert provider.calls[0]["cursor"] == "opaque.current.secret"
    assert len(sink.events) == 1
    assert sink.events[0].data_classification is DataClassification.RESTRICTED
    assert sink.events[0].audit_action == "leave.request.list_self"
    audit = sink.events[0].model_dump()
    assert not {"requests", "statuses", "cursor", "working_days"} & set(audit)
    assert "opaque.current.secret" not in repr(audit)
    assert "Annual a" not in repr(audit)
    assert str(request_record("a").request_id) not in repr(audit)


@pytest.mark.parametrize(
    "arguments",
    [
        {"employee_id": str(EMPLOYEE_ID)},
        {"customer_environment_id": "customer_b"},
        {"legal_entity_ids": [str(ENTITY_ID)]},
        {"enabled_modules": ["leave"]},
        {"permission_codes": ["leave.request.read_self"]},
        {"roles": ["employee"]},
        {"fiscal_year": 2026},
        {"reviewer": "forged"},
        {"approval_request_id": str(UUID(int=9))},
    ],
)
def test_trusted_and_unsupported_fields_are_rejected(arguments: dict[str, object]) -> None:
    provider = FakeLeaveRequestProvider({})

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
def test_authorization_denial_prevents_provider_execution(
    trusted_context: TrustedRequestContext,
) -> None:
    provider = FakeLeaveRequestProvider({})
    tool_gateway = gateway(provider, RecordingAuditSink())

    assert tool_gateway.available_tools(trusted_context) == ()
    result = execute(tool_gateway, trusted_context)

    assert isinstance(result, PublicToolFailure)
    assert result.safe_error_code is ToolErrorCode.TOOL_UNAVAILABLE
    assert provider.calls == []


def test_empty_page_is_a_success() -> None:
    result = execute(gateway(FakeLeaveRequestProvider({}), RecordingAuditSink()), context())

    assert isinstance(result, PublicToolSuccess)
    assert result.result.requests == ()


def test_out_of_order_provider_page_fails_safely() -> None:
    newer = request_record(
        "a",
        request_id=UUID("00000000-0000-4000-8000-000000000005"),
        submitted_at=datetime(2026, 8, 23, 9, 0, tzinfo=ZoneInfo("Africa/Cairo")),
    )
    provider = FakeLeaveRequestProvider(
        {
            ("customer_a", str(EMPLOYEE_ID)): LeaveRequestPageRecord(
                items=(request_record("a"), newer)
            )
        }
    )

    result = execute(gateway(provider, RecordingAuditSink()), context())

    assert isinstance(result, PublicToolFailure)
    assert result.safe_error_code is ToolErrorCode.TOOL_EXECUTION_FAILED
    assert "order" not in result.safe_message.lower()


@pytest.mark.parametrize(
    "bad_record",
    [
        request_record("a", employee_id=UUID("00000000-0000-4000-8000-000000000099")),
        request_record("a", legal_entity_id=UUID("00000000-0000-4000-8000-000000000099")),
    ],
)
def test_scope_violation_fails_complete_page(bad_record: LeaveRequestSummaryRecord) -> None:
    provider = FakeLeaveRequestProvider(
        {
            ("customer_a", str(EMPLOYEE_ID)): LeaveRequestPageRecord(
                items=(request_record("a"), bad_record)
            )
        }
    )

    result = execute(gateway(provider, RecordingAuditSink()), context())

    assert isinstance(result, PublicToolFailure)
    assert result.safe_error_code is ToolErrorCode.TOOL_EXECUTION_FAILED
    assert "mismatch" not in result.safe_message.lower()


def test_duplicate_request_and_invalid_provider_data_fail_safely() -> None:
    duplicate_provider = FakeLeaveRequestProvider(
        {
            ("customer_a", str(EMPLOYEE_ID)): LeaveRequestPageRecord(
                items=(request_record("a"), request_record("a"))
            )
        }
    )
    duplicate_result = execute(gateway(duplicate_provider, RecordingAuditSink()), context())
    assert isinstance(duplicate_result, PublicToolFailure)
    assert duplicate_result.safe_error_code is ToolErrorCode.TOOL_EXECUTION_FAILED

    invalid_provider = FakeLeaveRequestProvider({})
    invalid_provider.pages[("customer_a", str(EMPLOYEE_ID))] = object()  # type: ignore[assignment]
    invalid_result = execute(gateway(invalid_provider, RecordingAuditSink()), context())
    assert isinstance(invalid_result, PublicToolFailure)
    assert invalid_result.safe_error_code is ToolErrorCode.TOOL_EXECUTION_FAILED


def test_provider_exception_is_safe() -> None:
    provider = FakeLeaveRequestProvider({})
    provider.raises = True

    result = execute(gateway(provider, RecordingAuditSink()), context())

    assert isinstance(result, PublicToolFailure)
    assert result.safe_error_code is ToolErrorCode.TOOL_EXECUTION_FAILED
    assert "private" not in result.safe_message.lower()


def test_customers_with_same_employee_uuid_remain_isolated() -> None:
    provider = FakeLeaveRequestProvider(
        {
            ("customer_a", str(EMPLOYEE_ID)): LeaveRequestPageRecord(items=(request_record("a"),)),
            ("customer_b", str(EMPLOYEE_ID)): LeaveRequestPageRecord(items=(request_record("b"),)),
        }
    )
    tool_gateway = gateway(provider, RecordingAuditSink())

    result_a = execute(tool_gateway, context("customer_a"))
    result_b = execute(tool_gateway, context("customer_b"))

    assert isinstance(result_a, PublicToolSuccess)
    assert isinstance(result_b, PublicToolSuccess)
    assert result_a.result.requests[0].leave_type_name == "Annual a"
    assert result_b.result.requests[0].leave_type_name == "Annual b"


def test_customer_cannot_receive_page_stored_only_for_another_customer() -> None:
    provider = FakeLeaveRequestProvider(
        {("customer_b", str(EMPLOYEE_ID)): LeaveRequestPageRecord(items=(request_record("b"),))}
    )

    result = execute(gateway(provider, RecordingAuditSink()), context("customer_a"))

    assert isinstance(result, PublicToolSuccess)
    assert result.result.requests == ()


def test_two_provider_pages_have_no_duplicate_or_skipped_requests() -> None:
    first_record = request_record(
        "a",
        request_id=UUID("00000000-0000-4000-8000-000000000001"),
        submitted_at=datetime(2026, 8, 23, 9, 0, tzinfo=ZoneInfo("Africa/Cairo")),
    )
    second_record = request_record(
        "a",
        request_id=UUID("00000000-0000-4000-8000-000000000002"),
        submitted_at=datetime(2026, 8, 22, 9, 0, tzinfo=ZoneInfo("Africa/Cairo")),
    )

    class TwoPageProvider:
        def __init__(self) -> None:
            self.cursors: list[object] = []

        async def list_my_leave_requests(self, **kwargs: object) -> LeaveRequestPageRecord:
            cursor = kwargs["cursor"]
            self.cursors.append(cursor)
            if cursor is None:
                return LeaveRequestPageRecord(items=(first_record,), next_cursor="opaque.page.two")
            if cursor == "opaque.page.two":
                return LeaveRequestPageRecord(items=(second_record,))
            raise AssertionError("unexpected synthetic cursor")

        async def get_my_leave_balances(self, **kwargs: object) -> object:
            raise AssertionError(f"unexpected balance call: {kwargs}")

        async def get_my_leave_request(self, **kwargs: object) -> object:
            raise AssertionError(f"unexpected request-detail call: {kwargs}")

    provider = TwoPageProvider()
    tool_gateway = ReadToolGateway(
        CapabilityRegistry([LEAVE_MANIFEST]),
        [ListMyLeaveRequestsHandler(provider)],
        RecordingAuditSink(),
    )

    first = execute(tool_gateway, context(), invocation({"limit": 1}))
    assert isinstance(first, PublicToolSuccess)
    second = execute(
        tool_gateway,
        context(),
        invocation({"limit": 1, "cursor": first.result.next_cursor}),
    )
    assert isinstance(second, PublicToolSuccess)

    request_ids = tuple(
        item.request_id for result in (first, second) for item in result.result.requests
    )
    assert request_ids == (first_record.request_id, second_record.request_id)
    assert len(set(request_ids)) == 2
    assert provider.cursors == [None, "opaque.page.two"]
