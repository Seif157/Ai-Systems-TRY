"""Mandatory redacted audit boundary for one complete agent chat."""

from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from erp_ai.context import TrustedRequestContext


class AgentAuditEvent(BaseModel):
    """Approved identity, governance, and coarse outcome metadata only."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    request_id: str
    customer_environment_id: str
    user_id: str
    purpose: str
    action: Literal["agent.chat"] = "agent.chat"
    outcome: Literal["success", "failure"]
    internal_reason: str = Field(repr=False)


@runtime_checkable
class AgentAuditSink(Protocol):
    """Required delivery sink; no production default or no-op exists."""

    async def record(self, event: AgentAuditEvent) -> None: ...


def create_agent_audit_event(
    context: TrustedRequestContext,
    *,
    outcome: Literal["success", "failure"],
    internal_reason: str,
) -> AgentAuditEvent:
    return AgentAuditEvent(
        request_id=context.request_id,
        customer_environment_id=context.customer_environment_id,
        user_id=context.user_id,
        purpose=context.purpose,
        outcome=outcome,
        internal_reason=internal_reason,
    )
