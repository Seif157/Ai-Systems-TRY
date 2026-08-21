"""Typed provider and public models for the HR Core self-profile tool."""

from datetime import date, datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    StringConstraints,
    field_validator,
)

from erp_ai.context.models import Identifier


def _strip_text(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


DisplayName = Annotated[
    str,
    BeforeValidator(_strip_text),
    StringConstraints(strict=True, min_length=1, max_length=200),
]
OptionalDisplayText = Annotated[
    str,
    BeforeValidator(_strip_text),
    StringConstraints(strict=True, min_length=1, max_length=320),
]
EmployeeNumber = Annotated[
    str,
    BeforeValidator(_strip_text),
    StringConstraints(strict=True, min_length=1, max_length=20),
]
WorkEmail = Annotated[
    str,
    BeforeValidator(_strip_text),
    StringConstraints(strict=True, min_length=1, max_length=200),
]


class EmploymentStatus(str, Enum):
    """Canonical values enforced by the HR employees schema."""

    ACTIVE = "active"
    PROBATION = "probation"
    ON_LEAVE = "on_leave"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"
    RESIGNED = "resigned"
    RETIRED = "retired"
    INACTIVE = "inactive"


class GetMyEmployeeProfileInput(BaseModel):
    """The self-profile tool accepts no model-selected arguments."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class EmployeeProfileRecord(BaseModel):
    """Internal provider record used for ownership and scope verification."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    employee_id: Identifier
    legal_entity_id: Identifier
    employee_number: EmployeeNumber
    display_name: DisplayName
    work_email: WorkEmail
    job_title: OptionalDisplayText | None = None
    department_name: OptionalDisplayText | None = None
    branch_name: OptionalDisplayText | None = None
    legal_entity_name: OptionalDisplayText | None = None
    employment_status: EmploymentStatus
    hire_date: date
    manager_display_name: OptionalDisplayText | None = None
    freshness_at: datetime

    @field_validator("employment_status", mode="before")
    @classmethod
    def validate_employment_status(cls, value: Any) -> Any:
        return EmploymentStatus(value) if isinstance(value, str) else value

    @field_validator("freshness_at")
    @classmethod
    def validate_freshness_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("freshness_at must be timezone-aware")
        return value


class GetMyEmployeeProfileOutput(BaseModel):
    """Explicit safe subset returned for an authorized self-profile request."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    employee_number: EmployeeNumber
    display_name: DisplayName
    work_email: WorkEmail
    job_title: OptionalDisplayText | None = None
    department_name: OptionalDisplayText | None = None
    branch_name: OptionalDisplayText | None = None
    legal_entity_name: OptionalDisplayText | None = None
    employment_status: EmploymentStatus
    hire_date: date
    manager_display_name: OptionalDisplayText | None = None
    freshness_at: datetime

    @field_validator("employment_status", mode="before")
    @classmethod
    def validate_employment_status(cls, value: Any) -> Any:
        return EmploymentStatus(value) if isinstance(value, str) else value

    @field_validator("freshness_at")
    @classmethod
    def validate_freshness_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("freshness_at must be timezone-aware")
        return value
