"""Strict flat wire envelopes for Laravel ERP reads."""

from typing import Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from erp_ai.capabilities.hr_core.models import EmployeeProfileRecord
from erp_ai.capabilities.leave.models import (
    LeaveBalanceRecord,
    LeaveRequestDetailRecord,
    LeaveRequestPageRecord,
    OpaqueCursor,
)
from erp_ai.context.models import Code, Identifier


class LaravelBinding(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )
    contract_version: Literal["1.0.0"]
    correlation_request_id: UUID = Field(repr=False)
    customer_environment_id: Identifier = Field(repr=False)
    user_id: Identifier = Field(repr=False)
    employee_id: Identifier = Field(repr=False)
    authorization_snapshot_id: Identifier = Field(repr=False)
    purpose: Code = Field(repr=False)
    legal_entity_ids: tuple[Identifier, ...] = Field(repr=False, min_length=1, max_length=256)
    tool_name: Code
    tool_version: Literal["1.0.0"]

    @field_validator("legal_entity_ids", mode="before")
    @classmethod
    def immutable_unique_scope(cls, value: Any) -> Any:
        value = tuple(value) if isinstance(value, list) else value
        if isinstance(value, tuple) and len(value) != len(set(value)):
            raise ValueError("duplicate legal entity")
        return value

    @field_serializer("correlation_request_id")
    def serialize_correlation(self, value: UUID) -> str:
        return str(value)


class ProfileRequest(LaravelBinding):
    pass


class BalancesRequest(LaravelBinding):
    pass


class RequestListRequest(LaravelBinding):
    page_size: int = Field(strict=True, ge=1, le=100)
    cursor: OpaqueCursor | None


class RequestDetailRequest(LaravelBinding):
    leave_request_id: UUID = Field(repr=False)

    @field_serializer("leave_request_id")
    def serialize_selector(self, value: UUID) -> str:
        return str(value)


class ProfileResponse(LaravelBinding):
    outcome: Literal["found", "not_found"]
    profile: EmployeeProfileRecord | None = Field(repr=False)

    @model_validator(mode="after")
    def consistent(self) -> "ProfileResponse":
        if (self.outcome == "found") != (self.profile is not None):
            raise ValueError("profile outcome mismatch")
        return self


class BalancesResponse(LaravelBinding):
    outcome: Literal["found"]
    balances: tuple[LeaveBalanceRecord, ...] = Field(repr=False)

    @field_validator("balances", mode="before")
    @classmethod
    def immutable_balances(cls, value: Any) -> Any:
        return tuple(value) if isinstance(value, list) else value


class RequestListResponse(LaravelBinding):
    outcome: Literal["found"]
    requests: LeaveRequestPageRecord = Field(repr=False)


class RequestDetailResponse(LaravelBinding):
    outcome: Literal["found", "not_found"]
    leave_request: LeaveRequestDetailRecord | None = Field(repr=False)

    @model_validator(mode="after")
    def consistent(self) -> "RequestDetailResponse":
        if (self.outcome == "found") != (self.leave_request is not None):
            raise ValueError("detail outcome mismatch")
        return self
