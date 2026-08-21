"""Security-preserving Leave balance read handler."""

from dataclasses import dataclass

from pydantic import BaseModel

from erp_ai.capabilities.leave.models import (
    GetMyLeaveBalancesInput,
    GetMyLeaveBalancesOutput,
    LeaveBalanceItem,
)
from erp_ai.capabilities.leave.provider import LeaveReadProvider
from erp_ai.context import TrustedRequestContext


class _LeaveBalancesUnavailableError(RuntimeError):
    """Internal failure collapsed by the gateway to a safe execution error."""


@dataclass(frozen=True, slots=True)
class GetMyLeaveBalancesHandler:
    """Return authoritative ERP-calculated balances for the linked employee."""

    provider: LeaveReadProvider

    tool_name = "get_my_leave_balances"
    version = "1.0.0"
    input_model = GetMyLeaveBalancesInput
    output_model = GetMyLeaveBalancesOutput

    def __post_init__(self) -> None:
        if not isinstance(self.provider, LeaveReadProvider):
            raise TypeError("provider must implement LeaveReadProvider")

    async def execute(
        self,
        context: TrustedRequestContext,
        arguments: BaseModel,
    ) -> object:
        if not isinstance(arguments, GetMyLeaveBalancesInput):
            raise TypeError("unexpected leave balances input model")
        if context.employee_id is None:
            raise _LeaveBalancesUnavailableError("employee context is required")

        records = await self.provider.get_my_leave_balances(
            customer_environment_id=context.customer_environment_id,
            employee_id=context.employee_id,
            authorized_legal_entity_ids=context.legal_entity_ids,
        )

        seen: set[tuple[str, str, int]] = set()
        for record in records:
            if record.employee_id != context.employee_id:
                raise _LeaveBalancesUnavailableError("balance employee ownership mismatch")
            if record.legal_entity_id not in context.legal_entity_ids:
                raise _LeaveBalancesUnavailableError(
                    "balance legal entity outside authorized scope"
                )
            key = (record.legal_entity_id, record.leave_type_id, record.fiscal_year)
            if key in seen:
                raise _LeaveBalancesUnavailableError("duplicate balance record")
            seen.add(key)

        ordered_records = sorted(
            records,
            key=lambda record: (
                record.fiscal_year,
                record.leave_type_code,
                record.legal_entity_id,
                record.leave_type_id,
            ),
        )
        return GetMyLeaveBalancesOutput(
            balances=tuple(
                LeaveBalanceItem(
                    leave_type_code=record.leave_type_code,
                    leave_type_name=record.leave_type_name,
                    leave_type_name_local=record.leave_type_name_local,
                    fiscal_year=record.fiscal_year,
                    opening_days=record.opening_days,
                    accrued_days=record.accrued_days,
                    used_days=record.used_days,
                    pending_days=record.pending_days,
                    available_days=record.available_days,
                    calculated_at=record.calculated_at,
                    calculation_version=record.calculation_version,
                )
                for record in ordered_records
            )
        )
