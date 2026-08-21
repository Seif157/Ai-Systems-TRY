"""Redacted audit records for tool execution decisions."""

from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from erp_ai.capabilities import DataClassification, ToolDescriptor
from erp_ai.context import TrustedRequestContext


class ToolAuditEvent(BaseModel):
    """Immutable server-side audit metadata without raw arguments or outputs."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    request_id: str
    customer_environment_id: str
    user_id: str
    tool_name: str
    tool_version: str
    audit_action: str
    data_classification: DataClassification
    outcome: Literal["success", "failure"]
    internal_reason: str = Field(repr=False)
    purpose: str


@runtime_checkable
class ToolAuditSink(Protocol):
    """Mandatory server-side delivery boundary for tool audit events."""

    async def record(self, event: ToolAuditEvent) -> None: ...


def create_tool_audit_event(
    *,
    context: TrustedRequestContext,
    tool_name: str,
    tool_version: str,
    outcome: Literal["success", "failure"],
    internal_reason: str,
    descriptor: ToolDescriptor | None,
) -> ToolAuditEvent:
    """Create an explicit safe projection for a tool execution attempt."""

    return ToolAuditEvent(
        request_id=context.request_id,
        customer_environment_id=context.customer_environment_id,
        user_id=context.user_id,
        tool_name=tool_name,
        tool_version=tool_version,
        audit_action=(descriptor.audit_action if descriptor else "tool.invocation_denied"),
        data_classification=(
            descriptor.data_classification if descriptor else DataClassification.INTERNAL
        ),
        outcome=outcome,
        internal_reason=internal_reason,
        purpose=context.purpose,
    )
