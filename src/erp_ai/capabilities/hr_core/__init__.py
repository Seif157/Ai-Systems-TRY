"""HR Core production read capability contracts."""

from erp_ai.capabilities.hr_core.handlers import GetMyEmployeeProfileHandler
from erp_ai.capabilities.hr_core.manifest import HR_CORE_MANIFEST
from erp_ai.capabilities.hr_core.models import (
    EmployeeProfileRecord,
    EmploymentStatus,
    GetMyEmployeeProfileInput,
    GetMyEmployeeProfileOutput,
)
from erp_ai.capabilities.hr_core.provider import HrCoreReadProvider

__all__ = [
    "HR_CORE_MANIFEST",
    "EmployeeProfileRecord",
    "EmploymentStatus",
    "GetMyEmployeeProfileHandler",
    "GetMyEmployeeProfileInput",
    "GetMyEmployeeProfileOutput",
    "HrCoreReadProvider",
]
