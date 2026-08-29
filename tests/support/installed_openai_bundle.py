"""Source-tree-independent installed-wheel smoke flow for Step 29 verification."""

import asyncio
import hashlib
import json
import ssl
from datetime import UTC, datetime, timedelta
from types import MappingProxyType

import httpx
from pydantic import BaseModel, ConfigDict, SecretStr

from erp_ai.capabilities import DataClassification
from erp_ai.infrastructure.openai import (
    OPENAI_EMBEDDINGS_PATH,
    OPENAI_RESPONSES_PATH,
    OpenAIProductionConfig,
    OpenAIProjectPrivacyAttestation,
    OpenAIProjectRoute,
    OpenAIRequestLimits,
    build_openai_production_bundle,
)
from erp_ai.knowledge.embeddings import (
    EmbeddingBatchRequest,
    EmbeddingInput,
    EmbeddingInputKind,
    EmbeddingProfile,
)
from erp_ai.knowledge.embeddings.models import (
    EmbeddingDistanceMetric,
    EmbeddingStorageRepresentation,
)
from erp_ai.orchestration import (
    ModelFinalAnswer,
    ModelToolCall,
    ModelToolDefinition,
    ModelToolInteraction,
    ModelToolSelection,
    ModelTurnRequest,
    ToolResultMessage,
    ToolSelectionMode,
)
from erp_ai.runtime import ProviderLifecycleLease
from erp_ai.tools import PublicToolSuccess

NOW = datetime(2026, 8, 28, 12, tzinfo=UTC)
CHAT_MODEL = "gpt-5.1-2025-11-13"
EMBEDDING_MODEL = "text-embedding-3-large"


class Clock:
    def now(self) -> datetime:
        return NOW


class Credentials:
    async def resolve(self, _reference: str, _organization: str, _project: str) -> SecretStr:
        return SecretStr("installed-wheel-synthetic-secret")


class Result(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    value: str


class Factory:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def create(self) -> httpx.AsyncBaseTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = json.loads(request.content)
        if request.url.path == OPENAI_EMBEDDINGS_PATH:
            payload = {
                "model": EMBEDDING_MODEL,
                "data": [{"object": "embedding", "index": 0, "embedding": [1.0, 0.0, 0.0]}],
            }
        elif body["tool_choice"] != "none":
            name = body["tool_choice"]["name"]
            payload = {
                "model": CHAT_MODEL,
                "status": "completed",
                "background": False,
                "output": [
                    {
                        "type": "function_call",
                        "call_id": f"call_{name}",
                        "name": name,
                        "arguments": "{}",
                        "status": "completed",
                    }
                ],
            }
        else:
            has_interaction = any(
                isinstance(item, dict) and item.get("type") == "function_call_output"
                for item in body["input"]
            )
            basis = "erp_data" if has_interaction else "general"
            call_ids = (
                [item["call_id"] for item in body["input"] if item.get("type") == "function_call"]
                if has_interaction
                else []
            )
            final = {
                "response_type": "final_answer",
                "answer": "Installed synthetic result.",
                "answer_basis": basis,
                "evidence_call_ids": call_ids,
                "citation_ids": [],
            }
            payload = {
                "model": CHAT_MODEL,
                "status": "completed",
                "background": False,
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": json.dumps(final)}],
                    }
                ],
            }
        return httpx.Response(
            200,
            content=json.dumps(payload, separators=(",", ":")).encode(),
            headers={"content-type": "application/json", "content-encoding": "identity"},
        )


def configuration() -> OpenAIProductionConfig:
    limits = OpenAIRequestLimits(
        connect_timeout_seconds=2.0,
        read_timeout_seconds=5.0,
        write_timeout_seconds=2.0,
        pool_timeout_seconds=2.0,
        maximum_request_bytes=131072,
        maximum_response_bytes=131072,
        maximum_input_bytes=65536,
        maximum_input_tokens=16384,
        maximum_output_tokens=4096,
    )
    route = OpenAIProjectRoute(
        customer_environment_id="installed-customer",
        organization_id="installed-org",
        project_id="installed-project",
        credential_reference="installed-credential",
        privacy_attestation_id="installed-policy",
        chat_model=CHAT_MODEL,
        embedding_model=EMBEDDING_MODEL,
        embedding_revision="installed-revision-1",
        embedding_dimensions=3,
        maximum_attestation_lifetime_seconds=2_678_400,
        allowed_data_classifications=(DataClassification.RESTRICTED,),
        allowed_purposes=("employee_self_service",),
        reasoning_effort="none",
        limits=limits,
    )
    attestation = OpenAIProjectPrivacyAttestation(
        organization_id="installed-org",
        project_id="installed-project",
        retention_mode="zero_data_retention",
        training_data_sharing_opt_in=False,
        allowed_endpoints=(OPENAI_RESPONSES_PATH, OPENAI_EMBEDDINGS_PATH),
        allowed_data_classifications=(DataClassification.RESTRICTED,),
        allowed_purposes=("employee_self_service",),
        approved_at=NOW - timedelta(days=1),
        expires_at=NOW + timedelta(days=1),
        policy_id="installed-policy",
        policy_digest="a" * 64,
    )
    return OpenAIProductionConfig(routes=(route,), attestations=(attestation,))


def turn(
    mode: ToolSelectionMode,
    tool_name: str | None = None,
    interaction: ModelToolInteraction | None = None,
) -> ModelTurnRequest:
    definition = (
        ModelToolDefinition(
            tool_name=tool_name,
            version="1.0.0",
            input_schema=MappingProxyType(
                {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
            ),
        )
        if tool_name is not None
        else None
    )
    return ModelTurnRequest(
        policy_instructions=("Installed synthetic policy.",),
        user_message="Installed synthetic request.",
        response_language="en",
        tools=(definition,) if definition is not None else (),
        tool_selection=ModelToolSelection(
            mode=mode,
            tool_name=tool_name if mode is ToolSelectionMode.REQUIRED_EXACT_TOOL else None,
            version="1.0.0" if mode is ToolSelectionMode.REQUIRED_EXACT_TOOL else None,
        ),
        interactions=(interaction,) if interaction is not None else (),
        turn_number=2 if interaction is not None else 1,
        routing_customer_environment_id="installed-customer",
        maximum_data_classification=DataClassification.RESTRICTED,
        purpose="employee_self_service",
    )


async def main() -> None:
    factory = Factory()
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    bundle = build_openai_production_bundle(
        config=configuration(),
        credential_provider=Credentials(),
        clock=Clock(),
        ssl_context=context,
        _transport_factory=factory,
    )
    lease = ProviderLifecycleLease(bundle.lifecycle)
    token = lease.claim()
    lease.release(token)
    await bundle.lifecycle.open()
    general = await bundle.model_provider.complete_turn(turn(ToolSelectionMode.NO_TOOLS))
    assert isinstance(general, ModelFinalAnswer)
    for tool_name in ("get_installed_erp_record", "search_installed_knowledge"):
        call = await bundle.model_provider.complete_turn(
            turn(ToolSelectionMode.REQUIRED_EXACT_TOOL, tool_name)
        )
        assert isinstance(call, ModelToolCall)
        interaction = ModelToolInteraction(
            assistant_call=call,
            tool_result=ToolResultMessage(
                call_id=call.call_id,
                tool_name=call.tool_name,
                result=PublicToolSuccess(
                    tool_name=call.tool_name,
                    version=call.version,
                    result=Result(value="installed synthetic"),
                ),
            ),
        )
        final = await bundle.model_provider.complete_turn(
            turn(ToolSelectionMode.FINAL_ONLY, interaction=interaction)
        )
        assert isinstance(final, ModelFinalAnswer)
    profile = EmbeddingProfile(
        contract_version=1,
        profile_id="installed_openai",
        provider_id="openai",
        model_id=EMBEDDING_MODEL,
        model_revision="installed-revision-1",
        dimensions=3,
        distance_metric=EmbeddingDistanceMetric.COSINE,
        storage_representation=EmbeddingStorageRepresentation.FLOAT32,
        input_normalization_version=1,
        document_transform_version=1,
        query_transform_version=1,
        query_instruction="Installed synthetic retrieval.",
        allowed_data_classifications=(DataClassification.RESTRICTED,),
    )
    text = "Installed synthetic query."
    result = await bundle.embedding_provider("installed-customer", "employee_self_service").embed(
        EmbeddingBatchRequest(
            profile=profile,
            inputs=(
                EmbeddingInput(
                    input_id="installed-query",
                    text=text,
                    content_sha256=hashlib.sha256(text.encode()).hexdigest(),
                    data_classification=DataClassification.RESTRICTED,
                    input_kind=EmbeddingInputKind.QUERY,
                ),
            ),
        )
    )
    assert len(result.vectors[0].values) == 3
    await bundle.lifecycle.close()
    assert len(factory.requests) == 6
    print("installed OpenAI bundle flows passed")


if __name__ == "__main__":
    asyncio.run(main())
