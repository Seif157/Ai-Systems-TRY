"""Security-preserving Leave balance read handler."""

from dataclasses import dataclass

from pydantic import BaseModel

from erp_ai.capabilities.leave.models import (
    LEAVE_REQUEST_ENTITY_TYPE,
    GetMyLeaveBalancesInput,
    GetMyLeaveBalancesOutput,
    GetMyLeaveRequestInput,
    GetMyLeaveRequestOutput,
    LeaveBalanceItem,
    LeaveRequestHistoryRecord,
    LeaveRequestStatusTransition,
    LeaveRequestSummary,
    LeaveRequestSummaryRecord,
    ListMyLeaveRequestsInput,
    ListMyLeaveRequestsOutput,
)
from erp_ai.capabilities.leave.provider import LeaveReadProvider
from erp_ai.context import TrustedRequestContext


class _LeaveBalancesUnavailableError(RuntimeError):
    """Internal failure collapsed by the gateway to a safe execution error."""


class _LeaveRequestsUnavailableError(RuntimeError):
    """Internal list failure collapsed by the gateway to a safe execution error."""


class _LeaveRequestDetailUnavailableError(RuntimeError):
    """Internal detail failure collapsed to the same safe public failure."""


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


@dataclass(frozen=True, slots=True)
class ListMyLeaveRequestsHandler:
    """List safe request summaries owned by the linked employee."""

    provider: LeaveReadProvider

    tool_name = "list_my_leave_requests"
    version = "1.0.0"
    input_model = ListMyLeaveRequestsInput
    output_model = ListMyLeaveRequestsOutput

    def __post_init__(self) -> None:
        if not isinstance(self.provider, LeaveReadProvider):
            raise TypeError("provider must implement LeaveReadProvider")

    async def execute(
        self,
        context: TrustedRequestContext,
        arguments: BaseModel,
    ) -> object:
        if not isinstance(arguments, ListMyLeaveRequestsInput):
            raise TypeError("unexpected leave request list input model")
        if context.employee_id is None:
            raise _LeaveRequestsUnavailableError("employee context is required")

        page = await self.provider.list_my_leave_requests(
            customer_environment_id=context.customer_environment_id,
            employee_id=context.employee_id,
            authorized_legal_entity_ids=context.legal_entity_ids,
            statuses=arguments.statuses,
            start_from=arguments.start_from,
            start_to=arguments.start_to,
            limit=arguments.limit,
            cursor=arguments.cursor,
            authorization_snapshot_id=context.authorization_snapshot_id,
        )

        if len(page.items) > arguments.limit:
            raise _LeaveRequestsUnavailableError("provider page exceeds requested limit")
        if not page.items and page.next_cursor is not None:
            raise _LeaveRequestsUnavailableError("empty provider page has continuation cursor")

        seen: set[str] = set()
        previous: LeaveRequestSummaryRecord | None = None
        for record in page.items:
            if str(record.employee_id) != context.employee_id:
                raise _LeaveRequestsUnavailableError("request employee ownership mismatch")
            if str(record.legal_entity_id) not in context.legal_entity_ids:
                raise _LeaveRequestsUnavailableError(
                    "request legal entity outside authorized scope"
                )
            request_id = str(record.request_id)
            if request_id in seen:
                raise _LeaveRequestsUnavailableError("duplicate leave request")
            seen.add(request_id)
            if previous is not None:
                if previous.submitted_at < record.submitted_at:
                    raise _LeaveRequestsUnavailableError("provider page ordering violation")
                if (
                    previous.submitted_at == record.submitted_at
                    and previous.request_id.hex > record.request_id.hex
                ):
                    raise _LeaveRequestsUnavailableError("provider page ordering violation")
            previous = record

        return ListMyLeaveRequestsOutput(
            requests=tuple(
                LeaveRequestSummary(
                    request_id=record.request_id,
                    leave_type_code=record.leave_type_code,
                    leave_type_name=record.leave_type_name,
                    leave_type_name_local=record.leave_type_name_local,
                    start_date=record.start_date,
                    end_date=record.end_date,
                    working_days=record.working_days,
                    is_half_day=record.is_half_day,
                    half_day_period=record.half_day_period,
                    status=record.status,
                    submitted_at=record.submitted_at,
                    updated_at=record.updated_at,
                    working_days_calculation_version=(record.working_days_calculation_version),
                )
                for record in page.items
            ),
            next_cursor=page.next_cursor,
        )


@dataclass(frozen=True, slots=True)
class GetMyLeaveRequestHandler:
    """Return one owned request with a validated safe status timeline."""

    provider: LeaveReadProvider

    tool_name = "get_my_leave_request"
    version = "1.0.0"
    input_model = GetMyLeaveRequestInput
    output_model = GetMyLeaveRequestOutput

    def __post_init__(self) -> None:
        if not isinstance(self.provider, LeaveReadProvider):
            raise TypeError("provider must implement LeaveReadProvider")

    async def execute(
        self,
        context: TrustedRequestContext,
        arguments: BaseModel,
    ) -> object:
        if not isinstance(arguments, GetMyLeaveRequestInput):
            raise TypeError("unexpected leave request detail input model")
        if context.employee_id is None:
            raise _LeaveRequestDetailUnavailableError("employee context is required")

        record = await self.provider.get_my_leave_request(
            customer_environment_id=context.customer_environment_id,
            employee_id=context.employee_id,
            authorized_legal_entity_ids=context.legal_entity_ids,
            request_id=arguments.request_id,
        )
        if record is None:
            raise _LeaveRequestDetailUnavailableError("leave request unavailable")
        if record.request_id != arguments.request_id:
            raise _LeaveRequestDetailUnavailableError("leave request selector mismatch")
        if record.customer_environment_id != context.customer_environment_id:
            raise _LeaveRequestDetailUnavailableError("leave request customer mismatch")
        if str(record.employee_id) != context.employee_id:
            raise _LeaveRequestDetailUnavailableError("leave request employee mismatch")
        if str(record.legal_entity_id) not in context.legal_entity_ids:
            raise _LeaveRequestDetailUnavailableError(
                "leave request legal entity outside authorized scope"
            )

        seen_history_ids: set[str] = set()
        previous: LeaveRequestHistoryRecord | None = None
        for transition in record.status_history:
            history_id = str(transition.history_id)
            if history_id in seen_history_ids:
                raise _LeaveRequestDetailUnavailableError("duplicate status history")
            seen_history_ids.add(history_id)
            if transition.entity_type != LEAVE_REQUEST_ENTITY_TYPE:
                raise _LeaveRequestDetailUnavailableError("wrong history entity type")
            if transition.entity_id != record.request_id:
                raise _LeaveRequestDetailUnavailableError("wrong history entity")
            if previous is not None:
                if previous.changed_at > transition.changed_at:
                    raise _LeaveRequestDetailUnavailableError("history ordering violation")
                if (
                    previous.changed_at == transition.changed_at
                    and previous.history_id.hex > transition.history_id.hex
                ):
                    raise _LeaveRequestDetailUnavailableError("history ordering violation")
                if transition.from_status != previous.to_status:
                    raise _LeaveRequestDetailUnavailableError("broken history status chain")
            previous = transition

        if previous is not None and previous.to_status != record.status:
            raise _LeaveRequestDetailUnavailableError("history final status mismatch")

        return GetMyLeaveRequestOutput(
            request_id=record.request_id,
            leave_type_code=record.leave_type_code,
            leave_type_name=record.leave_type_name,
            leave_type_name_local=record.leave_type_name_local,
            start_date=record.start_date,
            end_date=record.end_date,
            working_days=record.working_days,
            is_half_day=record.is_half_day,
            half_day_period=record.half_day_period,
            status=record.status,
            submitted_at=record.submitted_at,
            updated_at=record.updated_at,
            status_timeline=tuple(
                LeaveRequestStatusTransition(
                    from_status=transition.from_status,
                    to_status=transition.to_status,
                    changed_at=transition.changed_at,
                    reason_code=transition.reason_code,
                )
                for transition in record.status_history
            ),
        )
