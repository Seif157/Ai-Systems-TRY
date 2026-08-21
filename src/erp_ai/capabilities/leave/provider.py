"""Trusted ERP provider boundary for Leave read operations."""

from typing import Protocol, runtime_checkable

from erp_ai.capabilities.leave.models import LeaveBalanceRecord


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
