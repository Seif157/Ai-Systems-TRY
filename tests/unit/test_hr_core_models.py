from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from erp_ai.capabilities.hr_core import (
    EmployeeProfileRecord,
    EmploymentStatus,
    GetMyEmployeeProfileInput,
    GetMyEmployeeProfileOutput,
)


def record_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "employee_id": "employee_1",
        "legal_entity_id": "entity_1",
        "employee_number": "EMP-001",
        "display_name": "Synthetic Employee",
        "work_email": "employee@example.test",
        "job_title": "Software Engineer",
        "department_name": "Engineering",
        "branch_name": "Cairo",
        "legal_entity_name": "Example Egypt",
        "employment_status": "active",
        "hire_date": date(2024, 1, 15),
        "manager_display_name": "Synthetic Manager",
        "freshness_at": datetime(2026, 8, 22, 9, 0, tzinfo=ZoneInfo("Africa/Cairo")),
    }
    payload.update(overrides)
    return payload


def test_empty_input_accepts_only_empty_arguments() -> None:
    assert GetMyEmployeeProfileInput.model_validate({}, strict=True).model_dump() == {}

    with pytest.raises(ValidationError):
        GetMyEmployeeProfileInput.model_validate({"employee_id": "forged"}, strict=True)


def test_internal_record_is_strict_frozen_and_normalized() -> None:
    record = EmployeeProfileRecord.model_validate(
        record_payload(display_name=" Synthetic Employee "), strict=True
    )

    assert record.display_name == "Synthetic Employee"
    with pytest.raises(ValidationError):
        record.employee_id = "employee_2"  # type: ignore[misc]


@pytest.mark.parametrize("model", [EmployeeProfileRecord, GetMyEmployeeProfileOutput])
def test_profile_models_reject_naive_freshness(model: type[object]) -> None:
    payload = record_payload(freshness_at=datetime(2026, 8, 22, 9, 0))
    if model is GetMyEmployeeProfileOutput:
        payload.pop("employee_id")
        payload.pop("legal_entity_id")

    with pytest.raises(ValidationError, match="timezone-aware"):
        model.model_validate(payload, strict=True)  # type: ignore[attr-defined]


def test_safe_output_excludes_internal_and_prohibited_hr_fields() -> None:
    record = EmployeeProfileRecord.model_validate(record_payload(), strict=True)
    output = GetMyEmployeeProfileOutput(
        employee_number=record.employee_number,
        display_name=record.display_name,
        work_email=record.work_email,
        job_title=record.job_title,
        department_name=record.department_name,
        branch_name=record.branch_name,
        legal_entity_name=record.legal_entity_name,
        employment_status=record.employment_status,
        hire_date=record.hire_date,
        manager_display_name=record.manager_display_name,
        freshness_at=record.freshness_at,
    )

    prohibited = {
        "employee_id",
        "legal_entity_id",
        "national_id",
        "passport_number",
        "religion",
        "marital_status",
        "gender",
        "date_of_birth",
        "personal_email",
        "personal_phone",
        "home_address",
        "bank_information",
        "salary",
        "compensation",
        "medical_information",
        "emergency_contacts",
        "authentication_information",
    }
    assert not prohibited & set(GetMyEmployeeProfileOutput.model_fields)
    assert not prohibited & set(output.model_dump())


def test_optional_profile_fields_remain_none_without_inference() -> None:
    optional_fields = {
        "job_title": None,
        "department_name": None,
        "branch_name": None,
        "legal_entity_name": None,
        "manager_display_name": None,
    }
    record = EmployeeProfileRecord.model_validate(record_payload(**optional_fields), strict=True)

    for field in optional_fields:
        assert getattr(record, field) is None


def test_profile_text_must_be_a_nonempty_string() -> None:
    with pytest.raises(ValidationError):
        EmployeeProfileRecord.model_validate(record_payload(display_name=123), strict=True)
    with pytest.raises(ValidationError):
        EmployeeProfileRecord.model_validate(record_payload(display_name="  "), strict=True)


@pytest.mark.parametrize("status", list(EmploymentStatus))
def test_employment_status_matches_employee_schema(status: EmploymentStatus) -> None:
    record = EmployeeProfileRecord.model_validate(
        record_payload(employment_status=status.value), strict=True
    )

    assert record.employment_status is status


def test_invalid_employment_status_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EmployeeProfileRecord.model_validate(
            record_payload(employment_status="unknown"), strict=True
        )


@pytest.mark.parametrize("required_field", ["work_email", "hire_date"])
@pytest.mark.parametrize("model", [EmployeeProfileRecord, GetMyEmployeeProfileOutput])
def test_schema_required_profile_fields_cannot_be_omitted(
    required_field: str, model: type[object]
) -> None:
    payload = record_payload()
    if model is GetMyEmployeeProfileOutput:
        payload.pop("employee_id")
        payload.pop("legal_entity_id")
    payload.pop(required_field)

    with pytest.raises(ValidationError):
        model.model_validate(payload, strict=True)  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("employee_number", "E" * 21),
        ("employee_number", " "),
        ("display_name", "D" * 201),
        ("work_email", "e" * 201),
        ("work_email", " "),
    ],
)
def test_required_profile_text_limits(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        EmployeeProfileRecord.model_validate(record_payload(**{field: value}), strict=True)


@pytest.mark.parametrize(
    "field",
    ["job_title", "department_name", "branch_name", "legal_entity_name", "manager_display_name"],
)
def test_optional_display_fields_reject_blank_values(field: str) -> None:
    with pytest.raises(ValidationError):
        EmployeeProfileRecord.model_validate(record_payload(**{field: "  "}), strict=True)
