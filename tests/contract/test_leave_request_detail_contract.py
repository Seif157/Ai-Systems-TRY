from erp_ai.capabilities.leave import (
    GetMyLeaveRequestInput,
    GetMyLeaveRequestOutput,
    LeaveRequestStatusTransition,
)


def test_detail_input_contains_only_record_selector() -> None:
    assert set(GetMyLeaveRequestInput.model_fields) == {"request_id"}


def test_public_detail_contract_contains_only_approved_fields() -> None:
    assert set(GetMyLeaveRequestOutput.model_fields) == {
        "request_id",
        "leave_type_code",
        "leave_type_name",
        "leave_type_name_local",
        "start_date",
        "end_date",
        "working_days",
        "is_half_day",
        "half_day_period",
        "status",
        "submitted_at",
        "updated_at",
        "status_timeline",
    }
    assert set(LeaveRequestStatusTransition.model_fields) == {
        "from_status",
        "to_status",
        "changed_at",
        "reason_code",
    }
