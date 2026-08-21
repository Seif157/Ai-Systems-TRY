"""Explicit, redacted audit projection for trusted request context."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from erp_ai.context.models import TrustedRequestContext


class ContextAuditRecord(BaseModel):
    """Immutable context metadata safe for structured audit events."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    context_version: Literal[1]
    request_id: str
    customer_environment_id: str
    user_id: str
    purpose: str
    locale: str
    timezone: str
    issued_at: datetime
    authorization_snapshot_id: str
    employee_linked: bool
    role_count: int
    permission_count: int
    legal_entity_count: int
    enabled_module_count: int


def to_audit_record(context: TrustedRequestContext) -> ContextAuditRecord:
    """Return the approved audit projection; never log the complete context instead."""

    return ContextAuditRecord(
        context_version=context.context_version,
        request_id=context.request_id,
        customer_environment_id=context.customer_environment_id,
        user_id=context.user_id,
        purpose=context.purpose,
        locale=context.locale,
        timezone=context.timezone,
        issued_at=context.issued_at,
        authorization_snapshot_id=context.authorization_snapshot_id,
        employee_linked=context.employee_id is not None,
        role_count=len(context.roles),
        permission_count=len(context.permission_codes),
        legal_entity_count=len(context.legal_entity_ids),
        enabled_module_count=len(context.enabled_modules),
    )
