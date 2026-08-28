"""Capability-specific providers backed by one strict Laravel client."""

from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

from erp_ai.capabilities.hr_core.models import EmployeeProfileRecord
from erp_ai.capabilities.leave.models import (
    LeaveBalanceRecord,
    LeaveRequestDetailRecord,
    LeaveRequestPageRecord,
    LeaveRequestStatus,
)
from erp_ai.context import TrustedRequestContext

from .client import LaravelErpReadClient
from .contracts import BALANCES_PATH, PROFILE_PATH, REQUEST_DETAIL_PATH, REQUESTS_PATH
from .errors import LaravelErpReadUnavailable
from .models import (
    BalancesRequest,
    BalancesResponse,
    LaravelBinding,
    ProfileRequest,
    ProfileResponse,
    RequestDetailRequest,
    RequestDetailResponse,
    RequestListRequest,
    RequestListResponse,
)


def _binding(context: TrustedRequestContext, tool_name: str) -> dict[str, object]:
    if context.employee_id is None:
        raise LaravelErpReadUnavailable
    try:
        correlation = UUID(context.request_id)
    except (ValueError, TypeError):
        raise LaravelErpReadUnavailable from None
    return {
        "contract_version": "1.0.0",
        "correlation_request_id": correlation,
        "customer_environment_id": context.customer_environment_id,
        "user_id": context.user_id,
        "employee_id": context.employee_id,
        "authorization_snapshot_id": context.authorization_snapshot_id,
        "purpose": context.purpose,
        "legal_entity_ids": context.legal_entity_ids,
        "tool_name": tool_name,
        "tool_version": "1.0.0",
    }


def _same_binding(expected: LaravelBinding, actual: LaravelBinding) -> None:
    fields = tuple(LaravelBinding.model_fields)
    if any(getattr(expected, name) != getattr(actual, name) for name in fields):
        raise LaravelErpReadUnavailable


@dataclass(frozen=True, slots=True)
class LaravelHrCoreReadProvider:
    uses_trusted_context = True
    client: LaravelErpReadClient = field(repr=False)

    async def get_my_employee_profile(
        self, *, context: TrustedRequestContext
    ) -> EmployeeProfileRecord | None:
        request = ProfileRequest.model_validate(
            _binding(context, "get_my_employee_profile"), strict=True
        )
        result = await self.client.post_model(PROFILE_PATH, request, ProfileResponse)
        if not isinstance(result, ProfileResponse):  # pragma: no cover - client binds model type
            raise LaravelErpReadUnavailable
        _same_binding(request, result)
        if result.profile is not None and (
            result.profile.employee_id != context.employee_id
            or result.profile.legal_entity_id not in context.legal_entity_ids
        ):
            raise LaravelErpReadUnavailable
        return result.profile


@dataclass(frozen=True, slots=True)
class LaravelLeaveReadProvider:
    uses_trusted_context = True
    client: LaravelErpReadClient = field(repr=False)

    async def get_my_leave_balances(
        self, *, context: TrustedRequestContext
    ) -> tuple[LeaveBalanceRecord, ...]:
        request = BalancesRequest.model_validate(
            _binding(context, "get_my_leave_balances"), strict=True
        )
        result = await self.client.post_model(BALANCES_PATH, request, BalancesResponse)
        if not isinstance(result, BalancesResponse):  # pragma: no cover - client binds model type
            raise LaravelErpReadUnavailable
        _same_binding(request, result)
        if any(
            item.employee_id != context.employee_id
            or item.legal_entity_id not in context.legal_entity_ids
            for item in result.balances
        ):
            raise LaravelErpReadUnavailable
        return result.balances

    async def list_my_leave_requests(
        self,
        *,
        context: TrustedRequestContext,
        statuses: tuple[LeaveRequestStatus, ...],
        start_from: date | None,
        start_to: date | None,
        limit: int,
        cursor: str | None,
    ) -> LeaveRequestPageRecord:
        if statuses or start_from is not None or start_to is not None:
            raise LaravelErpReadUnavailable
        request = RequestListRequest.model_validate(
            {**_binding(context, "list_my_leave_requests"), "page_size": limit, "cursor": cursor},
            strict=True,
        )
        result = await self.client.post_model(REQUESTS_PATH, request, RequestListResponse)
        if not isinstance(
            result, RequestListResponse
        ):  # pragma: no cover - client binds model type
            raise LaravelErpReadUnavailable
        _same_binding(request, result)
        if len(result.requests.items) > limit or any(
            str(item.employee_id) != context.employee_id
            or str(item.legal_entity_id) not in context.legal_entity_ids
            for item in result.requests.items
        ):
            raise LaravelErpReadUnavailable
        return result.requests

    async def get_my_leave_request(
        self, *, context: TrustedRequestContext, request_id: UUID
    ) -> LeaveRequestDetailRecord | None:
        request = RequestDetailRequest.model_validate(
            {**_binding(context, "get_my_leave_request"), "leave_request_id": request_id},
            strict=True,
        )
        result = await self.client.post_model(REQUEST_DETAIL_PATH, request, RequestDetailResponse)
        if not isinstance(
            result, RequestDetailResponse
        ):  # pragma: no cover - client binds model type
            raise LaravelErpReadUnavailable
        _same_binding(request, result)
        record = result.leave_request
        if record is not None and (
            record.request_id != request_id
            or record.customer_environment_id != context.customer_environment_id
            or str(record.employee_id) != context.employee_id
            or str(record.legal_entity_id) not in context.legal_entity_ids
        ):
            raise LaravelErpReadUnavailable
        return record
