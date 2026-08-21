import asyncio
from dataclasses import FrozenInstanceError
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

import pytest
from pydantic import BaseModel, ConfigDict

from erp_ai.capabilities import (
    CapabilityManifest,
    CapabilityRegistry,
    DataClassification,
    ToolDescriptor,
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


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    detail: Literal["summary"]


class ProfileOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    display_name: str


class NonStrictInput(BaseModel):
    value: str


class NonStrictOutput(BaseModel):
    value: str


class FakeReadHandler:
    tool_name = "get_profile"
    version = "1.0.0"
    input_model = ProfileInput
    output_model = ProfileOutput

    def __init__(self, *, output: object = None, raises: bool = False) -> None:
        self.output = {"display_name": "Synthetic User"} if output is None else output
        self.raises = raises
        self.call_count = 0
        self.received_contexts: list[TrustedRequestContext] = []
        self.received_arguments: list[BaseModel] = []

    async def execute(self, context: TrustedRequestContext, arguments: BaseModel) -> object:
        self.call_count += 1
        self.received_contexts.append(context)
        self.received_arguments.append(arguments)
        if self.raises:
            raise RuntimeError("sensitive handler detail")
        return self.output


class RecordingAuditSink:
    """Test-only sink that records call order and can simulate delivery failure."""

    def __init__(self, *, fails: bool = False) -> None:
        self.fails = fails
        self.attempted_events: list[ToolAuditEvent] = []
        self.events: list[ToolAuditEvent] = []
        self.order: list[str] = []

    async def record(self, event: ToolAuditEvent) -> None:
        self.order.append("record_started")
        self.attempted_events.append(event)
        if self.fails:
            raise RuntimeError("sensitive audit provider detail")
        self.events.append(event)
        self.order.append("record_completed")


def descriptor(
    *,
    name: str = "get_profile",
    version: str = "1.0.0",
    operation: Literal["read", "command"] = "read",
) -> ToolDescriptor:
    return ToolDescriptor(
        tool_name=name,
        version=version,
        operation=operation,
        required_permissions_all=("profile_read",),
        required_roles_any=("employee", "hr"),
        allowed_purposes=("employee_self_service",),
        data_classification=DataClassification.RESTRICTED,
        audit_action="profile_read",
    )


def registry(*tools: ToolDescriptor) -> CapabilityRegistry:
    return CapabilityRegistry(
        [
            CapabilityManifest(
                capability_code="hr_core",
                version="1.0.0",
                required_modules=("hr_core",),
                tools=tools or (descriptor(),),
            )
        ]
    )


def context(
    customer: str = "customer_a",
    *,
    modules: tuple[str, ...] = ("hr_core",),
    permissions: tuple[str, ...] = ("profile_read",),
    roles: tuple[str, ...] = ("employee",),
    purpose: str = "employee_self_service",
) -> TrustedRequestContext:
    return TrustedRequestContext(
        context_version=1,
        request_id=f"req_{customer}",
        customer_environment_id=customer,
        user_id="user_1",
        employee_id="employee_1",
        roles=roles,
        permission_codes=permissions,
        legal_entity_ids=("entity_1",),
        enabled_modules=modules,
        locale="en",
        timezone="Africa/Cairo",
        purpose=purpose,
        issued_at=datetime(2026, 8, 21, 12, 0, tzinfo=ZoneInfo("Africa/Cairo")),
        authorization_snapshot_id=f"snapshot_{customer}",
    )


def invocation(
    *, name: str = "get_profile", version: str = "1.0.0", arguments: object = None
) -> ToolInvocation:
    return ToolInvocation.model_validate(
        {
            "tool_name": name,
            "version": version,
            "arguments": {"detail": "summary"} if arguments is None else arguments,
        },
        strict=True,
    )


def make_gateway(
    capability_registry: CapabilityRegistry,
    handlers: list[object],
    audit_sink: RecordingAuditSink | None = None,
) -> ReadToolGateway:
    return ReadToolGateway(
        capability_registry,
        handlers,  # type: ignore[arg-type]
        audit_sink or RecordingAuditSink(),
    )


def execute(
    gateway: ReadToolGateway,
    trusted_context: TrustedRequestContext,
    tool_invocation: ToolInvocation | None = None,
) -> PublicToolSuccess | PublicToolFailure:
    return asyncio.run(gateway.execute(trusted_context, tool_invocation or invocation()))


def assert_unavailable_before_execution(
    gateway: ReadToolGateway,
    handler: FakeReadHandler,
    trusted_context: TrustedRequestContext,
) -> None:
    result = execute(gateway, trusted_context)

    assert isinstance(result, PublicToolFailure)
    assert result.safe_error_code is ToolErrorCode.TOOL_UNAVAILABLE
    assert handler.call_count == 0


def test_authorized_read_handler_succeeds_and_receives_context_separately() -> None:
    handler = FakeReadHandler()
    gateway = make_gateway(registry(), [handler])
    trusted_context = context()

    result = execute(gateway, trusted_context)

    assert isinstance(result, PublicToolSuccess)
    assert result.result == ProfileOutput(display_name="Synthetic User")
    assert handler.received_contexts == [trusted_context]
    assert handler.received_arguments == [ProfileInput(detail="summary")]
    assert "customer_environment_id" not in handler.received_arguments[0].model_fields_set


@pytest.mark.parametrize(
    "trusted_context",
    [
        context(modules=()),
        context(permissions=()),
        context(roles=("manager",)),
        context(purpose="manager_self_service"),
    ],
)
def test_authorization_failure_occurs_before_handler_execution(
    trusted_context: TrustedRequestContext,
) -> None:
    handler = FakeReadHandler()
    gateway = make_gateway(registry(), [handler])

    assert_unavailable_before_execution(gateway, handler, trusted_context)


def test_unknown_tool_returns_unavailable() -> None:
    gateway = make_gateway(registry(), [FakeReadHandler()])

    result = execute(gateway, context(), invocation(name="unknown_tool"))

    assert isinstance(result, PublicToolFailure)
    assert result.safe_error_code is ToolErrorCode.TOOL_UNAVAILABLE


def test_missing_handler_prevents_model_facing_availability() -> None:
    gateway = make_gateway(registry(), [])

    assert gateway.available_tools(context()) == ()


def test_duplicate_handler_registration_fails() -> None:
    with pytest.raises(ValueError, match="duplicate handler"):
        make_gateway(registry(), [FakeReadHandler(), FakeReadHandler()])


def test_object_without_handler_protocol_fails() -> None:
    with pytest.raises(TypeError, match="ReadToolHandler"):
        make_gateway(registry(), [object()])


def test_unregistered_handler_fails() -> None:
    handler = FakeReadHandler()
    handler.tool_name = "unregistered_tool"

    with pytest.raises(ValueError, match="no registered descriptor"):
        make_gateway(registry(), [handler])


def test_handler_descriptor_version_mismatch_fails() -> None:
    handler = FakeReadHandler()
    handler.version = "2.0.0"

    with pytest.raises(ValueError, match="version mismatch"):
        make_gateway(registry(), [handler])


def test_command_handler_registration_fails() -> None:
    with pytest.raises(ValueError, match="command handlers"):
        make_gateway(registry(descriptor(operation="command")), [FakeReadHandler()])


@pytest.mark.parametrize("model_field", ["input_model", "output_model"])
def test_non_strict_handler_models_fail(model_field: str) -> None:
    handler = FakeReadHandler()
    setattr(
        handler, model_field, NonStrictInput if model_field == "input_model" else NonStrictOutput
    )

    with pytest.raises(ValueError, match="strict and frozen"):
        make_gateway(registry(), [handler])


def test_handler_input_model_must_forbid_extra_fields() -> None:
    class PermissiveInput(BaseModel):
        model_config = ConfigDict(frozen=True, strict=True)

        detail: str

    handler = FakeReadHandler()
    handler.input_model = PermissiveInput

    with pytest.raises(ValueError, match="forbid extra"):
        make_gateway(registry(), [handler])


def test_command_invocation_is_always_rejected() -> None:
    gateway = make_gateway(registry(descriptor(operation="command")), [])

    result = execute(gateway, context())

    assert isinstance(result, PublicToolFailure)
    assert result.safe_error_code is ToolErrorCode.READ_ONLY_VIOLATION


@pytest.mark.parametrize("reserved_name", ["user_id", "read_only_mode", "permission_codes"])
def test_trusted_context_argument_injection_fails(reserved_name: str) -> None:
    handler = FakeReadHandler()
    gateway = make_gateway(registry(), [handler])

    result = execute(
        gateway,
        context(),
        invocation(arguments={"detail": "summary", "nested": {reserved_name: "forged"}}),
    )

    assert isinstance(result, PublicToolFailure)
    assert result.safe_error_code is ToolErrorCode.INVALID_TOOL_ARGUMENTS
    assert handler.call_count == 0


def test_reserved_context_argument_nested_in_sequence_fails() -> None:
    handler = FakeReadHandler()
    gateway = make_gateway(registry(), [handler])

    result = execute(
        gateway,
        context(),
        invocation(arguments={"detail": "summary", "filters": [{"user_id": "forged"}]}),
    )

    assert isinstance(result, PublicToolFailure)
    assert result.safe_error_code is ToolErrorCode.INVALID_TOOL_ARGUMENTS
    assert handler.call_count == 0


def test_reviewed_target_employee_field_is_not_reserved() -> None:
    handler = FakeReadHandler()
    gateway = make_gateway(registry(), [handler])

    result = execute(
        gateway,
        context(),
        invocation(arguments={"detail": "summary", "target_employee_id": "employee_2"}),
    )

    assert isinstance(result, PublicToolFailure)
    assert result.safe_error_code is ToolErrorCode.INVALID_TOOL_ARGUMENTS


def test_invalid_input_fails_before_handler_execution() -> None:
    handler = FakeReadHandler()
    gateway = make_gateway(registry(), [handler])

    result = execute(gateway, context(), invocation(arguments={"detail": "full"}))

    assert isinstance(result, PublicToolFailure)
    assert result.safe_error_code is ToolErrorCode.INVALID_TOOL_ARGUMENTS
    assert handler.call_count == 0


def test_handler_exception_returns_safe_failure() -> None:
    handler = FakeReadHandler(raises=True)
    gateway = make_gateway(registry(), [handler])

    result = execute(gateway, context())

    assert isinstance(result, PublicToolFailure)
    assert result.safe_error_code is ToolErrorCode.TOOL_EXECUTION_FAILED
    assert "sensitive" not in result.safe_message


def test_invalid_handler_output_returns_safe_failure() -> None:
    handler = FakeReadHandler(output={"wrong": "shape"})
    gateway = make_gateway(registry(), [handler])

    result = execute(gateway, context())

    assert isinstance(result, PublicToolFailure)
    assert result.safe_error_code is ToolErrorCode.INVALID_TOOL_OUTPUT


def test_customer_contexts_do_not_contaminate_and_access_is_recalculated() -> None:
    handler = FakeReadHandler()
    gateway = make_gateway(registry(), [handler])

    allowed = execute(gateway, context("customer_a"))
    denied = execute(gateway, context("customer_b", permissions=()))
    allowed_again = execute(gateway, context("customer_a"))

    assert isinstance(allowed, PublicToolSuccess)
    assert isinstance(denied, PublicToolFailure)
    assert isinstance(allowed_again, PublicToolSuccess)
    assert handler.call_count == 2
    assert [item.customer_environment_id for item in handler.received_contexts] == [
        "customer_a",
        "customer_a",
    ]


def test_gateway_and_available_results_are_immutable() -> None:
    gateway = make_gateway(registry(), [FakeReadHandler()])
    available = gateway.available_tools(context())

    assert isinstance(available, tuple)
    with pytest.raises(FrozenInstanceError):
        gateway.handlers = ()  # type: ignore[misc]


def test_failure_message_excludes_authorization_details() -> None:
    gateway = make_gateway(registry(), [FakeReadHandler()])

    result = execute(gateway, context(permissions=()))

    assert isinstance(result, PublicToolFailure)
    for detail in ("profile_read", "employee", "hr_core", "permission", "role", "module"):
        assert detail not in result.safe_message.lower()


def test_gateway_construction_without_audit_sink_fails() -> None:
    with pytest.raises(TypeError):
        ReadToolGateway(registry(), [FakeReadHandler()])  # type: ignore[call-arg]


def test_gateway_rejects_invalid_audit_sink() -> None:
    with pytest.raises(TypeError, match="ToolAuditSink"):
        ReadToolGateway(registry(), [FakeReadHandler()], object())  # type: ignore[arg-type]


def test_success_records_exactly_one_event_before_return() -> None:
    sink = RecordingAuditSink()
    gateway = make_gateway(registry(), [FakeReadHandler()], sink)

    result = execute(gateway, context())

    assert isinstance(result, PublicToolSuccess)
    assert len(sink.attempted_events) == 1
    assert len(sink.events) == 1
    assert sink.events[0].outcome == "success"
    assert sink.order == ["record_started", "record_completed"]


def test_authorization_denial_records_exactly_one_event() -> None:
    sink = RecordingAuditSink()
    gateway = make_gateway(registry(), [FakeReadHandler()], sink)

    result = execute(gateway, context(permissions=()))

    assert isinstance(result, PublicToolFailure)
    assert len(sink.events) == 1
    assert sink.events[0].outcome == "failure"


def test_invalid_arguments_record_exactly_one_event() -> None:
    sink = RecordingAuditSink()
    gateway = make_gateway(registry(), [FakeReadHandler()], sink)

    result = execute(gateway, context(), invocation(arguments={"detail": "invalid"}))

    assert isinstance(result, PublicToolFailure)
    assert len(sink.events) == 1
    assert sink.events[0].internal_reason == "input_validation_failed"


def test_handler_failure_records_exactly_one_event() -> None:
    sink = RecordingAuditSink()
    gateway = make_gateway(registry(), [FakeReadHandler(raises=True)], sink)

    result = execute(gateway, context())

    assert isinstance(result, PublicToolFailure)
    assert len(sink.events) == 1
    assert sink.events[0].internal_reason == "handler_execution_failed"


def test_invalid_output_records_exactly_one_event() -> None:
    sink = RecordingAuditSink()
    gateway = make_gateway(registry(), [FakeReadHandler(output={"wrong": "shape"})], sink)

    result = execute(gateway, context())

    assert isinstance(result, PublicToolFailure)
    assert len(sink.events) == 1
    assert sink.events[0].internal_reason == "output_validation_failed"


def test_unknown_tool_records_generic_audit_event() -> None:
    sink = RecordingAuditSink()
    gateway = make_gateway(registry(), [FakeReadHandler()], sink)

    result = execute(gateway, context(), invocation(name="unknown_tool"))

    assert isinstance(result, PublicToolFailure)
    assert len(sink.events) == 1
    assert sink.events[0].audit_action == "tool.invocation_denied"
    assert sink.events[0].data_classification is DataClassification.INTERNAL


def test_audit_failure_replaces_success_and_hides_exception() -> None:
    sink = RecordingAuditSink(fails=True)
    gateway = make_gateway(registry(), [FakeReadHandler()], sink)

    result = execute(gateway, context())

    assert isinstance(result, PublicToolFailure)
    assert result.safe_error_code is ToolErrorCode.AUDIT_UNAVAILABLE
    assert "sensitive" not in result.safe_message
    assert "Synthetic User" not in repr(result.model_dump())
    assert len(sink.attempted_events) == 1
    assert sink.events == []
    assert sink.order == ["record_started"]
