"""Read-only execution boundary for model-requested ERP tools."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from pydantic import BaseModel, ValidationError

from erp_ai.capabilities import (
    CapabilityRegistry,
    ModelToolDescriptor,
    ToolDescriptor,
    evaluate_capability_access,
)
from erp_ai.context import TrustedRequestContext
from erp_ai.tools.audit import ToolAuditEvent, ToolAuditSink, create_tool_audit_event
from erp_ai.tools.errors import SAFE_ERROR_MESSAGES, ToolErrorCode
from erp_ai.tools.handlers import ReadToolHandler
from erp_ai.tools.models import (
    PublicToolFailure,
    PublicToolResult,
    PublicToolSuccess,
    ToolInvocation,
)

RESERVED_ARGUMENT_NAMES = frozenset(
    {
        "context_version",
        "customer_environment_id",
        "user_id",
        "employee_id",
        "roles",
        "permission_codes",
        "legal_entity_ids",
        "enabled_modules",
        "locale",
        "timezone",
        "purpose",
        "issued_at",
        "authorization_snapshot_id",
        "read_only_mode",
    }
)


def _contains_reserved_argument(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(
            key in RESERVED_ARGUMENT_NAMES or _contains_reserved_argument(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_reserved_argument(item) for item in value)
    return False


def _strict_frozen_model(model: type[BaseModel]) -> bool:
    return model.model_config.get("strict") is True and model.model_config.get("frozen") is True


@dataclass(frozen=True, slots=True, init=False)
class ReadToolGateway:
    """Immutable gateway that re-authorizes every invocation in enforced read-only mode."""

    registry: CapabilityRegistry = field(repr=False)
    handlers: tuple[ReadToolHandler, ...] = field(repr=False)
    audit_sink: ToolAuditSink = field(repr=False)
    _handlers_by_name: Mapping[str, ReadToolHandler] = field(repr=False)
    _descriptors_by_name: Mapping[str, ToolDescriptor] = field(repr=False)

    def __init__(
        self,
        registry: CapabilityRegistry,
        handlers: Iterable[ReadToolHandler],
        audit_sink: ToolAuditSink,
    ) -> None:
        if not isinstance(audit_sink, ToolAuditSink):
            raise TypeError("audit_sink must implement ToolAuditSink")
        descriptors = {
            tool.tool_name: tool for manifest in registry.manifests for tool in manifest.tools
        }
        handlers_by_name: dict[str, ReadToolHandler] = {}
        for handler in handlers:
            if not isinstance(handler, ReadToolHandler):
                raise TypeError("handlers must implement ReadToolHandler")
            if handler.tool_name in handlers_by_name:
                raise ValueError(f"duplicate handler: {handler.tool_name}")

            descriptor = descriptors.get(handler.tool_name)
            if descriptor is None:
                raise ValueError(f"handler has no registered descriptor: {handler.tool_name}")
            if descriptor.version != handler.version:
                raise ValueError(f"handler version mismatch: {handler.tool_name}")
            if descriptor.operation != "read":
                raise ValueError(f"command handlers are forbidden: {handler.tool_name}")
            if not _strict_frozen_model(handler.input_model):
                raise ValueError(
                    f"handler input model must be strict and frozen: {handler.tool_name}"
                )
            if handler.input_model.model_config.get("extra") != "forbid":
                raise ValueError(
                    f"handler input model must forbid extra fields: {handler.tool_name}"
                )
            if not _strict_frozen_model(handler.output_model):
                raise ValueError(
                    f"handler output model must be strict and frozen: {handler.tool_name}"
                )
            handlers_by_name[handler.tool_name] = handler

        ordered_handlers = tuple(handlers_by_name[name] for name in sorted(handlers_by_name))
        object.__setattr__(self, "registry", registry)
        object.__setattr__(self, "handlers", ordered_handlers)
        object.__setattr__(self, "audit_sink", audit_sink)
        object.__setattr__(self, "_handlers_by_name", MappingProxyType(handlers_by_name))
        object.__setattr__(self, "_descriptors_by_name", MappingProxyType(descriptors))

    def available_tools(self, context: TrustedRequestContext) -> tuple[ModelToolDescriptor, ...]:
        """Return only currently authorized model-facing tools with installed handlers."""

        decision = evaluate_capability_access(self.registry, context, read_only_mode=True)
        return tuple(
            tool
            for capability in decision.model_capabilities
            for tool in capability.tools
            if tool.tool_name in self._handlers_by_name
        )

    def public_input_schema(self, tool_name: str) -> Mapping[str, object]:
        """Return a copy of a registered handler's public input schema, never its type."""

        handler = self._handlers_by_name.get(tool_name)
        if handler is None:
            raise KeyError("tool has no installed public input schema")
        return MappingProxyType(handler.input_model.model_json_schema(mode="validation"))

    @staticmethod
    def _public_failure(
        *,
        invocation: ToolInvocation,
        error_code: ToolErrorCode,
    ) -> PublicToolFailure:
        return PublicToolFailure(
            tool_name=invocation.tool_name,
            version=invocation.version,
            safe_error_code=error_code,
            safe_message=SAFE_ERROR_MESSAGES[error_code],
        )

    async def _record_before_return(
        self,
        *,
        invocation: ToolInvocation,
        event: ToolAuditEvent,
        result: PublicToolResult,
    ) -> PublicToolResult:
        try:
            await self.audit_sink.record(event)
        except Exception:
            return self._public_failure(
                invocation=invocation,
                error_code=ToolErrorCode.AUDIT_UNAVAILABLE,
            )
        return result

    async def _failure(
        self,
        *,
        context: TrustedRequestContext,
        invocation: ToolInvocation,
        error_code: ToolErrorCode,
        internal_reason: str,
        descriptor: ToolDescriptor | None,
    ) -> PublicToolResult:
        event = create_tool_audit_event(
            context=context,
            tool_name=invocation.tool_name,
            tool_version=invocation.version,
            outcome="failure",
            internal_reason=internal_reason,
            descriptor=descriptor,
        )
        return await self._record_before_return(
            invocation=invocation,
            event=event,
            result=self._public_failure(invocation=invocation, error_code=error_code),
        )

    async def execute(
        self,
        context: TrustedRequestContext,
        invocation: ToolInvocation,
    ) -> PublicToolResult:
        """Re-authorize, validate, execute, verify, and audit one read invocation."""

        descriptor = self._descriptors_by_name.get(invocation.tool_name)
        if descriptor is not None and descriptor.operation == "command":
            return await self._failure(
                context=context,
                invocation=invocation,
                error_code=ToolErrorCode.READ_ONLY_VIOLATION,
                internal_reason="command_descriptor_rejected",
                descriptor=descriptor,
            )

        decision = evaluate_capability_access(self.registry, context, read_only_mode=True)
        authorized_names = {
            tool.tool_name
            for capability in decision.model_capabilities
            for tool in capability.tools
        }
        handler = self._handlers_by_name.get(invocation.tool_name)
        if (
            descriptor is None
            or handler is None
            or invocation.version != descriptor.version
            or invocation.tool_name not in authorized_names
        ):
            return await self._failure(
                context=context,
                invocation=invocation,
                error_code=ToolErrorCode.TOOL_UNAVAILABLE,
                internal_reason="tool_not_authorized_or_installed",
                descriptor=descriptor,
            )

        if _contains_reserved_argument(invocation.arguments):
            return await self._failure(
                context=context,
                invocation=invocation,
                error_code=ToolErrorCode.INVALID_TOOL_ARGUMENTS,
                internal_reason="reserved_context_argument_rejected",
                descriptor=descriptor,
            )

        try:
            arguments = handler.input_model.model_validate(dict(invocation.arguments), strict=True)
        except ValidationError:
            return await self._failure(
                context=context,
                invocation=invocation,
                error_code=ToolErrorCode.INVALID_TOOL_ARGUMENTS,
                internal_reason="input_validation_failed",
                descriptor=descriptor,
            )

        try:
            raw_result = await handler.execute(context, arguments)
        except Exception:
            return await self._failure(
                context=context,
                invocation=invocation,
                error_code=ToolErrorCode.TOOL_EXECUTION_FAILED,
                internal_reason="handler_execution_failed",
                descriptor=descriptor,
            )

        try:
            result = handler.output_model.model_validate(raw_result, strict=True)
        except ValidationError:
            return await self._failure(
                context=context,
                invocation=invocation,
                error_code=ToolErrorCode.INVALID_TOOL_OUTPUT,
                internal_reason="output_validation_failed",
                descriptor=descriptor,
            )

        result_envelope = PublicToolSuccess(
            tool_name=invocation.tool_name,
            version=invocation.version,
            result=result,
        )
        event = create_tool_audit_event(
            context=context,
            tool_name=invocation.tool_name,
            tool_version=invocation.version,
            outcome="success",
            internal_reason="execution_succeeded",
            descriptor=descriptor,
        )
        return await self._record_before_return(
            invocation=invocation,
            event=event,
            result=result_envelope,
        )
