import pytest
from pydantic import ValidationError

from erp_ai.api import PublicChatRequest
from erp_ai.application.audit import ApplicationAuditEvent
from erp_ai.orchestration.audit import AgentAuditEvent
from erp_ai.tools.audit import ToolAuditEvent


@pytest.mark.parametrize(
    "field",
    (
        "model",
        "project_id",
        "organization_id",
        "credential_reference",
        "privacy_attestation_id",
        "retention_mode",
        "maximum_data_classification",
        "purpose",
        "store",
        "endpoint",
    ),
)
def test_public_request_cannot_select_openai_policy(field: str) -> None:
    with pytest.raises(ValidationError):
        PublicChatRequest.model_validate({"message": "Synthetic", field: "attacker"})


def test_audit_contracts_have_no_openai_provider_fields() -> None:
    forbidden = {
        "model",
        "project_id",
        "organization_id",
        "credential",
        "prompt",
        "response_id",
        "usage",
        "embedding",
        "vector",
    }
    for contract in (ApplicationAuditEvent, AgentAuditEvent, ToolAuditEvent):
        assert forbidden.isdisjoint(contract.model_fields)
