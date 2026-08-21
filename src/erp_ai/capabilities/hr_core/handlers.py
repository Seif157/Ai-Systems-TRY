"""Security-preserving read handlers for HR Core."""

from dataclasses import dataclass

from pydantic import BaseModel

from erp_ai.capabilities.hr_core.models import (
    GetMyEmployeeProfileInput,
    GetMyEmployeeProfileOutput,
)
from erp_ai.capabilities.hr_core.provider import HrCoreReadProvider
from erp_ai.context import TrustedRequestContext


class _ProfileUnavailableError(RuntimeError):
    """Internal failure collapsed by the gateway to a safe execution error."""


@dataclass(frozen=True, slots=True)
class GetMyEmployeeProfileHandler:
    """Read the authenticated employee's explicitly allowlisted profile fields."""

    provider: HrCoreReadProvider

    tool_name = "get_my_employee_profile"
    version = "1.0.0"
    input_model = GetMyEmployeeProfileInput
    output_model = GetMyEmployeeProfileOutput

    def __post_init__(self) -> None:
        if not isinstance(self.provider, HrCoreReadProvider):
            raise TypeError("provider must implement HrCoreReadProvider")

    async def execute(
        self,
        context: TrustedRequestContext,
        arguments: BaseModel,
    ) -> object:
        if not isinstance(arguments, GetMyEmployeeProfileInput):
            raise TypeError("unexpected profile input model")
        if context.employee_id is None:
            raise _ProfileUnavailableError("employee context is required")

        record = await self.provider.get_my_employee_profile(
            customer_environment_id=context.customer_environment_id,
            employee_id=context.employee_id,
        )
        if record is None:
            raise _ProfileUnavailableError("profile record unavailable")
        if record.employee_id != context.employee_id:
            raise _ProfileUnavailableError("profile employee ownership mismatch")
        if record.legal_entity_id not in context.legal_entity_ids:
            raise _ProfileUnavailableError("profile legal entity outside authorized scope")

        return GetMyEmployeeProfileOutput(
            employee_number=record.employee_number,
            display_name=record.display_name,
            work_email=record.work_email,
            job_title=record.job_title,
            department_name=record.department_name,
            branch_name=record.branch_name,
            legal_entity_name=record.legal_entity_name,
            employment_status=record.employment_status,
            hire_date=record.hire_date,
            manager_display_name=record.manager_display_name,
            freshness_at=record.freshness_at,
        )
