"""Frozen, dependency-independent Laravel ERP read wire contract."""

import hashlib
import json
from typing import Final, Literal, cast

from pydantic import BaseModel, ConfigDict, field_validator

LARAVEL_ERP_READ_DOMAIN: Final = "erp-ai.laravel-erp-read-contract"
LARAVEL_ERP_READ_SERVICE_IDENTITY: Final = "laravel_erp_read_api"
LARAVEL_ERP_READ_CONTRACT_VERSION: Final = "1.0.0"
CONTRACT_PATH: Final = "/internal/ai/v1/read-contract"
PROFILE_PATH: Final = "/internal/ai/v1/hr/profile/read-self"
BALANCES_PATH: Final = "/internal/ai/v1/leave/balances/read-self"
REQUESTS_PATH: Final = "/internal/ai/v1/leave/requests/list-self"
REQUEST_DETAIL_PATH: Final = "/internal/ai/v1/leave/requests/get-self"
POST_PATHS: Final = frozenset({PROFILE_PATH, BALANCES_PATH, REQUESTS_PATH, REQUEST_DETAIL_PATH})

COMMON_FIELDS: Final = (
    ("contract_version", "literal:1.0.0"),
    ("correlation_request_id", "uuid:v4:lowercase-hyphenated"),
    ("customer_environment_id", "identifier:1..128"),
    ("user_id", "identifier:1..128"),
    ("employee_id", "identifier:1..128"),
    ("authorization_snapshot_id", "identifier:1..128"),
    ("purpose", "snake_code:1..64"),
    ("legal_entity_ids", "ordered_unique_array<identifier>:1..256"),
    ("tool_name", "snake_code:1..128"),
    ("tool_version", "semver_release"),
)

_CONTRACT_DESCRIPTOR: Final = {
    "domain": LARAVEL_ERP_READ_DOMAIN,
    "service_identity": LARAVEL_ERP_READ_SERVICE_IDENTITY,
    "contract_version": LARAVEL_ERP_READ_CONTRACT_VERSION,
    "canonicalization": "compact-insertion-ordered-utf8-finite-json-no-newline",
    "metadata": {
        "method": "GET",
        "path": CONTRACT_PATH,
        "fields": [
            ["service_identity", "literal:laravel_erp_read_api"],
            ["contract_version", "literal:1.0.0"],
            ["contract_digest", "sha256:lowerhex"],
            ["read_only", "literal:true"],
        ],
    },
    "operations": [
        {
            "name": "get_my_employee_profile",
            "method": "POST",
            "path": PROFILE_PATH,
            "request_fields": COMMON_FIELDS,
            "response_fields": [
                *COMMON_FIELDS,
                ["outcome", ["found", "not_found"]],
                ["profile", "EmployeeProfileRecord:v1|null"],
            ],
        },
        {
            "name": "get_my_leave_balances",
            "method": "POST",
            "path": BALANCES_PATH,
            "request_fields": COMMON_FIELDS,
            "response_fields": [
                *COMMON_FIELDS,
                ["outcome", ["found"]],
                ["balances", "ordered_array<LeaveBalanceRecord:v1>"],
            ],
        },
        {
            "name": "list_my_leave_requests",
            "method": "POST",
            "path": REQUESTS_PATH,
            "request_fields": [
                *COMMON_FIELDS,
                ["page_size", "strict_integer:1..100"],
                ["cursor", "opaque_string:1..4096|null"],
            ],
            "response_fields": [
                *COMMON_FIELDS,
                ["outcome", ["found"]],
                ["requests", "LeaveRequestPageRecord:v1"],
            ],
        },
        {
            "name": "get_my_leave_request",
            "method": "POST",
            "path": REQUEST_DETAIL_PATH,
            "request_fields": [
                *COMMON_FIELDS,
                ["leave_request_id", "uuid:lowercase-hyphenated"],
            ],
            "response_fields": [
                *COMMON_FIELDS,
                ["outcome", ["found", "not_found"]],
                ["leave_request", "LeaveRequestDetailRecord:v1|null"],
            ],
        },
    ],
    "read_only": True,
}


def canonical_contract_bytes(descriptor: object = _CONTRACT_DESCRIPTOR) -> bytes:
    return json.dumps(
        descriptor, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode()


def contract_digest(descriptor: object = _CONTRACT_DESCRIPTOR) -> str:
    return hashlib.sha256(
        b"erp-ai:laravel-erp-read-contract:v1\x00" + canonical_contract_bytes(descriptor)
    ).hexdigest()


LARAVEL_ERP_READ_CONTRACT_BYTES: Final = canonical_contract_bytes()
LARAVEL_ERP_READ_CONTRACT_DIGEST: Final = contract_digest()


def mutable_contract_descriptor() -> dict[str, object]:
    return cast(dict[str, object], json.loads(canonical_contract_bytes()))


class LaravelContractMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)
    service_identity: Literal["laravel_erp_read_api"]
    contract_version: Literal["1.0.0"]
    contract_digest: str
    read_only: Literal[True]

    @field_validator("contract_digest")
    @classmethod
    def exact_digest(cls, value: str) -> str:
        if value != LARAVEL_ERP_READ_CONTRACT_DIGEST:
            raise ValueError("contract digest mismatch")
        return value

    @field_validator("read_only", mode="before")
    @classmethod
    def strict_true(cls, value: object) -> object:
        if type(value) is not bool or value is not True:
            raise ValueError("read_only must be true")
        return value
