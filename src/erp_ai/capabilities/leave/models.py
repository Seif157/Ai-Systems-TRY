"""Provider and safe public models for employee leave balances."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
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


class GetMyLeaveBalancesInput(BaseModel):
    """The current-balance tool accepts no model-selected arguments."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


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
