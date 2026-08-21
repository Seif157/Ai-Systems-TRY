import asyncio
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import BaseModel, ConfigDict

from erp_ai.capabilities.hr_core import (
    EmployeeProfileRecord,
    GetMyEmployeeProfileHandler,
    GetMyEmployeeProfileInput,
    GetMyEmployeeProfileOutput,
)
from erp_ai.context import TrustedRequestContext


def profile_record(**overrides: object) -> EmployeeProfileRecord:
    payload: dict[str, object] = {
        "employee_id": "employee_1",
        "legal_entity_id": "entity_1",
        "employee_number": "EMP-001",
        "display_name": "Synthetic Employee",
        "work_email": "employee@example.test",
        "job_title": "Engineer",
        "department_name": "Engineering",
        "branch_name": "Cairo",
        "legal_entity_name": "Example Egypt",
        "employment_status": "active",
        "hire_date": date(2024, 1, 15),
        "manager_display_name": "Synthetic Manager",
        "freshness_at": datetime(2026, 8, 22, 9, 0, tzinfo=ZoneInfo("Africa/Cairo")),
    }
    payload.update(overrides)
    return EmployeeProfileRecord.model_validate(payload, strict=True)


def trusted_context(*, employee_id: str | None = "employee_1") -> TrustedRequestContext:
    return TrustedRequestContext(
        context_version=1,
        request_id="req_a",
        customer_environment_id="customer_a",
        user_id="user_1",
        employee_id=employee_id,
        roles=("employee",),
        permission_codes=("hr.profile.read_self",),
        legal_entity_ids=("entity_1",),
        enabled_modules=("hr_core",),
        locale="en",
        timezone="Africa/Cairo",
        purpose="employee_self_service",
        issued_at=datetime(2026, 8, 22, 9, 0, tzinfo=ZoneInfo("Africa/Cairo")),
        authorization_snapshot_id="snapshot_a",
    )


class FakeHrCoreProvider:
    def __init__(self, record: EmployeeProfileRecord | None, *, raises: bool = False) -> None:
        self.record = record
        self.raises = raises
        self.calls: list[tuple[str, str]] = []

    async def get_my_employee_profile(
        self, *, customer_environment_id: str, employee_id: str
    ) -> EmployeeProfileRecord | None:
        self.calls.append((customer_environment_id, employee_id))
        if self.raises:
            raise RuntimeError("synthetic provider failure")
        return self.record


def run(handler: GetMyEmployeeProfileHandler, context: TrustedRequestContext) -> object:
    return asyncio.run(handler.execute(context, GetMyEmployeeProfileInput()))


def test_handler_calls_provider_with_trusted_identifiers_and_maps_safe_output() -> None:
    provider = FakeHrCoreProvider(profile_record())
    handler = GetMyEmployeeProfileHandler(provider)

    result = run(handler, trusted_context())

    assert isinstance(result, GetMyEmployeeProfileOutput)
    assert provider.calls == [("customer_a", "employee_1")]
    assert result.display_name == "Synthetic Employee"
    assert "employee_id" not in result.model_dump()
    assert "legal_entity_id" not in result.model_dump()


@pytest.mark.parametrize(
    "record",
    [
        None,
        profile_record(employee_id="employee_2"),
        profile_record(legal_entity_id="entity_2"),
    ],
)
def test_handler_rejects_missing_or_mismatched_provider_record(
    record: EmployeeProfileRecord | None,
) -> None:
    handler = GetMyEmployeeProfileHandler(FakeHrCoreProvider(record))

    with pytest.raises(RuntimeError):
        run(handler, trusted_context())


def test_handler_rejects_missing_employee_context_before_provider_call() -> None:
    provider = FakeHrCoreProvider(profile_record())
    handler = GetMyEmployeeProfileHandler(provider)

    with pytest.raises(RuntimeError):
        run(handler, trusted_context(employee_id=None))

    assert provider.calls == []


def test_provider_exception_is_not_converted_to_profile_output() -> None:
    handler = GetMyEmployeeProfileHandler(FakeHrCoreProvider(profile_record(), raises=True))

    with pytest.raises(RuntimeError, match="synthetic provider failure"):
        run(handler, trusted_context())


def test_handler_rejects_wrong_input_model() -> None:
    class WrongInput(BaseModel):
        model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    handler = GetMyEmployeeProfileHandler(FakeHrCoreProvider(profile_record()))

    with pytest.raises(TypeError, match="unexpected"):
        asyncio.run(handler.execute(trusted_context(), WrongInput()))


def test_handler_rejects_invalid_provider_object() -> None:
    with pytest.raises(TypeError, match="HrCoreReadProvider"):
        GetMyEmployeeProfileHandler(object())  # type: ignore[arg-type]
