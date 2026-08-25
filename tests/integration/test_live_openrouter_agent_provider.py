import asyncio
import os

import pytest
from pydantic import SecretStr

from erp_ai.infrastructure.openrouter import (
    OpenRouterAgentModelProvider,
    OpenRouterAgentModelProviderConfig,
)
from erp_ai.orchestration import (
    ModelFinalAnswer,
    ModelToolCall,
    ModelToolDefinition,
    ModelToolInteraction,
    ModelTurnRequest,
    ToolResultMessage,
)
from erp_ai.tools import PublicToolFailure, ToolErrorCode

pytestmark = pytest.mark.openrouter


def _live_enabled() -> bool:
    return os.environ.get("ERP_AI_REQUIRE_OPENROUTER_TESTS") == "1"


@pytest.mark.skipif(not _live_enabled(), reason="synthetic OpenRouter live test not enabled")
def test_live_synthetic_forced_call_and_state_free_continuation() -> None:
    key = os.environ.get("ERP_AI_OPENROUTER_API_KEY")
    if not key:
        pytest.fail("ERP_AI_OPENROUTER_API_KEY is required when the live test is enabled")

    tool_name = "combine_synthetic_tokens"
    definition = ModelToolDefinition(
        tool_name=tool_name,
        version="1.0.0",
        input_schema={
            "type": "object",
            "properties": {
                "left": {"type": "string", "enum": ["alpha"]},
                "right": {"type": "string", "enum": ["beta"]},
            },
            "required": ["left", "right"],
            "additionalProperties": False,
        },
    )
    instructions = (
        "Synthetic protocol test only; call the supplied tool exactly once on the first turn.",
        "After the tool result, return only a JSON object with response_type final_answer, "
        "a non-empty answer, answer_basis general, and empty evidence_call_ids and citation_ids.",
    )

    def request(
        number: int, interactions: tuple[ModelToolInteraction, ...] = ()
    ) -> ModelTurnRequest:
        return ModelTurnRequest(
            policy_instructions=instructions,
            user_message="Combine the fictional tokens alpha and beta.",
            response_language="en",
            tools=(definition,),
            interactions=interactions,
            turn_number=number,
        )

    async def exercise() -> None:
        provider = OpenRouterAgentModelProvider(
            OpenRouterAgentModelProviderConfig(
                api_key=SecretStr(key),
                synthetic_forced_tool_name=tool_name,
            )
        )
        first = await provider.complete_turn(request(1))
        assert isinstance(first, ModelToolCall)
        public_failure = PublicToolFailure(
            tool_name=first.tool_name,
            version=first.version,
            safe_error_code=ToolErrorCode.TOOL_UNAVAILABLE,
            safe_message="Synthetic result supplied.",
        )
        interaction = ModelToolInteraction(
            assistant_call=first,
            tool_result=ToolResultMessage(
                call_id=first.call_id,
                tool_name=first.tool_name,
                result=public_failure,
            ),
        )
        second = await provider.complete_turn(request(2, (interaction,)))
        assert isinstance(second, ModelFinalAnswer)

    asyncio.run(exercise())
