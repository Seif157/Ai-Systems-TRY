"""Provider and safe public models for Leave read tools."""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from erp_ai.context.models import Identifier


def _strip_text(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


LeaveTypeCode = Annotated[
    str,
    BeforeValidator(_strip_text),
    StringConstraints(strict=True, min_length=1, max_length=20),
]
LeaveTypeName = Annotated[
    str,
    BeforeValidator(_strip_text),
    StringConstraints(strict=True, min_length=1, max_length=100),
]
NonEmptyMetadata = Annotated[
    str,
    BeforeValidator(_strip_text),
    StringConstraints(strict=True, min_length=1),
]
NonnegativeDays = Annotated[
    Decimal,
    Field(strict=True, ge=Decimal("0"), max_digits=7, decimal_places=2),
]
AvailableDays = Annotated[
    Decimal,
    Field(strict=True, max_digits=7, decimal_places=2),
]
FiscalYear = Annotated[int, Field(strict=True, ge=1000, le=9999)]
WorkingDays = Annotated[
    Decimal,
    Field(strict=True, gt=Decimal("0"), max_digits=5, decimal_places=2),
]


class LeaveRequestStatus(str, Enum):
    """Canonical leave request states from the HR schema."""

    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    RETURNED = "returned"
    CANCELLED = "cancelled"


class HalfDayPeriod(str, Enum):
    """Canonical half-day periods from the HR schema."""

    FIRST_HALF = "first_half"
    SECOND_HALF = "second_half"


def _validate_opaque_cursor(value: Any) -> Any:
    if isinstance(value, str) and not value.strip():
        raise ValueError("cursor must not be blank")
    return value


OpaqueCursor = Annotated[
    str,
    BeforeValidator(_validate_opaque_cursor),
    StringConstraints(strict=True, max_length=512),
]


class GetMyLeaveBalancesInput(BaseModel):
    """The current-balance tool accepts no model-selected arguments."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ListMyLeaveRequestsInput(BaseModel):
    """Validated public filters for the linked employee's leave requests."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    statuses: tuple[LeaveRequestStatus, ...] = ()
    start_from: date | None = None
    start_to: date | None = None
    limit: int = Field(default=20, strict=True, ge=1, le=50)
    cursor: OpaqueCursor | None = None

    @field_validator("statuses", mode="before")
    @classmethod
    def validate_and_order_statuses(cls, value: Any) -> Any:
        if not isinstance(value, (list, tuple)):
            return value
        normalized = tuple(
            LeaveRequestStatus(item) if isinstance(item, str) else item for item in value
        )
        if len(set(normalized)) != len(normalized):
            raise ValueError("duplicate statuses are not allowed")
        return tuple(sorted(normalized, key=lambda status: status.value))

    @field_validator("start_from", "start_to", mode="before")
    @classmethod
    def parse_iso_dates(cls, value: Any) -> Any:
        if isinstance(value, str):
            try:
                return date.fromisoformat(value)
            except ValueError as error:
                raise ValueError("date filters must use ISO YYYY-MM-DD format") from error
        return value

    @model_validator(mode="after")
    def validate_date_range(self) -> "ListMyLeaveRequestsInput":
        if self.start_from is None or self.start_to is None:
            return self
        if self.start_from > self.start_to:
            raise ValueError("start_from must not exceed start_to")
        if (self.start_to - self.start_from).days > 366:
            raise ValueError("explicit date range must not exceed 366 days")
        return self


class LeaveBalanceRecord(BaseModel):
    """Authoritative calculated balance cache record returned by the ERP provider."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    employee_id: Identifier
    legal_entity_id: Identifier
    leave_type_id: Identifier
    leave_type_code: LeaveTypeCode
    leave_type_name: LeaveTypeName
    leave_type_name_local: LeaveTypeName
    fiscal_year: FiscalYear
    opening_days: NonnegativeDays
    accrued_days: NonnegativeDays
    used_days: NonnegativeDays
    pending_days: NonnegativeDays
    available_days: AvailableDays
    calculated_at: datetime
    source_watermark: NonEmptyMetadata
    calculation_version: NonEmptyMetadata

    @field_validator("calculated_at")
    @classmethod
    def validate_calculated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("calculated_at must be timezone-aware")
        return value


class LeaveBalanceItem(BaseModel):
    """Explicit safe balance projection for public/model consumption."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    leave_type_code: LeaveTypeCode
    leave_type_name: LeaveTypeName
    leave_type_name_local: LeaveTypeName
    fiscal_year: FiscalYear
    opening_days: NonnegativeDays
    accrued_days: NonnegativeDays
    used_days: NonnegativeDays
    pending_days: NonnegativeDays
    available_days: AvailableDays
    calculated_at: datetime
    calculation_version: NonEmptyMetadata

    @field_validator("calculated_at")
    @classmethod
    def validate_calculated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("calculated_at must be timezone-aware")
        return value


class GetMyLeaveBalancesOutput(BaseModel):
    """Immutable, deterministic collection of safe leave balance items."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    balances: tuple[LeaveBalanceItem, ...]

    @field_validator("balances", mode="before")
    @classmethod
    def normalize_balances(cls, value: Any) -> Any:
        if isinstance(value, list):
            return tuple(value)
        return value

    @field_validator("balances")
    @classmethod
    def order_balances(cls, value: tuple[LeaveBalanceItem, ...]) -> tuple[LeaveBalanceItem, ...]:
        return tuple(
            sorted(
                value,
                key=lambda item: (
                    item.fiscal_year,
                    item.leave_type_code,
                    item.leave_type_name,
                    item.leave_type_name_local,
                ),
            )
        )


class LeaveRequestSummaryRecord(BaseModel):
    """Internal ERP record used for request ownership and scope verification."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    request_id: UUID
    employee_id: UUID
    legal_entity_id: UUID
    leave_type_id: UUID
    leave_type_code: LeaveTypeCode
    leave_type_name: LeaveTypeName
    leave_type_name_local: LeaveTypeName
    start_date: date
    end_date: date
    working_days: WorkingDays
    is_half_day: bool
    half_day_period: HalfDayPeriod | None
    status: LeaveRequestStatus
    submitted_at: datetime
    updated_at: datetime | None = None
    working_days_calculation_version: NonEmptyMetadata

    @field_validator("half_day_period", mode="before")
    @classmethod
    def validate_half_day_period(cls, value: Any) -> Any:
        return HalfDayPeriod(value) if isinstance(value, str) else value

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, value: Any) -> Any:
        return LeaveRequestStatus(value) if isinstance(value, str) else value

    @field_validator("submitted_at", "updated_at")
    @classmethod
    def validate_timestamps(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("request timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_dates_and_half_day(self) -> "LeaveRequestSummaryRecord":
        if self.end_date < self.start_date:
            raise ValueError("end_date must not precede start_date")
        if self.is_half_day:
            if self.start_date != self.end_date:
                raise ValueError("half-day request must cover one date")
            if self.half_day_period is None:
                raise ValueError("half_day_period is required for a half-day request")
            if self.working_days != Decimal("0.50"):
                raise ValueError("half-day request must have 0.50 working days")
        elif self.half_day_period is not None:
            raise ValueError("half_day_period must be absent for a full-day request")
        return self


class LeaveRequestPageRecord(BaseModel):
    """Internal provider page with an opaque continuation cursor."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    items: tuple[LeaveRequestSummaryRecord, ...]
    next_cursor: OpaqueCursor | None = None

    @field_validator("items", mode="before")
    @classmethod
    def normalize_items(cls, value: Any) -> Any:
        if isinstance(value, list):
            return tuple(value)
        return value


class LeaveRequestSummary(BaseModel):
    """Explicit safe projection of one linked employee leave request."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    request_id: UUID
    leave_type_code: LeaveTypeCode
    leave_type_name: LeaveTypeName
    leave_type_name_local: LeaveTypeName
    start_date: date
    end_date: date
    working_days: WorkingDays
    is_half_day: bool
    half_day_period: HalfDayPeriod | None
    status: LeaveRequestStatus
    submitted_at: datetime
    updated_at: datetime | None
    working_days_calculation_version: NonEmptyMetadata


class ListMyLeaveRequestsOutput(BaseModel):
    """Immutable safe request page preserving canonical provider order."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    requests: tuple[LeaveRequestSummary, ...]
    next_cursor: OpaqueCursor | None = None

    @field_validator("requests", mode="before")
    @classmethod
    def normalize_requests(cls, value: Any) -> Any:
        if isinstance(value, list):
            return tuple(value)
        return value
