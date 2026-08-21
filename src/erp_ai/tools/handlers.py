"""Protocol implemented by trusted read-tool adapters."""

from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from erp_ai.context import TrustedRequestContext


@runtime_checkable
class ReadToolHandler(Protocol):
    """A fixed typed read handler; implementations are injected at gateway construction."""

    tool_name: str
    version: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]

    async def execute(self, context: TrustedRequestContext, arguments: BaseModel) -> object: ...
