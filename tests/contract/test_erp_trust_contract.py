from erp_ai.application import TrustedRequestReference
from erp_ai.infrastructure.erp_trust.assertions import HEADER_FIELDS, PAYLOAD_FIELDS
from erp_ai.infrastructure.erp_trust.models import (
    ResolveRequest,
    ResolveResponse,
    SnapshotVerifyRequest,
    SnapshotVerifyResponse,
)


def test_assertion_and_reference_contract_allowlists_are_exact() -> None:
    assert {"alg", "kid", "typ"} == HEADER_FIELDS
    assert {
        "v",
        "iss",
        "aud",
        "jti",
        "iat",
        "exp",
        "method",
        "path",
        "body_sha256",
        "resolver_ref",
    } == PAYLOAD_FIELDS
    assert set(TrustedRequestReference.model_json_schema()["properties"]) == {
        "request_id",
        "resolver_reference",
    }


def test_erp_trust_json_contract_allowlists_are_exact() -> None:
    assert set(ResolveRequest.model_json_schema()["properties"]) == {
        "contract_version",
        "request_id",
        "resolver_reference",
    }
    assert set(ResolveResponse.model_json_schema()["properties"]) == {
        "contract_version",
        "request_id",
        "trusted_request_context",
        "trusted_route_intent",
    }
    bindings = {
        "contract_version",
        "request_id",
        "customer_environment_id",
        "user_id",
        "authorization_snapshot_id",
    }
    assert set(SnapshotVerifyRequest.model_json_schema()["properties"]) == bindings
    assert set(SnapshotVerifyResponse.model_json_schema()["properties"]) == bindings | {"status"}
