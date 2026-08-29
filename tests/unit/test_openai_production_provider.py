import asyncio
import hashlib
import json
import ssl
from datetime import UTC, datetime, timedelta
from types import MappingProxyType

import httpx
import pytest
from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from erp_ai.capabilities import DataClassification
from erp_ai.infrastructure.openai import (
    OPENAI_EMBEDDINGS_PATH,
    OPENAI_ORIGIN,
    OPENAI_RESPONSES_PATH,
    OpenAIPrivacyDenied,
    OpenAIProductionConfig,
    OpenAIProjectPrivacyAttestation,
    OpenAIProjectRoute,
    OpenAIProviderUnavailable,
    OpenAIRequestLimits,
    build_openai_production_bundle,
)
from erp_ai.infrastructure.openai.client import strict_json_loads
from erp_ai.infrastructure.openai.model_provider import _strict_schema_value
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
    AnswerBasis,
    ModelFinalAnswer,
    ModelToolCall,
    ModelToolDefinition,
    ModelToolInteraction,
    ModelToolSelection,
    ModelTurnRequest,
    ToolResultMessage,
    ToolSelectionMode,
)
from erp_ai.tools import PublicToolSuccess

NOW = datetime(2026, 8, 28, 12, tzinfo=UTC)
CHAT_MODEL = "gpt-5.1-2025-11-13"
EMBEDDING_MODEL = "text-embedding-3-large"
PRIVATE = "never-expose-private-marker"


class SyntheticSafeResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    value: str


class Clock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return self.value


class Credentials:
    def __init__(self, failure: BaseException | None = None) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.failure = failure

    async def resolve(self, reference: str, organization: str, project: str) -> SecretStr:
        self.calls.append((reference, organization, project))
        if self.failure is not None:
            raise self.failure
        return SecretStr(PRIVATE)


class InvalidCredentials:
    def __init__(self, value: object) -> None:
        self.value = value
        self.calls = 0

    async def resolve(self, reference: str, organization: str, project: str) -> SecretStr:
        self.calls += 1
        return self.value  # type: ignore[return-value]


class TransportFactory:
    def __init__(self, handler) -> None:  # type: ignore[no-untyped-def]
        self.handler = handler

    def create(self) -> httpx.AsyncBaseTransport:
        return httpx.MockTransport(self.handler)


def ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def limits() -> OpenAIRequestLimits:
    return OpenAIRequestLimits(
        connect_timeout_seconds=2.0,
        read_timeout_seconds=5.0,
        write_timeout_seconds=2.0,
        pool_timeout_seconds=2.0,
        maximum_request_bytes=131_072,
        maximum_response_bytes=131_072,
        maximum_input_bytes=65_536,
        maximum_input_tokens=16_384,
        maximum_output_tokens=4096,
    )


def attestation(
    *,
    policy_id: str = "privacy-policy-a",
    project_id: str = "proj_alpha",
    approved_at: datetime = NOW - timedelta(days=1),
    expires_at: datetime = NOW + timedelta(days=30),
) -> OpenAIProjectPrivacyAttestation:
    return OpenAIProjectPrivacyAttestation(
        organization_id="org_approved",
        project_id=project_id,
        retention_mode="zero_data_retention",
        training_data_sharing_opt_in=False,
        allowed_endpoints=(OPENAI_RESPONSES_PATH, OPENAI_EMBEDDINGS_PATH),
        allowed_data_classifications=(DataClassification.RESTRICTED,),
        allowed_purposes=("employee_self_service",),
        approved_at=approved_at,
        expires_at=expires_at,
        policy_id=policy_id,
        policy_digest="a" * 64,
    )


def route(
    *, customer: str = "customer-alpha", project_id: str = "proj_alpha"
) -> OpenAIProjectRoute:
    return OpenAIProjectRoute(
        customer_environment_id=customer,
        organization_id="org_approved",
        project_id=project_id,
        credential_reference=f"credential-{project_id}",
        privacy_attestation_id=f"privacy-policy-{project_id[-1]}",
        chat_model=CHAT_MODEL,
        embedding_model=EMBEDDING_MODEL,
        embedding_revision="deployment-eval-revision-1",
        embedding_dimensions=3,
        maximum_attestation_lifetime_seconds=2_678_400,
        allowed_data_classifications=(DataClassification.RESTRICTED,),
        allowed_purposes=("employee_self_service",),
        reasoning_effort="none",
        limits=limits(),
    )


def config() -> OpenAIProductionConfig:
    return OpenAIProductionConfig(routes=(route(),), attestations=(attestation(),))


def tool() -> ModelToolDefinition:
    return ModelToolDefinition(
        tool_name="get_synthetic_record",
        version="1.0.0",
        input_schema=MappingProxyType(
            {
                "type": "object",
                "properties": {"record_id": {"type": "string"}},
                "required": ["record_id"],
                "additionalProperties": False,
            }
        ),
    )


def turn(
    mode: ToolSelectionMode,
    interactions: tuple[ModelToolInteraction, ...] = (),
) -> ModelTurnRequest:
    selected = mode is ToolSelectionMode.REQUIRED_EXACT_TOOL
    return ModelTurnRequest(
        policy_instructions=("Use only validated evidence.",),
        user_message="Synthetic question.",
        response_language="en",
        tools=(tool(),) if selected else (),
        tool_selection=ModelToolSelection(
            mode=mode,
            tool_name=tool().tool_name if selected else None,
            version=tool().version if selected else None,
        ),
        interactions=interactions,
        turn_number=2 if interactions else 1,
        routing_customer_environment_id="customer-alpha",
        maximum_data_classification=DataClassification.RESTRICTED,
        purpose="employee_self_service",
    )


def response(value: object, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        content=json.dumps(value, separators=(",", ":")).encode(),
        headers={"content-type": "application/json", "content-encoding": "identity"},
    )


def final_response() -> dict[str, object]:
    final = {
        "response_type": "final_answer",
        "answer": "Synthetic answer.",
        "answer_basis": "general",
        "evidence_call_ids": [],
        "citation_ids": [],
    }
    return {
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


def test_config_is_strict_immutable_repr_safe_and_unique() -> None:
    configuration = config()
    assert "customer-alpha" not in repr(configuration)
    assert "proj_alpha" not in repr(configuration)
    with pytest.raises(ValidationError):
        configuration.routes = ()  # type: ignore[misc]
    with pytest.raises(ValidationError):
        OpenAIProjectRoute.model_validate({**route().model_dump(), "extra": True}, strict=True)
    with pytest.raises(ValidationError, match="duplicate"):
        OpenAIProductionConfig(routes=(route(), route()), attestations=(attestation(),))
    second = route(customer="customer-beta", project_id="proj_alpha")
    with pytest.raises(ValidationError, match="duplicate"):
        OpenAIProductionConfig(routes=(route(), second), attestations=(attestation(),))
    for model in ("gpt-5.1", "gpt-5.1-latest", "LATEST"):
        with pytest.raises(ValidationError):
            OpenAIProjectRoute.model_validate(
                {**route().model_dump(mode="python"), "chat_model": model}, strict=True
            )


def test_privacy_attestation_is_zdr_only_and_time_bound() -> None:
    values = attestation().model_dump(mode="python")
    with pytest.raises(ValidationError):
        OpenAIProjectPrivacyAttestation.model_validate(
            {**values, "retention_mode": "standard"}, strict=True
        )
    with pytest.raises(ValidationError):
        OpenAIProjectPrivacyAttestation.model_validate(
            {**values, "allowed_purposes": "employee_self_service"}, strict=True
        )
    with pytest.raises(ValidationError, match="duplicate"):
        OpenAIProjectPrivacyAttestation.model_validate(
            {
                **values,
                "allowed_purposes": (
                    "employee_self_service",
                    "employee_self_service",
                ),
            },
            strict=True,
        )
    for changes in (
        {"approved_at": NOW.replace(tzinfo=None)},
        {"expires_at": NOW.replace(tzinfo=None)},
        {"expires_at": values["approved_at"]},
    ):
        with pytest.raises(ValidationError):
            OpenAIProjectPrivacyAttestation.model_validate({**values, **changes}, strict=True)


def test_internal_routing_fields_are_repr_hidden_and_construct_bypass_fails() -> None:
    valid = turn(ToolSelectionMode.NO_TOOLS)
    rendered = repr(valid)
    assert "customer-alpha" not in rendered
    assert "employee_self_service" not in rendered
    assert "restricted" not in rendered

    malformed = ModelTurnRequest.model_construct(
        **{
            **valid.model_dump(mode="python"),
            "routing_customer_environment_id": "bad customer",
            "maximum_data_classification": "public",
            "purpose": "BAD PURPOSE",
        }
    )
    bundle = build_openai_production_bundle(
        config=config(),
        credential_provider=Credentials(),
        clock=Clock(),
        ssl_context=ssl_context(),
        _transport_factory=TransportFactory(lambda _: response(final_response())),
    )

    async def exercise() -> None:
        await bundle.lifecycle.open()
        with pytest.raises(OpenAIProviderUnavailable) as error:
            await bundle.model_provider.complete_turn(malformed)
        assert "bad customer" not in str(error.value)
        assert "BAD PURPOSE" not in str(error.value)
        await bundle.lifecycle.close()

    asyncio.run(exercise())


def test_route_and_catalog_collection_validation_is_fail_closed() -> None:
    values = route().model_dump(mode="python")
    with pytest.raises(ValidationError):
        OpenAIProjectRoute.model_validate(
            {**values, "allowed_purposes": "employee_self_service"}, strict=True
        )
    with pytest.raises(ValidationError, match="duplicate"):
        OpenAIProjectRoute.model_validate(
            {
                **values,
                "allowed_purposes": (
                    "employee_self_service",
                    "employee_self_service",
                ),
            },
            strict=True,
        )
    other_attestation = attestation(policy_id="privacy-policy-b")
    with pytest.raises(ValidationError, match="duplicate privacy"):
        OpenAIProductionConfig(routes=(route(),), attestations=(attestation(), attestation()))
    with pytest.raises(ValidationError, match="binding"):
        OpenAIProductionConfig(routes=(route(),), attestations=(other_attestation,))


def test_strict_json_rejects_duplicate_keys_nonfinite_and_invalid_utf8() -> None:
    assert strict_json_loads(b'{"value":1}') == {"value": 1}
    for raw in (b'{"value":1,"value":2}', b'{"value":NaN}', b"\xff"):
        with pytest.raises((ValueError, UnicodeDecodeError)):
            strict_json_loads(raw)
    values = attestation().model_dump(mode="python")
    with pytest.raises(ValidationError):
        OpenAIProjectPrivacyAttestation.model_validate(
            {**values, "training_data_sharing_opt_in": True}, strict=True
        )
    with pytest.raises(ValidationError):
        OpenAIProjectPrivacyAttestation.model_validate(
            {**values, "allowed_endpoints": (OPENAI_RESPONSES_PATH,)}, strict=True
        )
    with pytest.raises(ValidationError):
        OpenAIProjectPrivacyAttestation.model_validate(
            {
                **values,
                "allowed_data_classifications": (DataClassification.HIGHLY_RESTRICTED,),
            },
            strict=True,
        )


@pytest.mark.parametrize(
    ("value", "schema", "expected"),
    (
        ({}, None, False),
        ([], {"type": "object", "properties": {}, "required": []}, False),
        ({}, {"type": "object", "properties": [], "required": []}, False),
        ({"extra": 1}, {"type": "object", "properties": {}, "required": []}, False),
        (
            {},
            {
                "type": "object",
                "properties": {"x": {"type": "string"}},
                "required": ["x"],
                "additionalProperties": False,
            },
            False,
        ),
        (["x"], {"type": "array", "items": {"type": "string"}}, True),
        ("x", {"type": "string"}, True),
        (1, {"type": "integer"}, True),
        (True, {"type": "integer"}, False),
        (1.0, {"type": "number"}, True),
        (False, {"type": "boolean"}, True),
        (None, {"type": "null"}, True),
        ("x", {"type": "unsupported"}, False),
    ),
)
def test_strict_tool_schema_values_are_type_sensitive(
    value: object, schema: object, expected: bool
) -> None:
    assert _strict_schema_value(value, schema) is expected


def test_unknown_expired_future_and_highly_restricted_deny_before_credentials() -> None:
    credentials = Credentials()
    bundle = build_openai_production_bundle(
        config=config(),
        credential_provider=credentials,
        clock=Clock(),
        ssl_context=ssl_context(),
    )
    with pytest.raises(OpenAIPrivacyDenied):
        bundle.router.authorize(
            "unknown", DataClassification.RESTRICTED, "employee_self_service", OPENAI_RESPONSES_PATH
        )
    with pytest.raises(OpenAIPrivacyDenied):
        bundle.router.authorize(
            "customer-alpha",
            DataClassification.HIGHLY_RESTRICTED,
            "employee_self_service",
            OPENAI_RESPONSES_PATH,
        )
    assert credentials.calls == []

    with pytest.raises(TypeError):
        build_openai_production_bundle(
            config=config(),
            credential_provider=credentials,
            clock=object(),  # type: ignore[arg-type]
            ssl_context=ssl_context(),
        )

    for invalid in (
        attestation(expires_at=NOW - timedelta(seconds=1)),
        attestation(approved_at=NOW + timedelta(seconds=1)),
    ):
        denied = build_openai_production_bundle(
            config=OpenAIProductionConfig(routes=(route(),), attestations=(invalid,)),
            credential_provider=credentials,
            clock=Clock(),
            ssl_context=ssl_context(),
        )
        with pytest.raises(OpenAIPrivacyDenied):
            denied.router.authorize(
                "customer-alpha",
                DataClassification.RESTRICTED,
                "employee_self_service",
                OPENAI_RESPONSES_PATH,
            )


def test_general_request_is_minimized_and_response_is_strict() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return response(final_response())

    bundle = build_openai_production_bundle(
        config=config(),
        credential_provider=Credentials(),
        clock=Clock(),
        ssl_context=ssl_context(),
        _transport_factory=TransportFactory(handler),
    )

    async def exercise() -> None:
        await bundle.lifecycle.open()
        result = await bundle.model_provider.complete_turn(turn(ToolSelectionMode.NO_TOOLS))
        assert isinstance(result, ModelFinalAnswer)
        assert result.answer_basis is AnswerBasis.GENERAL
        await bundle.lifecycle.close()

    asyncio.run(exercise())
    request = captured[0]
    assert str(request.url) == f"{OPENAI_ORIGIN}{OPENAI_RESPONSES_PATH}"
    assert request.headers["openai-project"] == "proj_alpha"
    assert request.headers["accept-encoding"] == "identity"
    payload = json.loads(request.content)
    assert payload["store"] is False
    assert payload["stream"] is False
    assert payload["background"] is False
    assert payload["parallel_tool_calls"] is False
    assert payload["tools"] == [] and payload["tool_choice"] == "none"
    wire = request.content.decode()
    for forbidden in (
        "customer-alpha",
        "employee",
        "authorization_snapshot",
        "permission",
        "enabled_modules",
        "prompt_cache",
    ):
        assert forbidden not in wire


def test_forced_call_and_final_transcript_are_exact_and_adjacent() -> None:
    payloads: list[dict[str, object]] = []
    replies = [
        {
            "model": CHAT_MODEL,
            "status": "completed",
            "background": False,
            "output": [
                {
                    "type": "function_call",
                    "call_id": "call_synthetic",
                    "name": "get_synthetic_record",
                    "arguments": '{ "record_id": "synthetic-1" }',
                    "status": "completed",
                }
            ],
        },
        {
            **final_response(),
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(
                                {
                                    "response_type": "final_answer",
                                    "answer": "Synthetic record.",
                                    "answer_basis": "erp_data",
                                    "evidence_call_ids": ["call_synthetic"],
                                    "citation_ids": [],
                                }
                            ),
                        }
                    ],
                }
            ],
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return response(replies.pop(0))

    bundle = build_openai_production_bundle(
        config=config(),
        credential_provider=Credentials(),
        clock=Clock(),
        ssl_context=ssl_context(),
        _transport_factory=TransportFactory(handler),
    )

    async def exercise() -> None:
        await bundle.lifecycle.open()
        call = await bundle.model_provider.complete_turn(
            turn(ToolSelectionMode.REQUIRED_EXACT_TOOL)
        )
        assert isinstance(call, ModelToolCall)
        result = PublicToolSuccess(
            tool_name=call.tool_name,
            version=call.version,
            result=SyntheticSafeResult(value="synthetic"),
        )
        interaction = ModelToolInteraction(
            assistant_call=call,
            tool_result=ToolResultMessage(
                call_id=call.call_id, tool_name=call.tool_name, result=result
            ),
        )
        final = await bundle.model_provider.complete_turn(
            turn(ToolSelectionMode.FINAL_ONLY, (interaction,))
        )
        assert isinstance(final, ModelFinalAnswer)
        await bundle.lifecycle.close()

    asyncio.run(exercise())
    first = payloads[0]
    assert first["tool_choice"] == {"type": "function", "name": "get_synthetic_record"}
    assert len(first["tools"]) == 1  # type: ignore[arg-type]
    replay = payloads[1]["input"]
    assert replay[2]["arguments"] == '{ "record_id": "synthetic-1" }'  # type: ignore[index]
    assert replay[2]["call_id"] == replay[3]["call_id"]  # type: ignore[index]
    assert payloads[1]["tools"] == [] and payloads[1]["tool_choice"] == "none"


@pytest.mark.parametrize(
    "output",
    (
        [],
        [{"type": "refusal"}],
        [
            {
                "type": "function_call",
                "call_id": "call",
                "name": "wrong_tool",
                "arguments": "{}",
                "status": "completed",
            }
        ],
        [
            {
                "type": "function_call",
                "call_id": "call",
                "name": "get_synthetic_record",
                "arguments": '{"record_id":1}',
                "status": "completed",
            }
        ],
    ),
)
def test_invalid_forced_outputs_fail_closed(output: list[object]) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return response(
            {"model": CHAT_MODEL, "status": "completed", "background": False, "output": output}
        )

    bundle = build_openai_production_bundle(
        config=config(),
        credential_provider=Credentials(),
        clock=Clock(),
        ssl_context=ssl_context(),
        _transport_factory=TransportFactory(handler),
    )

    async def exercise() -> None:
        await bundle.lifecycle.open()
        with pytest.raises(OpenAIProviderUnavailable):
            await bundle.model_provider.complete_turn(turn(ToolSelectionMode.REQUIRED_EXACT_TOOL))
        await bundle.lifecycle.close()

    asyncio.run(exercise())


def embedding_request() -> EmbeddingBatchRequest:
    profile = EmbeddingProfile(
        contract_version=1,
        profile_id="openai_prod",
        provider_id="openai",
        model_id=EMBEDDING_MODEL,
        model_revision="deployment-eval-revision-1",
        dimensions=3,
        distance_metric=EmbeddingDistanceMetric.COSINE,
        storage_representation=EmbeddingStorageRepresentation.FLOAT32,
        input_normalization_version=1,
        document_transform_version=1,
        query_transform_version=1,
        query_instruction="Retrieve synthetic policy text.",
        allowed_data_classifications=(DataClassification.RESTRICTED,),
    )
    return EmbeddingBatchRequest(
        profile=profile,
        inputs=(
            EmbeddingInput(
                input_id="query-1",
                text="Synthetic query.",
                content_sha256=hashlib.sha256(b"Synthetic query.").hexdigest(),
                data_classification=DataClassification.RESTRICTED,
                input_kind=EmbeddingInputKind.QUERY,
            ),
        ),
    )


def test_embedding_request_is_minimized_and_exactly_validated() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return response(
            {
                "model": EMBEDDING_MODEL,
                "data": [{"object": "embedding", "index": 0, "embedding": [1.0, 0.0, 0.0]}],
            }
        )

    bundle = build_openai_production_bundle(
        config=config(),
        credential_provider=Credentials(),
        clock=Clock(),
        ssl_context=ssl_context(),
        _transport_factory=TransportFactory(handler),
    )

    async def exercise() -> None:
        await bundle.lifecycle.open()
        provider = bundle.embedding_provider("customer-alpha", "employee_self_service")
        result = await provider.embed(embedding_request())
        assert result.vectors[0].values == (1.0, 0.0, 0.0)
        await bundle.lifecycle.close()

    asyncio.run(exercise())
    payload = json.loads(captured[0].content)
    assert payload == {
        "model": EMBEDDING_MODEL,
        "input": "Instruct: Retrieve synthetic policy text.\nQuery: Synthetic query.",
        "dimensions": 3,
        "encoding_format": "float",
    }
    assert "customer-alpha" not in captured[0].content.decode()


@pytest.mark.parametrize(
    "embedding",
    ([], [0.0, 0.0, 0.0], [True, 0.0, 0.0], [float("nan"), 0.0, 0.0]),
)
def test_embedding_invalid_values_fail_closed(embedding: list[object]) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return response(
            {
                "model": EMBEDDING_MODEL,
                "data": [{"object": "embedding", "index": 0, "embedding": embedding}],
            }
        )

    bundle = build_openai_production_bundle(
        config=config(),
        credential_provider=Credentials(),
        clock=Clock(),
        ssl_context=ssl_context(),
        _transport_factory=TransportFactory(handler),
    )

    async def exercise() -> None:
        await bundle.lifecycle.open()
        with pytest.raises(OpenAIProviderUnavailable):
            await bundle.embedding_provider("customer-alpha", "employee_self_service").embed(
                embedding_request()
            )
        await bundle.lifecycle.close()

    asyncio.run(exercise())


def test_lifecycle_is_concurrency_safe_and_irreversible() -> None:
    bundle = build_openai_production_bundle(
        config=config(),
        credential_provider=Credentials(),
        clock=Clock(),
        ssl_context=ssl_context(),
        _transport_factory=TransportFactory(lambda _: response(final_response())),
    )

    async def exercise() -> None:
        await asyncio.gather(bundle.lifecycle.open(), bundle.lifecycle.open())
        await asyncio.gather(bundle.lifecycle.close(), bundle.lifecycle.close())
        with pytest.raises(OpenAIProviderUnavailable):
            await bundle.lifecycle.open()
        with pytest.raises(OpenAIProviderUnavailable):
            await bundle.model_provider.complete_turn(turn(ToolSelectionMode.NO_TOOLS))

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "provider_response",
    (
        httpx.Response(401, content=PRIVATE.encode(), headers={"content-type": "text/plain"}),
        httpx.Response(429, content=PRIVATE.encode(), headers={"content-type": "text/plain"}),
        httpx.Response(
            200,
            content=b"{}",
            headers={"content-type": "text/plain", "content-encoding": "identity"},
        ),
        httpx.Response(
            200,
            stream=httpx.ByteStream(b"{}"),
            headers={"content-type": "application/json", "content-encoding": "gzip"},
        ),
        httpx.Response(
            200,
            content=b"{}",
            headers={
                "content-type": "application/json",
                "content-encoding": "identity",
                "set-cookie": f"private={PRIVATE}",
            },
        ),
        httpx.Response(
            200,
            content=b"{}",
            headers={
                "content-type": "application/json; charset=latin-1",
                "content-encoding": "identity",
            },
        ),
    ),
)
def test_http_failures_are_one_attempt_and_contain_provider_data(
    provider_response: httpx.Response,
) -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return provider_response

    bundle = build_openai_production_bundle(
        config=config(),
        credential_provider=Credentials(),
        clock=Clock(),
        ssl_context=ssl_context(),
        _transport_factory=TransportFactory(handler),
    )

    async def exercise() -> None:
        await bundle.lifecycle.open()
        with pytest.raises(OpenAIProviderUnavailable) as error:
            await bundle.model_provider.complete_turn(turn(ToolSelectionMode.NO_TOOLS))
        assert PRIVATE not in str(error.value) and PRIVATE not in repr(error.value)
        await bundle.lifecycle.close()

    asyncio.run(exercise())
    assert attempts == 1


def test_credential_failure_timeout_and_cancellation_are_safe() -> None:
    async def run_case(failure: BaseException, credential_failure: bool) -> None:
        credentials = Credentials(failure if credential_failure else None)

        def handler(_: httpx.Request) -> httpx.Response:
            raise failure

        bundle = build_openai_production_bundle(
            config=config(),
            credential_provider=credentials,
            clock=Clock(),
            ssl_context=ssl_context(),
            _transport_factory=TransportFactory(handler),
        )

        await bundle.lifecycle.open()
        with pytest.raises(OpenAIProviderUnavailable) as error:
            await bundle.model_provider.complete_turn(turn(ToolSelectionMode.NO_TOOLS))
        assert PRIVATE not in str(error.value)
        await bundle.lifecycle.close()

    asyncio.run(run_case(RuntimeError(PRIVATE), True))
    asyncio.run(run_case(httpx.ReadTimeout(PRIVATE), False))

    cancelled = build_openai_production_bundle(
        config=config(),
        credential_provider=Credentials(asyncio.CancelledError()),
        clock=Clock(),
        ssl_context=ssl_context(),
        _transport_factory=TransportFactory(lambda _: response(final_response())),
    )

    async def cancel() -> None:
        await cancelled.lifecycle.open()
        with pytest.raises(asyncio.CancelledError):
            await cancelled.model_provider.complete_turn(turn(ToolSelectionMode.NO_TOOLS))
        await cancelled.lifecycle.close()

    asyncio.run(cancel())


@pytest.mark.parametrize(
    "credential",
    (
        "plain-string",
        SecretStr(""),
        SecretStr(" leading"),
        SecretStr("trailing "),
        SecretStr("embedded space"),
        SecretStr("line\nbreak"),
        SecretStr("nul\x00byte"),
        SecretStr("x" * 4097),
    ),
)
def test_credential_results_are_strictly_revalidated(credential: object) -> None:
    provider = InvalidCredentials(credential)
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return response(final_response())

    bundle = build_openai_production_bundle(
        config=config(),
        credential_provider=provider,
        clock=Clock(),
        ssl_context=ssl_context(),
        _transport_factory=TransportFactory(handler),
    )

    async def exercise() -> None:
        await bundle.lifecycle.open()
        with pytest.raises(OpenAIProviderUnavailable):
            await bundle.model_provider.complete_turn(turn(ToolSelectionMode.NO_TOOLS))
        await bundle.lifecycle.close()

    asyncio.run(exercise())
    assert provider.calls == 1
    assert attempts == 0


def test_attestation_is_revalidated_at_every_request_and_has_bounded_lifetime() -> None:
    clock = Clock(NOW)
    credentials = Credentials()
    bundle = build_openai_production_bundle(
        config=config(),
        credential_provider=credentials,
        clock=clock,
        ssl_context=ssl_context(),
        _transport_factory=TransportFactory(lambda _: response(final_response())),
    )

    async def exercise() -> None:
        await bundle.lifecycle.open()
        await bundle.model_provider.complete_turn(turn(ToolSelectionMode.NO_TOOLS))
        clock.value = NOW + timedelta(days=30)
        with pytest.raises(OpenAIProviderUnavailable):
            await bundle.model_provider.complete_turn(turn(ToolSelectionMode.NO_TOOLS))
        await bundle.lifecycle.close()

    asyncio.run(exercise())
    assert clock.calls == 2
    assert len(credentials.calls) == 1

    excessive_route = route().model_copy(update={"maximum_attestation_lifetime_seconds": 60})
    excessive = OpenAIProductionConfig(routes=(excessive_route,), attestations=(attestation(),))
    denied = build_openai_production_bundle(
        config=excessive,
        credential_provider=credentials,
        clock=Clock(),
        ssl_context=ssl_context(),
        _transport_factory=TransportFactory(lambda _: response(final_response())),
    )

    async def reject() -> None:
        await denied.lifecycle.open()
        with pytest.raises(OpenAIProviderUnavailable):
            await denied.model_provider.complete_turn(turn(ToolSelectionMode.NO_TOOLS))
        await denied.lifecycle.close()

    asyncio.run(reject())


@pytest.mark.parametrize(
    "payload",
    (
        {**final_response(), "model": "wrong-2026-01-01"},
        {**final_response(), "status": "incomplete"},
        {**final_response(), "background": True},
        {**final_response(), "output": []},
        {**final_response(), "output": [{"type": "refusal"}]},
        {
            **final_response(),
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "refusal", "refusal": PRIVATE}],
                }
            ],
        },
    ),
)
def test_invalid_response_shapes_are_contained(payload: dict[str, object]) -> None:
    bundle = build_openai_production_bundle(
        config=config(),
        credential_provider=Credentials(),
        clock=Clock(),
        ssl_context=ssl_context(),
        _transport_factory=TransportFactory(lambda _: response(payload)),
    )

    async def exercise() -> None:
        await bundle.lifecycle.open()
        with pytest.raises(OpenAIProviderUnavailable) as error:
            await bundle.model_provider.complete_turn(turn(ToolSelectionMode.NO_TOOLS))
        assert PRIVATE not in str(error.value)
        await bundle.lifecycle.close()

    asyncio.run(exercise())


def test_invalid_tls_policy_and_calls_outside_readiness_fail_closed() -> None:
    invalid = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    invalid.check_hostname = False
    invalid.verify_mode = ssl.CERT_NONE
    bundle = build_openai_production_bundle(
        config=config(),
        credential_provider=Credentials(),
        clock=Clock(),
        ssl_context=invalid,
        _transport_factory=TransportFactory(lambda _: response(final_response())),
    )

    async def exercise() -> None:
        with pytest.raises(OpenAIProviderUnavailable):
            await bundle.model_provider.complete_turn(turn(ToolSelectionMode.NO_TOOLS))
        with pytest.raises(OpenAIProviderUnavailable):
            await bundle.lifecycle.open()

    asyncio.run(exercise())
