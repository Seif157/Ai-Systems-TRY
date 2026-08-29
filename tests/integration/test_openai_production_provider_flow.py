"""Synthetic two-project flow through the production OpenAI bundle."""

import asyncio
import json

import httpx

from erp_ai.infrastructure.openai import build_openai_production_bundle
from erp_ai.orchestration import ModelFinalAnswer, ToolSelectionMode
from tests.unit.test_openai_production_provider import (
    CHAT_MODEL,
    Clock,
    Credentials,
    TransportFactory,
    attestation,
    config,
    final_response,
    response,
    ssl_context,
    turn,
)


def test_synthetic_general_flow_uses_only_configured_project() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return response(final_response())

    credentials = Credentials()
    bundle = build_openai_production_bundle(
        config=config(),
        credential_provider=credentials,
        clock=Clock(),
        ssl_context=ssl_context(),
        _transport_factory=TransportFactory(handler),
    )

    async def exercise() -> None:
        await bundle.lifecycle.open()
        result = await bundle.model_provider.complete_turn(turn(ToolSelectionMode.NO_TOOLS))
        assert isinstance(result, ModelFinalAnswer)
        await bundle.lifecycle.close()

    asyncio.run(exercise())
    assert len(captured) == 1
    assert captured[0].headers["openai-project"] == "proj_alpha"
    assert credentials.calls == [("credential-proj_alpha", "org_approved", "proj_alpha")]
    assert json.loads(captured[0].content)["model"] == CHAT_MODEL
    assert "customer-alpha" not in captured[0].content.decode()


def test_attestation_fixture_contains_no_provider_or_customer_content() -> None:
    value = attestation().model_dump(mode="json")
    assert "prompt" not in value and "response" not in value and "customer" not in value
