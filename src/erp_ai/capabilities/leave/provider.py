"""Trusted ERP provider boundary for Leave read operations."""

from datetime import date
from typing import Protocol, runtime_checkable
from uuid import UUID

from erp_ai.capabilities.leave.models import (
    LeaveBalanceRecord,
    LeaveRequestDetailRecord,
    LeaveRequestPageRecord,
    LeaveRequestStatus,
)


@runtime_checkable
class LeaveReadProvider(Protocol):
    """Customer-scoped calculated-balance provider implemented outside this package."""

    async def get_my_leave_balances(
        self,
        *,
        customer_environment_id: str,
        employee_id: str,
        authorized_legal_entity_ids: tuple[str, ...],
    ) -> tuple[LeaveBalanceRecord, ...]: ...

    async def list_my_leave_requests(
        self,
        *,
        customer_environment_id: str,
        employee_id: str,
        authorized_legal_entity_ids: tuple[str, ...],
        statuses: tuple[LeaveRequestStatus, ...],
        start_from: date | None,
        start_to: date | None,
        limit: int,
        cursor: str | None,
    ) -> LeaveRequestPageRecord: ...

    async def get_my_leave_request(
        self,
        *,
        customer_environment_id: str,
        employee_id: str,
        authorized_legal_entity_ids: tuple[str, ...],
        request_id: UUID,
    ) -> LeaveRequestDetailRecord | None: ...
