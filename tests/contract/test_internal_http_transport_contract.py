from pydantic import SecretStr

from erp_ai.api import PublicChatRequest
from erp_ai.application import TrustedRequestReference
from erp_ai.transport.http import (
    InternalHttpTransportConfig,
    TrustedIngressAuthenticationRequest,
)
from erp_ai.transport.http.protocols import TransportDependencies


def test_public_body_and_authentication_contracts_are_disjoint() -> None:
    public_fields = set(PublicChatRequest.model_json_schema()["properties"])
    authentication_fields = set(
        TrustedIngressAuthenticationRequest.model_json_schema()["properties"]
    )
    assert public_fields == {"message", "stream", "preferred_response_language"}
    assert authentication_fields == {
        "request_id",
        "method",
        "route_path",
        "body_digest_sha256",
        "bearer_assertion",
    }
    prohibited = {
        "customer_environment_id",
        "user_id",
        "roles",
        "permission_codes",
        "enabled_modules",
        "legal_entity_ids",
        "purpose",
        "authorization_snapshot_id",
        "route_intent",
        "tool_name",
    }
    assert not prohibited & public_fields
    assert not prohibited & authentication_fields


def test_authenticator_can_return_only_the_existing_opaque_reference() -> None:
    assert set(TrustedRequestReference.model_json_schema()["properties"]) == {
        "request_id",
        "resolver_handle",
    }
    request = TrustedIngressAuthenticationRequest(
        request_id="123e4567-e89b-42d3-a456-426614174000",
        method="POST",
        route_path="/v1/chat",
        body_digest_sha256="a" * 64,
        bearer_assertion=SecretStr("opaque"),
    )
    assert "opaque" not in repr(request)


def test_transport_configuration_has_no_secret_or_provider_selection_fields() -> None:
    assert set(InternalHttpTransportConfig.model_json_schema()["properties"]) == {
        "allowed_hosts",
        "require_https",
        "maximum_body_bytes",
        "maximum_authorization_bytes",
    }


def test_transport_dependency_contract_has_only_explicit_security_boundaries() -> None:
    assert set(TransportDependencies.__annotations__) == {
        "authenticator",
        "request_id_factory",
        "application",
        "application_audit_sink",
        "lifecycle",
    }
