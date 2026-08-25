import pytest

from erp_ai.infrastructure.postgres_erp.contract import (
    BUSINESS_VIEW_SIGNATURES,
    CONTRACT_DESCRIPTOR,
    CONTRACT_VERSION,
    METADATA_VIEW_SIGNATURE,
    ContractDescriptor,
    canonical_contract_bytes,
    contract_digest,
    validate_contract_snapshot,
    validate_postgres_version,
)
from erp_ai.infrastructure.postgres_erp.errors import ErpReadContractError

EXPECTED_DIGEST = "077528e247774f3584de47187b97975535d938f562cdf6ad59c61ce9a506aec5"
GOLDEN_CANONICAL_JSON = (
    '{"contract_version":"1.0.0","views":['
    '["ai_read.hr_employee_profile_v1",[["employee_id","uuid"],'
    '["legal_entity_id","uuid"],["employee_number","character varying"],'
    '["display_name","character varying"],["work_email","character varying"],'
    '["job_title","character varying"],["department_name","character varying"],'
    '["branch_name","character varying"],["legal_entity_name","character varying"],'
    '["employment_status","character varying"],["hire_date","date"],'
    '["manager_display_name","character varying"],'
    '["freshness_at","timestamp with time zone"]]],'
    '["ai_read.leave_balances_v1",[["employee_id","uuid"],'
    '["legal_entity_id","uuid"],["leave_type_id","uuid"],'
    '["leave_type_code","character varying"],["leave_type_name","character varying"],'
    '["leave_type_name_local","character varying"],["fiscal_year","smallint"],'
    '["opening_days","numeric"],["accrued_days","numeric"],["used_days","numeric"],'
    '["pending_days","numeric"],["available_days","numeric"],'
    '["calculated_at","timestamp with time zone"],'
    '["source_watermark","character varying"],'
    '["calculation_version","character varying"]]],'
    '["ai_read.leave_requests_v1",[["request_id","uuid"],["employee_id","uuid"],'
    '["legal_entity_id","uuid"],["leave_type_id","uuid"],'
    '["leave_type_code","character varying"],["leave_type_name","character varying"],'
    '["leave_type_name_local","character varying"],["start_date","date"],'
    '["end_date","date"],["working_days","numeric"],["is_half_day","boolean"],'
    '["half_day_period","character varying"],["status","character varying"],'
    '["submitted_at","timestamp with time zone"],'
    '["updated_at","timestamp with time zone"],'
    '["working_days_calculation_version","character varying"]]],'
    '["ai_read.leave_request_history_v1",[["history_id","uuid"],'
    '["request_id","uuid"],["employee_id","uuid"],["legal_entity_id","uuid"],'
    '["entity_type","character varying"],["from_status","character varying"],'
    '["to_status","character varying"],["changed_at","timestamp with time zone"],'
    '["reason_code","character varying"]]]],'
    '"metadata_view":["ai_read.contract_metadata_v1",'
    '[["contract_version","character varying"],["contract_sha256","character"]]]}'
)


def test_contract_golden_bytes_and_digest_are_frozen() -> None:
    raw = canonical_contract_bytes()
    assert raw == GOLDEN_CANONICAL_JSON.encode("utf-8")
    assert not raw.endswith(b"\n")
    assert contract_digest() == EXPECTED_DIGEST
    assert CONTRACT_DESCRIPTOR[0] == CONTRACT_VERSION == "1.0.0"
    assert tuple(name for name, _ in CONTRACT_DESCRIPTOR[1]) == (
        "ai_read.hr_employee_profile_v1",
        "ai_read.leave_balances_v1",
        "ai_read.leave_requests_v1",
        "ai_read.leave_request_history_v1",
    )
    assert CONTRACT_DESCRIPTOR[2][0] == "ai_read.contract_metadata_v1"


def _mutated_descriptors() -> tuple[ContractDescriptor, ...]:
    version, views, metadata = CONTRACT_DESCRIPTOR
    first_name, first_columns = views[0]
    changed_name = (("ai_read.changed_v1", first_columns), *views[1:])
    changed_column_name = (
        (first_name, (("changed_id", first_columns[0][1]), *first_columns[1:])),
        *views[1:],
    )
    changed_type = (
        (first_name, ((first_columns[0][0], "text"), *first_columns[1:])),
        *views[1:],
    )
    changed_column_order = (
        (first_name, (first_columns[1], first_columns[0], *first_columns[2:])),
        *views[1:],
    )
    return (
        ("2.0.0", views, metadata),
        (version, changed_name, metadata),
        (version, (views[1], views[0], *views[2:]), metadata),
        (version, changed_column_name, metadata),
        (version, changed_column_order, metadata),
        (version, changed_type, metadata),
        (version, views, ("ai_read.changed_metadata_v1", metadata[1])),
        (version, views, (metadata[0], (metadata[1][1], metadata[1][0]))),
        (version, views, (metadata[0], (("changed", "text"), *metadata[1][1:]))),
    )


@pytest.mark.parametrize("descriptor", _mutated_descriptors())
def test_every_semantic_or_order_drift_changes_digest(descriptor: ContractDescriptor) -> None:
    assert contract_digest(descriptor) != EXPECTED_DIGEST


def test_startup_rejects_reported_and_observed_contract_drift() -> None:
    with pytest.raises(ErpReadContractError, match="metadata mismatch"):
        validate_contract_snapshot(
            reported_version="2.0.0",
            reported_digest=EXPECTED_DIGEST,
            actual_views=BUSINESS_VIEW_SIGNATURES,
            actual_metadata_view=METADATA_VIEW_SIGNATURE,
        )
    with pytest.raises(ErpReadContractError, match="view signature mismatch"):
        validate_contract_snapshot(
            reported_version=CONTRACT_VERSION,
            reported_digest=EXPECTED_DIGEST,
            actual_views=(
                BUSINESS_VIEW_SIGNATURES[1],
                BUSINESS_VIEW_SIGNATURES[0],
                *BUSINESS_VIEW_SIGNATURES[2:],
            ),
            actual_metadata_view=METADATA_VIEW_SIGNATURE,
        )
    with pytest.raises(ErpReadContractError, match="metadata view signature mismatch"):
        validate_contract_snapshot(
            reported_version=CONTRACT_VERSION,
            reported_digest=EXPECTED_DIGEST,
            actual_views=BUSINESS_VIEW_SIGNATURES,
            actual_metadata_view=("ai_read.changed_v1", METADATA_VIEW_SIGNATURE[1]),
        )


def test_supported_postgres_versions_remain_separate_from_digest() -> None:
    for major in range(15, 19):
        validate_postgres_version(major * 10_000)
    with pytest.raises(ErpReadContractError, match="unsupported"):
        validate_postgres_version(140000)
    with pytest.raises(ErpReadContractError, match="unsupported"):
        validate_postgres_version(190000)
