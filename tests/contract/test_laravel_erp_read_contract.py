import hashlib

from erp_ai.infrastructure.laravel_erp import (
    LARAVEL_ERP_READ_CONTRACT_BYTES,
    LARAVEL_ERP_READ_CONTRACT_DIGEST,
)
from erp_ai.infrastructure.laravel_erp.contracts import (
    BALANCES_PATH,
    CONTRACT_PATH,
    PROFILE_PATH,
    REQUEST_DETAIL_PATH,
    REQUESTS_PATH,
    contract_digest,
    mutable_contract_descriptor,
)
from erp_ai.infrastructure.laravel_erp.models import (
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


def test_frozen_canonical_contract() -> None:
    assert not LARAVEL_ERP_READ_CONTRACT_BYTES.endswith(b"\n")
    assert (
        hashlib.sha256(
            b"erp-ai:laravel-erp-read-contract:v1\x00" + LARAVEL_ERP_READ_CONTRACT_BYTES
        ).hexdigest()
        == LARAVEL_ERP_READ_CONTRACT_DIGEST
    )
    assert (CONTRACT_PATH, PROFILE_PATH, BALANCES_PATH, REQUESTS_PATH, REQUEST_DETAIL_PATH) == (
        "/internal/ai/v1/read-contract",
        "/internal/ai/v1/hr/profile/read-self",
        "/internal/ai/v1/leave/balances/read-self",
        "/internal/ai/v1/leave/requests/list-self",
        "/internal/ai/v1/leave/requests/get-self",
    )


def test_private_wire_allowlists_are_exact() -> None:
    common = (
        "contract_version",
        "correlation_request_id",
        "customer_environment_id",
        "user_id",
        "employee_id",
        "authorization_snapshot_id",
        "purpose",
        "legal_entity_ids",
        "tool_name",
        "tool_version",
    )
    assert tuple(LaravelBinding.model_fields) == common
    assert tuple(ProfileRequest.model_fields) == common
    assert tuple(BalancesRequest.model_fields) == common
    assert tuple(RequestListRequest.model_fields) == (*common, "page_size", "cursor")
    assert tuple(RequestDetailRequest.model_fields) == (*common, "leave_request_id")
    assert tuple(ProfileResponse.model_fields) == (*common, "outcome", "profile")
    assert tuple(BalancesResponse.model_fields) == (*common, "outcome", "balances")
    assert tuple(RequestListResponse.model_fields) == (*common, "outcome", "requests")
    assert tuple(RequestDetailResponse.model_fields) == (*common, "outcome", "leave_request")


def test_every_contract_dimension_is_digest_bound() -> None:
    mutations = []
    for edit in (
        lambda d: d.__setitem__("contract_version", "2.0.0"),
        lambda d: d["operations"][0].__setitem__("path", "/wrong"),
        lambda d: d["operations"][0].__setitem__("method", "GET"),
        lambda d: d["operations"][0]["request_fields"].reverse(),
        lambda d: d["operations"][0]["request_fields"][0].__setitem__(1, "string"),
        lambda d: d["operations"][0]["response_fields"][-1].__setitem__(1, "nullable:any"),
        lambda d: d["operations"][0]["response_fields"][-2][1].append("denied"),
    ):
        descriptor = mutable_contract_descriptor()
        edit(descriptor)
        mutations.append(contract_digest(descriptor))
    assert all(value != LARAVEL_ERP_READ_CONTRACT_DIGEST for value in mutations)
    assert len(set(mutations)) == len(mutations)
