"""Model-provider-neutral agent turn boundary."""

from typing import Protocol, runtime_checkable

from erp_ai.orchestration.models import ModelResponse, ModelTurnRequest


@runtime_checkable
class AgentModelProvider(Protocol):
    async def complete_turn(self, request: ModelTurnRequest) -> ModelResponse: ...
