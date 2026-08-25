import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from types import MappingProxyType

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from erp_ai.api import PublicChatRequest
from erp_ai.infrastructure.openrouter import (
    NORTH_MINI_CODE_SYNTHETIC_PROFILE,
    OpenRouterAgentModelProvider,
    OpenRouterAgentModelProviderConfig,
    OpenRouterProviderUnavailable,
)
from erp_ai.orchestration import (
    AgentAuditEvent,
    AgentModelProvider,
    ModelFinalAnswer,
    ModelToolCall,
    ModelToolDefinition,
    ModelToolInteraction,
    ModelTurnRequest,
    ToolResultMessage,
)
from erp_ai.tools import PublicToolFailure, ToolAuditEvent, ToolErrorCode

ASYNC_CLIENT = httpx.AsyncClient
MODEL = "cohere/north-mini-code:free"
TOOL_NAME = "combine_synthetic_tokens"
PRIVATE_MARKER = "private-synthetic-marker"


def config(**overrides: object) -> OpenRouterAgentModelProviderConfig:
    values: dict[str, object] = {
        "api_key": SecretStr("synthetic-secret"),
        "synthetic_forced_tool_name": TOOL_NAME,
    }
    values.update(overrides)
    return OpenRouterAgentModelProviderConfig.model_validate(values)


def tool() -> ModelToolDefinition:
    return ModelToolDefinition(
        tool_name=TOOL_NAME,
        version="1.0.0",
        input_schema={
            "type": "object",
            "properties": {
                "left": {"type": "string"},
                "right": {"type": "string"},
            },
            "required": ["left", "right"],
            "additionalProperties": False,
        },
    )


def turn(
    *, number: int = 1, interactions: tuple[ModelToolInteraction, ...] = ()
) -> ModelTurnRequest:
    return ModelTurnRequest(
        policy_instructions=(
            "Synthetic protocol test only.",
            "Return the strict provider-neutral JSON contract.",
        ),
        user_message="Combine two fictional tokens.",
        response_language="en",
        tools=(tool(),),
        interactions=interactions,
        turn_number=number,
    )


def tool_call_response(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "model": MODEL,
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_synthetic_1",
                            "type": "function",
                            "function": {
                                "name": TOOL_NAME,
                                "arguments": '{ "left": "alpha", "right": "beta" }',
                            },
                        }
                    ],
                },
            }
        ],
    }
    values.update(overrides)
    return values


def final_response(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "model": MODEL,
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "response_type": "final_answer",
                            "answer": "Synthetic combination completed.",
                            "answer_basis": "general",
                            "evidence_call_ids": [],
                            "citation_ids": [],
                        },
                        separators=(",", ":"),
                    ),
                },
            }
        ],
    }
    values.update(overrides)
    return values


def response(
    payload: object, *, status: int = 200, content_type: str = "application/json"
) -> httpx.Response:
    return httpx.Response(
        status,
        content=json.dumps(payload, separators=(",", ":")).encode(),
        headers={"content-type": content_type},
    )


def install_transport(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> None:
    def factory(**kwargs: object) -> httpx.AsyncClient:
        return ASYNC_CLIENT(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr("erp_ai.infrastructure.openrouter.provider.httpx.AsyncClient", factory)


def interaction(call: ModelToolCall) -> ModelToolInteraction:
    failure = PublicToolFailure(
        tool_name=call.tool_name,
        version=call.version,
        safe_error_code=ToolErrorCode.TOOL_UNAVAILABLE,
        safe_message="Synthetic tool unavailable.",
    )
    return ModelToolInteraction(
        assistant_call=call,
        tool_result=ToolResultMessage(
            call_id=call.call_id,
            tool_name=call.tool_name,
            result=failure,
        ),
    )


def test_configuration_is_strict_frozen_secret_safe_and_synthetic_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = config()
    assert "synthetic-secret" not in repr(value)
    assert value.classification == "synthetic_test_only"
    assert isinstance(NORTH_MINI_CODE_SYNTHETIC_PROFILE, MappingProxyType)
    assert NORTH_MINI_CODE_SYNTHETIC_PROFILE["parallel_tool_calls_sent"] is False
    assert isinstance(OpenRouterAgentModelProvider(value), AgentModelProvider)
    with pytest.raises(ValidationError):
        value.model = "different"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        config(model="different")
    with pytest.raises(ValidationError):
        config(endpoint="https://example.invalid")
    with pytest.raises(ValidationError):
        config(synthetic_forced_tool_name="Bad.Name")
    with pytest.raises(ValidationError):
        config(unknown=True)
    with pytest.raises(ValidationError):
        PublicChatRequest(message="safe", model=MODEL)  # type: ignore[call-arg]
    monkeypatch.delenv("ERP_AI_OPENROUTER_API_KEY", raising=False)
    with pytest.raises(OpenRouterProviderUnavailable):
        OpenRouterAgentModelProviderConfig.from_environment()
    monkeypatch.setenv("ERP_AI_OPENROUTER_API_KEY", "environment-secret")
    loaded = OpenRouterAgentModelProviderConfig.from_environment()
    assert loaded.api_key.get_secret_value() == "environment-secret"


def test_forced_call_and_exact_transcript_replay_discard_provider_state(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    requests: list[dict[str, object]] = []
    replies = [
        response(
            tool_call_response(
                choices=[
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            **tool_call_response()["choices"][0]["message"],  # type: ignore[index]
                            "reasoning": PRIVATE_MARKER,
                            "reasoning_details": [{"opaque": PRIVATE_MARKER}],
                        },
                    }
                ]
            )
        ),
        response(final_response()),
    ]

    def handler(http_request: httpx.Request) -> httpx.Response:
        assert http_request.url == "https://openrouter.ai/api/v1/chat/completions"
        assert http_request.headers["authorization"] == "Bearer synthetic-secret"
        requests.append(json.loads(http_request.content))
        return replies.pop(0)

    install_transport(monkeypatch, handler)

    async def exercise() -> None:
        provider = OpenRouterAgentModelProvider(config())
        first = await provider.complete_turn(turn())
        assert isinstance(first, ModelToolCall)
        assert first.arguments_json == '{ "left": "alpha", "right": "beta" }'
        result = await provider.complete_turn(turn(number=2, interactions=(interaction(first),)))
        assert isinstance(result, ModelFinalAnswer)

    asyncio.run(exercise())
    assert not caplog.records
    assert len(requests) == 2
    first_payload, second_payload = requests
    assert "parallel_tool_calls" not in first_payload
    assert first_payload["tool_choice"] == {
        "type": "function",
        "function": {"name": TOOL_NAME},
    }
    assert first_payload["reasoning"] == {"exclude": True}
    assert first_payload["provider"] == {
        "require_parameters": True,
        "allow_fallbacks": False,
    }
    assert "tool_choice" not in second_payload
    replay = second_payload["messages"]  # type: ignore[assignment]
    assert [item["role"] for item in replay] == ["system", "user", "assistant", "tool"]  # type: ignore[index]
    assert replay[2]["tool_calls"][0]["id"] == "call_synthetic_1"  # type: ignore[index]
    assert replay[2]["tool_calls"][0]["function"]["arguments"] == (  # type: ignore[index]
        '{ "left": "alpha", "right": "beta" }'
    )
    serialized = json.dumps(second_payload)
    assert PRIVATE_MARKER not in serialized
    assert "reasoning_details" not in replay[2]  # type: ignore[operator]


@pytest.mark.parametrize(
    ("choice_index", "tool_call_index"),
    (
        (0, 0),
        (False, 0),
        (0.0, 0),
        ("0", 0),
        (1, 0),
        (0, False),
        (0, 0.0),
        (0, "0"),
        (0, 1),
        (0, None),
        (None, 0),
    ),
)
def test_choice_and_tool_indexes_are_strict_integers(
    monkeypatch: pytest.MonkeyPatch,
    choice_index: object,
    tool_call_index: object,
) -> None:
    payload = tool_call_response()
    choice = payload["choices"][0]  # type: ignore[index]
    if choice_index is None:
        del choice["index"]  # type: ignore[index]
    else:
        choice["index"] = choice_index  # type: ignore[index]
    call = choice["message"]["tool_calls"][0]  # type: ignore[index]
    if tool_call_index is None:
        del call["index"]  # type: ignore[index]
    else:
        call["index"] = tool_call_index  # type: ignore[index]
    install_transport(monkeypatch, lambda _: response(payload))
    provider = OpenRouterAgentModelProvider(config())
    if (
        choice_index == 0
        and type(choice_index) is int
        and tool_call_index == 0
        and type(tool_call_index) is int
    ):
        assert isinstance(asyncio.run(provider.complete_turn(turn())), ModelToolCall)
    else:
        with pytest.raises(OpenRouterProviderUnavailable):
            asyncio.run(provider.complete_turn(turn()))


@pytest.mark.parametrize(
    "payload",
    (
        tool_call_response(model="different/model"),
        {"model": MODEL, "choices": []},
        {
            "model": MODEL,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            tool_call_response()["choices"][0]["message"]["tool_calls"][0],  # type: ignore[index]
                            tool_call_response()["choices"][0]["message"]["tool_calls"][0],  # type: ignore[index]
                        ],
                    },
                }
            ],
        },
        {
            "model": MODEL,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {"role": "assistant", "content": None, "tool_calls": []},
                }
            ],
        },
        {
            "model": MODEL,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "unknown_tool", "arguments": "{}"},
                            }
                        ],
                    },
                }
            ],
        },
        {
            "model": MODEL,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": TOOL_NAME, "arguments": "not-json"},
                            }
                        ],
                    },
                }
            ],
        },
    ),
)
def test_invalid_forced_responses_fail_closed(
    monkeypatch: pytest.MonkeyPatch, payload: object
) -> None:
    install_transport(monkeypatch, lambda _: response(payload))
    with pytest.raises(OpenRouterProviderUnavailable) as caught:
        asyncio.run(OpenRouterAgentModelProvider(config()).complete_turn(turn()))
    assert PRIVATE_MARKER not in repr(caught.value)


@pytest.mark.parametrize(
    ("provider_response", "configuration"),
    (
        (httpx.Response(503, json={"detail": PRIVATE_MARKER}), config()),
        (httpx.Response(200, text="not-json", headers={"content-type": "text/plain"}), config()),
        (
            httpx.Response(
                200,
                content=b"x" * 1025,
                headers={"content-type": "application/json"},
            ),
            config(maximum_response_bytes=1024),
        ),
    ),
)
def test_provider_status_content_type_and_response_limits_are_safe(
    monkeypatch: pytest.MonkeyPatch,
    provider_response: httpx.Response,
    configuration: OpenRouterAgentModelProviderConfig,
) -> None:
    install_transport(monkeypatch, lambda _: provider_response)
    with pytest.raises(OpenRouterProviderUnavailable) as caught:
        asyncio.run(OpenRouterAgentModelProvider(configuration).complete_turn(turn()))
    assert PRIVATE_MARKER not in str(caught.value)


def test_request_limit_invalid_configuration_and_missing_forced_tool_fail_before_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return response(tool_call_response())

    install_transport(monkeypatch, handler)
    with pytest.raises(OpenRouterProviderUnavailable):
        asyncio.run(
            OpenRouterAgentModelProvider(config(maximum_request_bytes=1)).complete_turn(turn())
        )
    empty_catalog = turn().model_copy(update={"tools": ()})
    with pytest.raises(OpenRouterProviderUnavailable):
        asyncio.run(OpenRouterAgentModelProvider(config()).complete_turn(empty_catalog))
    duplicate_catalog = turn().model_copy(update={"tools": (tool(), tool())})
    with pytest.raises(OpenRouterProviderUnavailable):
        asyncio.run(OpenRouterAgentModelProvider(config()).complete_turn(duplicate_catalog))
    assert called is False


def test_timeout_transport_error_and_cancellation_are_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure: BaseException = httpx.ReadTimeout(PRIVATE_MARKER)

    def handler(_: httpx.Request) -> httpx.Response:
        raise failure

    install_transport(monkeypatch, handler)
    with pytest.raises(OpenRouterProviderUnavailable) as caught:
        asyncio.run(OpenRouterAgentModelProvider(config()).complete_turn(turn()))
    assert PRIVATE_MARKER not in str(caught.value)
    failure = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(OpenRouterAgentModelProvider(config()).complete_turn(turn()))


@pytest.mark.parametrize(
    "payload",
    (
        final_response(model="substituted/model"),
        {
            "model": MODEL,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_2",
                                "type": "function",
                                "function": {"name": TOOL_NAME, "arguments": "{}"},
                            }
                        ],
                    },
                }
            ],
        },
        {
            "model": MODEL,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "not-json"},
                }
            ],
        },
        {
            "model": MODEL,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": '{"response_type":"final_answer","answer":"x","answer":"y"}',
                    },
                }
            ],
        },
        {
            "model": MODEL,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": "{}",
                        "provider_private_state": PRIVATE_MARKER,
                    },
                }
            ],
        },
    ),
)
def test_invalid_final_responses_and_unknown_state_fail_closed(
    monkeypatch: pytest.MonkeyPatch, payload: object
) -> None:
    install_transport(monkeypatch, lambda _: response(payload))
    provider = OpenRouterAgentModelProvider(config())
    with pytest.raises(OpenRouterProviderUnavailable):
        asyncio.run(provider.complete_turn(turn(number=2)))


def test_final_answer_size_and_valid_final_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replies = [response(final_response()), response(final_response())]
    install_transport(monkeypatch, lambda _: replies.pop(0))
    valid = OpenRouterAgentModelProvider(config(synthetic_forced_tool_name=None))
    assert isinstance(asyncio.run(valid.complete_turn(turn(number=2))), ModelFinalAnswer)
    limited = OpenRouterAgentModelProvider(
        config(synthetic_forced_tool_name=None, maximum_final_answer_bytes=1)
    )
    with pytest.raises(OpenRouterProviderUnavailable):
        asyncio.run(limited.complete_turn(turn(number=2)))


@pytest.mark.parametrize(
    "payload",
    (
        {"model": MODEL, "choices": ["not-an-object"]},
        {
            "model": MODEL,
            "choices": [{"index": 0, "finish_reason": "stop", "message": []}],
        },
        {
            "model": MODEL,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "user", "content": "{}"},
                }
            ],
        },
        {
            "model": MODEL,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": tool_call_response()["choices"][0]["message"][  # type: ignore[index]
                            "tool_calls"
                        ],
                    },
                }
            ],
        },
        {
            "model": MODEL,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "length",
                    "message": {"role": "assistant", "content": "{}"},
                }
            ],
        },
        b'{"model":"cohere/north-mini-code:free","choices":NaN}',
    ),
)
def test_additional_response_shapes_fail_closed(
    monkeypatch: pytest.MonkeyPatch, payload: object
) -> None:
    if isinstance(payload, bytes):
        provider_response = httpx.Response(
            200, content=payload, headers={"content-type": "application/json"}
        )
    else:
        provider_response = response(payload)
    install_transport(monkeypatch, lambda _: provider_response)
    with pytest.raises(OpenRouterProviderUnavailable):
        asyncio.run(
            OpenRouterAgentModelProvider(config(synthetic_forced_tool_name=None)).complete_turn(
                turn(number=2)
            )
        )


def test_tool_call_cannot_include_ambiguous_text_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = tool_call_response()
    payload["choices"][0]["message"]["content"] = "ambiguous"  # type: ignore[index]
    install_transport(monkeypatch, lambda _: response(payload))
    with pytest.raises(OpenRouterProviderUnavailable):
        asyncio.run(OpenRouterAgentModelProvider(config()).complete_turn(turn()))


def test_excessive_provider_nesting_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    deeply_nested = b"[" * 1100 + b"0" + b"]" * 1100
    install_transport(
        monkeypatch,
        lambda _: httpx.Response(
            200,
            content=deeply_nested,
            headers={"content-type": "application/json"},
        ),
    )
    with pytest.raises(OpenRouterProviderUnavailable):
        asyncio.run(
            OpenRouterAgentModelProvider(config(synthetic_forced_tool_name=None)).complete_turn(
                turn(number=2)
            )
        )


def test_provider_state_is_absent_from_neutral_public_and_audit_contracts() -> None:
    forbidden = {"reasoning", "reasoning_details", "provider_state", "model"}
    assert forbidden.isdisjoint(ModelTurnRequest.model_fields)
    assert forbidden.isdisjoint(ModelToolCall.model_fields)
    assert forbidden.isdisjoint(ModelFinalAnswer.model_fields)
    assert forbidden.isdisjoint(AgentAuditEvent.model_fields)
    assert forbidden.isdisjoint(ToolAuditEvent.model_fields)
    assert PRIVATE_MARKER not in repr(OpenRouterProviderUnavailable())


def test_no_production_composition_constructs_openrouter_provider() -> None:
    source_root = Path(__file__).parents[2] / "src" / "erp_ai"
    forbidden_import = "OpenRouterAgentModelProvider"
    occurrences = []
    for source_file in source_root.rglob("*.py"):
        if "infrastructure/openrouter" in source_file.as_posix():
            continue
        if forbidden_import in source_file.read_text(encoding="utf-8"):
            occurrences.append(source_file.relative_to(source_root).as_posix())
    assert occurrences == []


@pytest.mark.parametrize(
    ("raw_call", "forced_tool", "prior_ids"),
    (
        ([], TOOL_NAME, frozenset()),
        (
            {
                "index": 0,
                "id": "call_1",
                "type": "other",
                "function": {"name": TOOL_NAME, "arguments": "{}"},
            },
            TOOL_NAME,
            frozenset(),
        ),
        (
            {
                "index": 1,
                "id": "call_1",
                "type": "function",
                "function": {"name": TOOL_NAME, "arguments": "{}"},
            },
            TOOL_NAME,
            frozenset(),
        ),
        (
            {
                "extra": False,
                "id": "call_1",
                "type": "function",
                "function": {"name": TOOL_NAME, "arguments": "{}"},
            },
            TOOL_NAME,
            frozenset(),
        ),
        (
            {"index": 0, "id": "call_1", "type": "function", "function": []},
            TOOL_NAME,
            frozenset(),
        ),
        (
            {
                "index": 0,
                "id": "call_1",
                "type": "function",
                "function": {"name": TOOL_NAME, "arguments": "{}", "extra": True},
            },
            TOOL_NAME,
            frozenset(),
        ),
        (
            {
                "index": 0,
                "id": "call_1",
                "type": "function",
                "function": {"name": TOOL_NAME, "arguments": "{}"},
            },
            "different_tool",
            frozenset(),
        ),
        (
            {
                "index": 0,
                "id": "call_1",
                "type": "function",
                "function": {"name": TOOL_NAME, "arguments": "{}"},
            },
            TOOL_NAME,
            frozenset(("call_1",)),
        ),
        (
            {
                "index": 0,
                "id": 1,
                "type": "function",
                "function": {"name": TOOL_NAME, "arguments": "{}"},
            },
            TOOL_NAME,
            frozenset(),
        ),
    ),
)
def test_tool_envelope_and_duplicate_call_id_fail_closed(
    raw_call: object, forced_tool: str, prior_ids: frozenset[str]
) -> None:
    with pytest.raises(OpenRouterProviderUnavailable):
        OpenRouterAgentModelProvider._parse_tool_call(
            raw_call,
            {TOOL_NAME: tool()},
            forced_tool,
            prior_ids,
        )
