"""Direct OpenAI Responses API implementation of the provider-neutral model contract."""

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass, field

from erp_ai.orchestration import AgentModelProvider
from erp_ai.orchestration.models import (
    ModelFinalAnswer,
    ModelResponse,
    ModelToolCall,
    ModelToolDefinition,
    ModelTurnRequest,
    ToolSelectionMode,
    to_mutable_json,
)

from .client import OpenAIHttpClient, strict_json_loads
from .contracts import FINAL_ANSWER_SCHEMA, OPENAI_RESPONSES_PATH
from .errors import OpenAIProviderUnavailable
from .privacy import OpenAIProjectRouter


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
        "utf-8"
    )


def _strict_schema_value(value: object, schema: object) -> bool:
    if not isinstance(schema, Mapping):
        return False
    expected = schema.get("type")
    if expected == "object":
        if not isinstance(value, dict):
            return False
        properties = schema.get("properties")
        required = schema.get("required", [])
        if not isinstance(properties, Mapping) or not isinstance(required, (list, tuple)):
            return False
        if schema.get("additionalProperties") is not False or set(value) - set(properties):
            return False
        if not set(required).issubset(value):
            return False
        return all(_strict_schema_value(item, properties[key]) for key, item in value.items())
    if expected == "array":
        return isinstance(value, list) and all(
            _strict_schema_value(item, schema.get("items")) for item in value
        )
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return type(value) is int
    if expected == "number":
        return type(value) in (int, float)
    if expected == "boolean":
        return type(value) is bool
    if expected == "null":
        return value is None
    return False


@dataclass(frozen=True, slots=True)
class OpenAIResponsesModelProvider(AgentModelProvider):  # pragma: no cover - provider boundary
    router: OpenAIProjectRouter = field(repr=False)
    client: OpenAIHttpClient = field(repr=False)

    async def complete_turn(self, request: ModelTurnRequest) -> ModelResponse:
        try:
            request = ModelTurnRequest.model_validate(request, strict=True)
            approved = self.router.authorize(
                request.routing_customer_environment_id,
                request.maximum_data_classification,
                request.purpose,
                OPENAI_RESPONSES_PATH,
            )
            payload = self._payload(request, approved.route)
            body = _json_bytes(payload)
            if (
                len(body) > approved.route.limits.maximum_input_bytes
                or len(body) > approved.route.limits.maximum_input_tokens
            ):
                raise OpenAIProviderUnavailable
            raw = await self.client.post(approved.route, OPENAI_RESPONSES_PATH, body)
            return self._parse(
                raw,
                request,
                approved.route.chat_model,
                approved.route.limits.maximum_response_bytes,
            )
        except asyncio.CancelledError:
            raise
        except OpenAIProviderUnavailable:
            raise
        except Exception:
            raise OpenAIProviderUnavailable from None

    @staticmethod
    def _payload(request: ModelTurnRequest, route: object) -> dict[str, object]:
        from .config import OpenAIProjectRoute

        assert isinstance(route, OpenAIProjectRoute)
        input_items: list[dict[str, object]] = [
            {"role": "developer", "content": "\n".join(request.policy_instructions)},
            {"role": "user", "content": request.user_message},
        ]
        for interaction in request.interactions:
            call = interaction.assistant_call
            input_items.append(
                {
                    "type": "function_call",
                    "call_id": call.call_id,
                    "name": call.tool_name,
                    "arguments": call.arguments_json,
                }
            )
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(
                        interaction.tool_result.result.model_dump(mode="json"),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    ),
                }
            )
        tools = [OpenAIResponsesModelProvider._tool(item) for item in request.tools]
        selection = request.tool_selection
        tool_choice: object = "none"
        if selection.mode is ToolSelectionMode.REQUIRED_EXACT_TOOL:
            tool_choice = {"type": "function", "name": selection.tool_name}
        return {
            "model": route.chat_model,
            "input": input_items,
            "tools": tools,
            "tool_choice": tool_choice,
            "parallel_tool_calls": False,
            "reasoning": {"effort": route.reasoning_effort},
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "erp_ai_final_answer",
                    "strict": True,
                    "schema": FINAL_ANSWER_SCHEMA,
                }
            },
            "max_output_tokens": route.limits.maximum_output_tokens,
            "store": False,
            "stream": False,
            "background": False,
        }

    @staticmethod
    def _tool(tool: ModelToolDefinition) -> dict[str, object]:
        return {
            "type": "function",
            "name": tool.tool_name,
            "description": "Authorized read-only ERP AI tool.",
            "parameters": to_mutable_json(tool.input_schema),
            "strict": True,
        }

    @staticmethod
    def _parse(
        raw: bytes,
        request: ModelTurnRequest,
        expected_model: str,
        maximum_final_answer_bytes: int,
    ) -> ModelResponse:
        root = strict_json_loads(raw)
        if not isinstance(root, dict):
            raise OpenAIProviderUnavailable
        if (
            root.get("model") != expected_model
            or root.get("status") != "completed"
            or root.get("background") is not False
        ):
            raise OpenAIProviderUnavailable
        output = root.get("output")
        if not isinstance(output, list) or len(output) != 1:
            raise OpenAIProviderUnavailable
        item = output[0]
        if not isinstance(item, dict):
            raise OpenAIProviderUnavailable
        if request.tool_selection.mode is ToolSelectionMode.REQUIRED_EXACT_TOOL:
            return OpenAIResponsesModelProvider._parse_call(item, request)
        if item.get("type") != "message" or item.get("role") != "assistant":
            raise OpenAIProviderUnavailable
        content = item.get("content")
        if not isinstance(content, list) or len(content) != 1:
            raise OpenAIProviderUnavailable
        text_item = content[0]
        if not isinstance(text_item, dict) or text_item.get("type") != "output_text":
            raise OpenAIProviderUnavailable
        text = text_item.get("text")
        if not isinstance(text, str) or len(text.encode("utf-8")) > maximum_final_answer_bytes:
            raise OpenAIProviderUnavailable
        final = strict_json_loads(text.encode("utf-8"))
        return ModelFinalAnswer.model_validate(final, strict=True)

    @staticmethod
    def _parse_call(item: dict[str, object], request: ModelTurnRequest) -> ModelToolCall:
        if set(item) != {"type", "call_id", "name", "arguments", "status"}:
            raise OpenAIProviderUnavailable
        if item.get("type") != "function_call" or item.get("status") != "completed":
            raise OpenAIProviderUnavailable
        call_id, name, arguments = item.get("call_id"), item.get("name"), item.get("arguments")
        selected = request.tool_selection
        if (
            not isinstance(call_id, str)
            or not isinstance(name, str)
            or not isinstance(arguments, str)
            or name != selected.tool_name
            or len(request.tools) != 1
        ):
            raise OpenAIProviderUnavailable
        parsed = strict_json_loads(arguments.encode("utf-8"))
        if not isinstance(parsed, dict) or not _strict_schema_value(
            parsed, request.tools[0].input_schema
        ):
            raise OpenAIProviderUnavailable
        return ModelToolCall.from_arguments_json(
            call_id=call_id,
            tool_name=name,
            version=request.tools[0].version,
            arguments_json=arguments,
        )
