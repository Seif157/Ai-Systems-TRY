"""Bounded OpenRouter chat-completions adapter for synthetic tests only."""

import asyncio
import json
import os
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from erp_ai.orchestration.models import (
    ModelFinalAnswer,
    ModelResponse,
    ModelToolCall,
    ModelToolDefinition,
    ModelTurnRequest,
    ToolSelectionMode,
    to_mutable_json,
)

OPENROUTER_CHAT_COMPLETIONS_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
NORTH_MINI_CODE_MODEL: Final[Literal["cohere/north-mini-code:free"]] = "cohere/north-mini-code:free"
_CONTINUATION_STATE_FIELDS = frozenset(("reasoning", "reasoning_details"))
_ALLOWED_MESSAGE_FIELDS = frozenset(("role", "content", "tool_calls", "refusal"))


def _object_without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object keys are not allowed")
        result[key] = value
    return result


class OpenRouterProviderUnavailable(RuntimeError):
    """Safe provider error that never includes response or request data."""

    def __init__(self) -> None:
        super().__init__("model provider is unavailable")


class OpenRouterAgentModelProviderConfig(BaseModel):
    """Immutable server-owned configuration for the certified synthetic profile."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)

    classification: Literal["synthetic_test_only"] = "synthetic_test_only"
    model: Literal["cohere/north-mini-code:free"] = NORTH_MINI_CODE_MODEL
    api_key: SecretStr = Field(repr=False, min_length=1)
    connect_timeout_seconds: float = Field(default=5.0, strict=True, gt=0, le=30)
    read_timeout_seconds: float = Field(default=45.0, strict=True, gt=0, le=120)
    write_timeout_seconds: float = Field(default=10.0, strict=True, gt=0, le=30)
    pool_timeout_seconds: float = Field(default=5.0, strict=True, gt=0, le=30)
    maximum_request_bytes: int = Field(default=262_144, strict=True, ge=1, le=1_048_576)
    maximum_response_bytes: int = Field(default=262_144, strict=True, ge=1, le=1_048_576)
    maximum_final_answer_bytes: int = Field(default=32_768, strict=True, ge=1, le=131_072)

    @classmethod
    def from_environment(cls) -> "OpenRouterAgentModelProviderConfig":
        """Load only the secret from server environment configuration."""

        key = os.environ.get("ERP_AI_OPENROUTER_API_KEY")
        if not key:
            raise OpenRouterProviderUnavailable
        return cls(api_key=SecretStr(key))


NORTH_MINI_CODE_SYNTHETIC_PROFILE = MappingProxyType(
    {
        "classification": "synthetic_test_only",
        "model": NORTH_MINI_CODE_MODEL,
        "endpoint": OPENROUTER_CHAT_COMPLETIONS_ENDPOINT,
        "parallel_tool_calls_sent": False,
        "reasoning_excluded": True,
        "fallbacks_allowed": False,
        "streaming": False,
    }
)


@dataclass(frozen=True, slots=True, init=False)
class OpenRouterAgentModelProvider:
    """Translate provider-neutral turns to one sequential OpenRouter request."""

    config: OpenRouterAgentModelProviderConfig = field(repr=False)
    _lock: asyncio.Lock = field(repr=False, compare=False)

    def __init__(self, config: OpenRouterAgentModelProviderConfig) -> None:
        object.__setattr__(self, "config", config)
        object.__setattr__(self, "_lock", asyncio.Lock())

    async def complete_turn(self, request: ModelTurnRequest) -> ModelResponse:
        """Complete one bounded turn without retaining provider continuation state."""

        try:
            request = ModelTurnRequest.model_validate(request, strict=True)
        except Exception:
            raise OpenRouterProviderUnavailable from None
        payload, known_tools, forced_tool = self._build_payload(request)
        prior_call_ids = frozenset(
            interaction.assistant_call.call_id for interaction in request.interactions
        )
        request_bytes = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        if len(request_bytes) > self.config.maximum_request_bytes:
            raise OpenRouterProviderUnavailable
        async with self._lock:
            response_bytes = await self._post(request_bytes)
        return self._parse_response(
            response_bytes,
            known_tools,
            forced_tool,
            prior_call_ids,
            require_final=request.tool_selection.mode is ToolSelectionMode.FINAL_ONLY,
        )

    def _build_payload(
        self, request: ModelTurnRequest
    ) -> tuple[dict[str, object], dict[str, ModelToolDefinition], str | None]:
        tools = {tool.tool_name: tool for tool in request.tools}
        forced_tool = (
            request.tool_selection.tool_name
            if request.tool_selection.mode is ToolSelectionMode.REQUIRED_EXACT_TOOL
            else None
        )
        messages: list[dict[str, object]] = [
            {"role": "system", "content": "\n".join(request.policy_instructions)},
            {"role": "user", "content": request.user_message},
        ]
        for interaction in request.interactions:
            call = interaction.assistant_call
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call.call_id,
                            "type": "function",
                            "function": {
                                "name": call.tool_name,
                                "arguments": call.arguments_json,
                            },
                        }
                    ],
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": interaction.tool_result.call_id,
                    "name": interaction.tool_result.tool_name,
                    "content": json.dumps(
                        interaction.tool_result.result.model_dump(mode="json"),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    ),
                }
            )

        payload: dict[str, object] = {
            "model": self.config.model,
            "messages": messages,
            "reasoning": {"exclude": True},
            "provider": {"require_parameters": True, "allow_fallbacks": False},
            "stream": False,
        }
        if request.tools:
            payload["tools"] = [self._provider_tool(tool) for tool in request.tools]
        if forced_tool is not None:
            payload["tool_choice"] = {
                "type": "function",
                "function": {"name": forced_tool},
            }
        elif request.tool_selection.mode in (
            ToolSelectionMode.NO_TOOLS,
            ToolSelectionMode.FINAL_ONLY,
        ):
            payload["tool_choice"] = "none"
        return payload, tools, forced_tool

    @staticmethod
    def _provider_tool(tool: ModelToolDefinition) -> dict[str, object]:
        return {
            "type": "function",
            "function": {
                "name": tool.tool_name,
                "description": "Authorized synthetic test tool.",
                "parameters": to_mutable_json(tool.input_schema),
            },
        }

    async def _post(self, request_bytes: bytes) -> bytes:
        timeout = httpx.Timeout(
            connect=self.config.connect_timeout_seconds,
            read=self.config.read_timeout_seconds,
            write=self.config.write_timeout_seconds,
            pool=self.config.pool_timeout_seconds,
        )
        headers = {
            "Authorization": f"Bearer {self.config.api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=False,
                trust_env=False,
                limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
            ) as client:
                request = client.build_request(
                    "POST",
                    OPENROUTER_CHAT_COMPLETIONS_ENDPOINT,
                    headers=headers,
                    content=request_bytes,
                )
                response = await client.send(request, stream=True)
                try:
                    if response.status_code < 200 or response.status_code >= 300:
                        raise OpenRouterProviderUnavailable
                    if response.headers.get("content-type", "").split(";", 1)[
                        0
                    ].strip().lower() != ("application/json"):
                        raise OpenRouterProviderUnavailable
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > self.config.maximum_response_bytes:
                            raise OpenRouterProviderUnavailable
                        chunks.append(chunk)
                    return b"".join(chunks)
                finally:
                    await response.aclose()
        except OpenRouterProviderUnavailable:
            raise
        except Exception:
            raise OpenRouterProviderUnavailable from None

    def _parse_response(
        self,
        response_bytes: bytes,
        known_tools: dict[str, ModelToolDefinition],
        forced_tool: str | None,
        prior_call_ids: frozenset[str],
        *,
        require_final: bool,
    ) -> ModelResponse:
        try:
            root = json.loads(
                response_bytes,
                object_pairs_hook=_object_without_duplicate_keys,
                parse_constant=self._reject_json_constant,
            )
            if not isinstance(root, dict) or root.get("model") != self.config.model:
                raise OpenRouterProviderUnavailable
            choices = root.get("choices")
            if not isinstance(choices, list) or len(choices) != 1:
                raise OpenRouterProviderUnavailable
            choice = choices[0]
            if not isinstance(choice, dict):
                raise OpenRouterProviderUnavailable
            if type(choice.get("index")) is not int or choice["index"] != 0:
                raise OpenRouterProviderUnavailable
            message = choice.get("message")
            if not isinstance(message, dict) or message.get("role") != "assistant":
                raise OpenRouterProviderUnavailable
            unknown_fields = set(message) - _ALLOWED_MESSAGE_FIELDS - _CONTINUATION_STATE_FIELDS
            if unknown_fields:
                raise OpenRouterProviderUnavailable
            calls = message.get("tool_calls")
            if calls is None:
                calls = []
            if not isinstance(calls, list) or len(calls) > 1:
                raise OpenRouterProviderUnavailable
            if forced_tool is not None and len(calls) != 1:
                raise OpenRouterProviderUnavailable
            if calls:
                if require_final:
                    raise OpenRouterProviderUnavailable
                if choice.get("finish_reason") != "tool_calls":
                    raise OpenRouterProviderUnavailable
                if message.get("content") is not None:
                    raise OpenRouterProviderUnavailable
                return self._parse_tool_call(calls[0], known_tools, forced_tool, prior_call_ids)
            if choice.get("finish_reason") != "stop":
                raise OpenRouterProviderUnavailable
            content = message.get("content")
            if not isinstance(content, str) or len(content.encode("utf-8")) > (
                self.config.maximum_final_answer_bytes
            ):
                raise OpenRouterProviderUnavailable
            final_payload = json.loads(
                content,
                object_pairs_hook=_object_without_duplicate_keys,
                parse_constant=self._reject_json_constant,
            )
            return ModelFinalAnswer.model_validate(final_payload, strict=True)
        except OpenRouterProviderUnavailable:
            raise
        except Exception:
            raise OpenRouterProviderUnavailable from None

    @staticmethod
    def _parse_tool_call(
        raw_call: object,
        known_tools: dict[str, ModelToolDefinition],
        forced_tool: str | None,
        prior_call_ids: frozenset[str],
    ) -> ModelToolCall:
        if not isinstance(raw_call, dict):
            raise OpenRouterProviderUnavailable
        fields = set(raw_call)
        if not {"id", "type", "function"}.issubset(fields) or not fields.issubset(
            {"id", "type", "function", "index"}
        ):
            raise OpenRouterProviderUnavailable
        if type(raw_call.get("index")) is not int or raw_call["index"] != 0:
            raise OpenRouterProviderUnavailable
        if raw_call.get("type") != "function":
            raise OpenRouterProviderUnavailable
        function = raw_call.get("function")
        if not isinstance(function, dict) or set(function) != {"name", "arguments"}:
            raise OpenRouterProviderUnavailable
        name = function.get("name")
        call_id = raw_call.get("id")
        arguments_json = function.get("arguments")
        if not isinstance(name, str) or name not in known_tools:
            raise OpenRouterProviderUnavailable
        if forced_tool is not None and name != forced_tool:
            raise OpenRouterProviderUnavailable
        if (
            not isinstance(call_id, str)
            or call_id in prior_call_ids
            or not isinstance(arguments_json, str)
        ):
            raise OpenRouterProviderUnavailable
        definition = known_tools[name]
        return ModelToolCall.from_arguments_json(
            call_id=call_id,
            tool_name=name,
            version=definition.version,
            arguments_json=arguments_json,
        )

    @staticmethod
    def _reject_json_constant(_: str) -> object:
        raise ValueError("non-finite JSON number")
