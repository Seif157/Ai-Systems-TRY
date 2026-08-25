"""Trusted provider boundary for HR Core read operations."""

from typing import Protocol, runtime_checkable

from erp_ai.capabilities.hr_core.models import EmployeeProfileRecord


@runtime_checkable
class HrCoreReadProvider(Protocol):
    """Customer-scoped ERP provider implemented outside this capability contract."""

    async def get_my_employee_profile(
        self,
        *,
        customer_environment_id: str,
        employee_id: str,
        authorized_legal_entity_ids: tuple[str, ...],
    ) -> EmployeeProfileRecord | None: ...
