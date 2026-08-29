from types import MappingProxyType

import pytest
from pydantic import ValidationError

from erp_ai.api import PublicChatRequest
from erp_ai.capabilities import DataClassification
from erp_ai.orchestration import (
    AgentRouteMode,
    AgentRoutingPolicy,
    ModelToolCall,
    ModelToolDefinition,
    ModelToolInteraction,
    ModelToolSelection,
    ModelTurnRequest,
    ToolResultMessage,
    ToolSelectionMode,
)
from erp_ai.tools import PublicToolFailure, ToolErrorCode


def definition() -> ModelToolDefinition:
    return ModelToolDefinition(
        tool_name="get_my_employee_profile",
        version="1.0.0",
        input_schema=MappingProxyType({"type": "object"}),
    )


def test_routing_policy_is_strict_frozen_and_repr_safe() -> None:
    route = AgentRoutingPolicy(
        mode=AgentRouteMode.EXACT_READ_THEN_FINAL,
        tool_name="get_my_employee_profile",
        version="1.0.0",
    )
    assert "get_my_employee_profile" not in repr(route)
    with pytest.raises(ValidationError):
        route.mode = AgentRouteMode.GENERAL_ONLY  # type: ignore[misc]
    with pytest.raises(ValidationError):
        AgentRoutingPolicy.model_validate(
            {"mode": "general_only", "tool_name": "get_my_employee_profile"}, strict=True
        )
    with pytest.raises(ValidationError):
        AgentRoutingPolicy.model_validate({"mode": "general_only", "extra": True}, strict=True)


@pytest.mark.parametrize(
    "field",
    (
        "route",
        "routing_mode",
        "mode",
        "tool_name",
        "tool_version",
        "version",
        "tool_selection",
        "capability",
        "model",
        "tool_choice",
    ),
)
def test_public_request_cannot_spoof_routing(field: str) -> None:
    with pytest.raises(ValidationError):
        PublicChatRequest.model_validate({"message": "Help", field: "attacker"})


def test_required_exact_selection_requires_one_matching_tool() -> None:
    selection = ModelToolSelection(
        mode=ToolSelectionMode.REQUIRED_EXACT_TOOL,
        tool_name="get_my_employee_profile",
        version="1.0.0",
    )
    request = ModelTurnRequest(
        policy_instructions=("policy",),
        user_message="synthetic",
        response_language="en",
        tools=(definition(),),
        tool_selection=selection,
        interactions=(),
        turn_number=1,
        routing_customer_environment_id="synthetic-customer",
        maximum_data_classification=DataClassification.RESTRICTED,
        purpose="synthetic_test",
    )
    assert request.tools == (definition(),)
    with pytest.raises(ValidationError):
        ModelTurnRequest.model_validate({**request.model_dump(), "tools": ()}, strict=True)
    wrong = definition().model_copy(update={"version": "2.0.0"})
    with pytest.raises(ValidationError):
        ModelTurnRequest.model_validate({**request.model_dump(), "tools": (wrong,)}, strict=True)


def test_no_tools_selection_rejects_exposed_catalog() -> None:
    with pytest.raises(ValidationError):
        ModelTurnRequest(
            policy_instructions=("policy",),
            user_message="synthetic",
            response_language="en",
            tools=(definition(),),
            tool_selection=ModelToolSelection(mode=ToolSelectionMode.NO_TOOLS),
            interactions=(),
            turn_number=1,
            routing_customer_environment_id="synthetic-customer",
            maximum_data_classification=DataClassification.RESTRICTED,
            purpose="synthetic_test",
        )


def test_selection_rejects_inconsistent_exact_fields() -> None:
    with pytest.raises(ValidationError):
        ModelToolSelection(
            mode=ToolSelectionMode.REQUIRED_EXACT_TOOL,
            tool_name="get_my_employee_profile",
        )
    with pytest.raises(ValidationError):
        ModelToolSelection(mode=ToolSelectionMode.FINAL_ONLY, version="1.0.0")


def test_general_route_rejects_server_tool_fields() -> None:
    with pytest.raises(ValidationError):
        AgentRoutingPolicy(
            mode=AgentRouteMode.GENERAL_ONLY,
            tool_name="get_my_employee_profile",
            version="1.0.0",
        )


def test_constructed_route_and_selection_are_defensively_revalidated() -> None:
    invalid_route = AgentRoutingPolicy.model_construct(
        mode=AgentRouteMode.EXACT_READ_THEN_FINAL,
        tool_name=None,
        version=None,
    )
    with pytest.raises(ValidationError):
        AgentRoutingPolicy.model_validate(invalid_route, strict=True)

    invalid_selection = ModelToolSelection.model_construct(
        mode=ToolSelectionMode.REQUIRED_EXACT_TOOL,
        tool_name=None,
        version=None,
    )
    with pytest.raises(ValidationError):
        ModelToolSelection.model_validate(invalid_selection, strict=True)

    invalid_turn = ModelTurnRequest.model_construct(
        policy_instructions=("policy",),
        user_message="synthetic",
        response_language="en",
        tools=(),
        tool_selection=ModelToolSelection(mode=ToolSelectionMode.NO_TOOLS),
        interactions=(),
        turn_number=0,
    )
    with pytest.raises(ValidationError):
        ModelTurnRequest.model_validate(invalid_turn, strict=True)


def test_final_only_requires_one_successful_interaction() -> None:
    call = ModelToolCall.from_arguments(
        call_id="call_1",
        tool_name="get_my_employee_profile",
        version="1.0.0",
        arguments={},
    )
    failure = PublicToolFailure(
        tool_name=call.tool_name,
        version=call.version,
        safe_error_code=ToolErrorCode.TOOL_UNAVAILABLE,
        safe_message="Unavailable.",
    )
    interaction = ModelToolInteraction(
        assistant_call=call,
        tool_result=ToolResultMessage(
            call_id=call.call_id, tool_name=call.tool_name, result=failure
        ),
    )
    with pytest.raises(ValidationError):
        ModelTurnRequest(
            policy_instructions=("policy",),
            user_message="synthetic",
            response_language="en",
            tools=(),
            tool_selection=ModelToolSelection(mode=ToolSelectionMode.FINAL_ONLY),
            interactions=(interaction,),
            turn_number=2,
        )
