from erp_ai.orchestration import (
    AgentAuditEvent,
    ModelFinalAnswer,
    ModelToolInteraction,
    ModelTurnRequest,
    PublicChatFailure,
    PublicChatSuccess,
    PublicCitation,
    ToolResultMessage,
)


def test_public_chat_results_are_explicit_allowlists() -> None:
    assert set(PublicChatSuccess.model_fields) == {"answer", "response_language", "citations"}
    assert set(PublicChatFailure.model_fields) == {"safe_error_code", "safe_message"}
    assert set(PublicCitation.model_fields) == {
        "citation_id",
        "title",
        "section",
        "language",
        "source_type",
        "document_version",
    }


def test_model_turn_carries_only_minimum_repr_hidden_provider_routing_context() -> None:
    assert set(ModelTurnRequest.model_fields) == {
        "policy_instructions",
        "user_message",
        "response_language",
        "tools",
        "tool_selection",
        "interactions",
        "turn_number",
        "routing_customer_environment_id",
        "maximum_data_classification",
        "purpose",
    }
    assert set(ToolResultMessage.model_fields) == {
        "call_id",
        "tool_name",
        "result",
        "content_trust",
    }
    assert set(ModelToolInteraction.model_fields) == {"assistant_call", "tool_result"}
    assert set(ModelToolInteraction.model_fields["assistant_call"].metadata) == set()
    forbidden = {
        "trusted_context",
        "customer_environment_id",
        "user_id",
        "employee_id",
        "roles",
        "permission_codes",
        "enabled_modules",
        "legal_entity_ids",
        "authorization_snapshot_id",
        "denials",
        "audit_event",
    }
    assert forbidden.isdisjoint(ModelTurnRequest.model_fields)
    for field in (
        "routing_customer_environment_id",
        "maximum_data_classification",
        "purpose",
    ):
        assert ModelTurnRequest.model_fields[field].repr is False
    assert forbidden.isdisjoint(ModelToolInteraction.model_fields)
    assert set(ModelFinalAnswer.model_fields) == {
        "response_type",
        "answer",
        "answer_basis",
        "evidence_call_ids",
        "citation_ids",
    }
    assert "answer_basis" not in PublicChatSuccess.model_fields
    assert "evidence_call_ids" not in PublicChatSuccess.model_fields


def test_agent_audit_schema_is_exact() -> None:
    assert set(AgentAuditEvent.model_fields) == {
        "request_id",
        "customer_environment_id",
        "user_id",
        "purpose",
        "action",
        "outcome",
        "internal_reason",
    }
