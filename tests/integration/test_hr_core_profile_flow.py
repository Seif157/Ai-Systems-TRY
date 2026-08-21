import asyncio
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from erp_ai.capabilities import CapabilityRegistry, DataClassification
from erp_ai.capabilities.hr_core import (
    HR_CORE_MANIFEST,
    EmployeeProfileRecord,
    GetMyEmployeeProfileHandler,
    GetMyEmployeeProfileOutput,
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


class FakeHrCoreProvider:
    def __init__(self, records: dict[tuple[str, str], EmployeeProfileRecord]) -> None:
        self.records = records
        self.calls: list[tuple[str, str]] = []
        self.raises = False

    async def get_my_employee_profile(
        self, *, customer_environment_id: str, employee_id: str
    ) -> EmployeeProfileRecord | None:
        self.calls.append((customer_environment_id, employee_id))
        if self.raises:
            raise RuntimeError("private provider failure")
        return self.records.get((customer_environment_id, employee_id))


class RecordingAuditSink:
    def __init__(self) -> None:
        self.events: list[ToolAuditEvent] = []

    async def record(self, event: ToolAuditEvent) -> None:
        self.events.append(event)


def record(
    customer: str,
    *,
    employee_id: str = "employee_1",
    legal_entity_id: str = "entity_1",
) -> EmployeeProfileRecord:
    return EmployeeProfileRecord(
        employee_id=employee_id,
        legal_entity_id=legal_entity_id,
        employee_number=f"EMP-{customer[-1].upper()}",
        display_name=f"Synthetic {customer}",
        work_email=f"{customer}@example.test",
        job_title="Engineer",
        department_name="Engineering",
        branch_name="Cairo",
        legal_entity_name="Example Egypt",
        employment_status="active",
        hire_date=date(2024, 1, 15),
        manager_display_name="Synthetic Manager",
        freshness_at=datetime(2026, 8, 22, 9, 0, tzinfo=ZoneInfo("Africa/Cairo")),
    )


def context(
    customer: str = "customer_a",
    *,
    employee_id: str | None = "employee_1",
    modules: tuple[str, ...] = ("hr_core",),
    permissions: tuple[str, ...] = ("hr.profile.read_self",),
    roles: tuple[str, ...] = ("employee",),
    purpose: str = "employee_self_service",
    legal_entities: tuple[str, ...] = ("entity_1",),
) -> TrustedRequestContext:
    return TrustedRequestContext(
        context_version=1,
        request_id=f"req_{customer}",
        customer_environment_id=customer,
        user_id=f"user_{customer}",
        employee_id=employee_id,
        roles=roles,
        permission_codes=permissions,
        legal_entity_ids=legal_entities,
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
            "tool_name": "get_my_employee_profile",
            "version": "1.0.0",
            "arguments": {} if arguments is None else arguments,
        },
        strict=True,
    )


def gateway(provider: FakeHrCoreProvider, sink: RecordingAuditSink) -> ReadToolGateway:
    return ReadToolGateway(
        CapabilityRegistry([HR_CORE_MANIFEST]),
        [GetMyEmployeeProfileHandler(provider)],
        sink,
    )


def execute(
    tool_gateway: ReadToolGateway,
    trusted_context: TrustedRequestContext,
    tool_invocation: ToolInvocation | None = None,
) -> PublicToolSuccess | PublicToolFailure:
    return asyncio.run(tool_gateway.execute(trusted_context, tool_invocation or invocation()))


def test_complete_authorized_profile_flow_returns_safe_output_and_audit() -> None:
    provider = FakeHrCoreProvider({("customer_a", "employee_1"): record("customer_a")})
    sink = RecordingAuditSink()
    tool_gateway = gateway(provider, sink)

    result = execute(tool_gateway, context())

    assert isinstance(result, PublicToolSuccess)
    assert isinstance(result.result, GetMyEmployeeProfileOutput)
    assert result.result.display_name == "Synthetic customer_a"
    assert provider.calls == [("customer_a", "employee_1")]
    assert len(sink.events) == 1
    assert sink.events[0].audit_action == "hr.profile.read_self"
    assert sink.events[0].data_classification is DataClassification.RESTRICTED
    audit_payload = sink.events[0].model_dump()
    assert not {"employee_id", "result", "arguments", "display_name"} & set(audit_payload)
    assert "Synthetic customer_a" not in repr(audit_payload)


def test_profile_tool_accepts_only_empty_model_arguments() -> None:
    provider = FakeHrCoreProvider({("customer_a", "employee_1"): record("customer_a")})
    sink = RecordingAuditSink()

    result = execute(gateway(provider, sink), context(), invocation({"unexpected": True}))

    assert isinstance(result, PublicToolFailure)
    assert result.safe_error_code is ToolErrorCode.INVALID_TOOL_ARGUMENTS
    assert provider.calls == []


@pytest.mark.parametrize("trusted_field", ["employee_id", "customer_environment_id"])
def test_trusted_identifier_injection_is_rejected(trusted_field: str) -> None:
    provider = FakeHrCoreProvider({("customer_a", "employee_1"): record("customer_a")})

    result = execute(
        gateway(provider, RecordingAuditSink()),
        context(),
        invocation({trusted_field: "forged"}),
    )

    assert isinstance(result, PublicToolFailure)
    assert result.safe_error_code is ToolErrorCode.INVALID_TOOL_ARGUMENTS
    assert provider.calls == []


@pytest.mark.parametrize(
    "trusted_context",
    [
        context(employee_id=None),
        context(modules=()),
        context(permissions=()),
        context(purpose="manager_self_service"),
    ],
)
def test_missing_authorization_context_hides_and_rejects_before_provider(
    trusted_context: TrustedRequestContext,
) -> None:
    provider = FakeHrCoreProvider({("customer_a", "employee_1"): record("customer_a")})
    tool_gateway = gateway(provider, RecordingAuditSink())

    assert tool_gateway.available_tools(trusted_context) == ()
    result = execute(tool_gateway, trusted_context)

    assert isinstance(result, PublicToolFailure)
    assert result.safe_error_code is ToolErrorCode.TOOL_UNAVAILABLE
    assert provider.calls == []


@pytest.mark.parametrize("role", ["manager", "hr"])
def test_linked_authorized_user_can_read_own_profile_without_employee_role(
    role: str,
) -> None:
    provider = FakeHrCoreProvider({("customer_a", "employee_1"): record("customer_a")})

    result = execute(gateway(provider, RecordingAuditSink()), context(roles=(role,)))

    assert isinstance(result, PublicToolSuccess)
    assert provider.calls == [("customer_a", "employee_1")]


@pytest.mark.parametrize(
    "provider_record",
    [
        None,
        record("customer_a", employee_id="employee_2"),
        record("customer_a", legal_entity_id="entity_2"),
    ],
)
def test_provider_record_failure_returns_no_profile(
    provider_record: EmployeeProfileRecord | None,
) -> None:
    records = {} if provider_record is None else {("customer_a", "employee_1"): provider_record}
    provider = FakeHrCoreProvider(records)

    result = execute(gateway(provider, RecordingAuditSink()), context())

    assert isinstance(result, PublicToolFailure)
    assert result.safe_error_code is ToolErrorCode.TOOL_EXECUTION_FAILED
    assert "mismatch" not in result.safe_message.lower()


def test_provider_exception_returns_safe_failure() -> None:
    provider = FakeHrCoreProvider({("customer_a", "employee_1"): record("customer_a")})
    provider.raises = True

    result = execute(gateway(provider, RecordingAuditSink()), context())

    assert isinstance(result, PublicToolFailure)
    assert result.safe_error_code is ToolErrorCode.TOOL_EXECUTION_FAILED
    assert "private" not in result.safe_message


def test_same_employee_identifier_remains_isolated_by_customer() -> None:
    provider = FakeHrCoreProvider(
        {
            ("customer_a", "employee_1"): record("customer_a"),
            ("customer_b", "employee_1"): record("customer_b"),
        }
    )
    tool_gateway = gateway(provider, RecordingAuditSink())

    result_a = execute(tool_gateway, context("customer_a"))
    result_b = execute(tool_gateway, context("customer_b"))

    assert isinstance(result_a, PublicToolSuccess)
    assert isinstance(result_b, PublicToolSuccess)
    assert result_a.result.display_name == "Synthetic customer_a"
    assert result_b.result.display_name == "Synthetic customer_b"
    assert provider.calls == [
        ("customer_a", "employee_1"),
        ("customer_b", "employee_1"),
    ]


def test_customer_cannot_receive_a_record_stored_only_for_another_customer() -> None:
    provider = FakeHrCoreProvider({("customer_b", "employee_1"): record("customer_b")})

    result = execute(gateway(provider, RecordingAuditSink()), context("customer_a"))

    assert isinstance(result, PublicToolFailure)
    assert result.safe_error_code is ToolErrorCode.TOOL_EXECUTION_FAILED
    assert provider.calls == [("customer_a", "employee_1")]
