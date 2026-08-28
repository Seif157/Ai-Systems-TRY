"""Trusted provider boundary for HR Core read operations."""

from typing import Protocol, runtime_checkable

from erp_ai.capabilities.hr_core.models import EmployeeProfileRecord
from erp_ai.context import TrustedRequestContext


@runtime_checkable
class HrCoreReadProvider(Protocol):
    """Customer-scoped ERP provider implemented outside this capability contract."""

    async def get_my_employee_profile(
        self,
        *,
        context: TrustedRequestContext,
    ) -> EmployeeProfileRecord | None: ...
