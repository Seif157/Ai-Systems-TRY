"""Required-mode live PostgreSQL proof for the complete production composition root."""

import base64
import json
import ssl
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from pydantic import BaseModel, ConfigDict, SecretBytes, SecretStr

from erp_ai.api import PublicChatRequest
from erp_ai.application import TrustedRouteCatalog, TrustedRouteEntry
from erp_ai.capabilities import CapabilityManifest, CapabilityRegistry, ToolDescriptor
from erp_ai.context import TrustedRequestContext
from erp_ai.infrastructure.erp_trust import (
    ErpAssertionVerificationKey,
    ErpAssertionVerifierConfig,
    ErpTrustHttpClient,
    ErpTrustHttpConfig,
)
from erp_ai.infrastructure.postgres_audit import RuntimeAuditDatabaseConfig
from erp_ai.orchestration import (
    AgentLimits,
    AgentRouteMode,
    AgentRoutingPolicy,
    AnswerBasis,
    ModelFinalAnswer,
    ModelToolCall,
    ModelTurnRequest,
    ToolSelectionMode,
)
from erp_ai.runtime import (
    ExternalRuntimeBundle,
    ProviderLifecycleLease,
    RuntimeState,
    compose_production_runtime,
)
from erp_ai.transport.http import InternalHttpTransportConfig, canonical_public_chat_digest
from tests.integration.test_postgres_audit_storage import _prepare, _required, _run

pytestmark = pytest.mark.postgres
NOW = datetime(2026, 8, 27, 12, tzinfo=UTC)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class AsyncBody(httpx.AsyncByteStream):
    def __init__(self, value: bytes) -> None:
        self.value = value

    async def __aiter__(self):  # type: ignore[no-untyped-def]
        yield self.value


class SyntheticOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    value: str


class SyntheticHandler:
    tool_name = "synthetic_read"
    version = "1.0.0"
    input_model = EmptyInput
    output_model = SyntheticOutput

    async def execute(
        self, context: TrustedRequestContext, arguments: BaseModel
    ) -> SyntheticOutput:
        return SyntheticOutput(value=f"synthetic:{context.employee_id}")


class SyntheticModel:
    async def complete_turn(self, request: ModelTurnRequest) -> ModelFinalAnswer | ModelToolCall:
        if request.tool_selection.mode is ToolSelectionMode.REQUIRED_EXACT_TOOL:
            return ModelToolCall.from_arguments(
                call_id="synthetic_call", tool_name="synthetic_read", version="1.0.0", arguments={}
            )
        if request.interactions:
            return ModelFinalAnswer(
                answer="Synthetic structured result.",
                answer_basis=AnswerBasis.ERP_DATA,
                evidence_call_ids=("synthetic_call",),
                citation_ids=(),
            )
        return ModelFinalAnswer(
            answer="Synthetic general result.",
            answer_basis=AnswerBasis.GENERAL,
            evidence_call_ids=(),
            citation_ids=(),
        )


class ProviderLifecycle:
    def __init__(self) -> None:
        self.opened = False
        self.closed = False

    async def open(self) -> None:
        self.opened = True

    async def close(self) -> None:
        self.closed = True
        self.opened = False


class Clock:
    def now(self) -> datetime:
        return NOW


class RequestIds:
    def create(self) -> str:
        return str(uuid4())


def _assertion(private: Ed25519PrivateKey, resolver_ref: str, body_digest: str) -> str:
    header = {"alg": "EdDSA", "kid": "test_key", "typ": "erp-ai-request+jws"}
    payload = {
        "v": 1,
        "iss": "synthetic-erp",
        "aud": "synthetic-ai",
        "jti": str(uuid4()),
        "iat": int(NOW.timestamp()),
        "exp": int(NOW.timestamp()) + 60,
        "method": "POST",
        "path": "/v1/chat",
        "body_sha256": body_digest,
        "resolver_ref": resolver_ref,
    }
    first = _b64(json.dumps(header, separators=(",", ":")).encode())
    second = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{first}.{second}".encode()
    return f"{first}.{second}.{_b64(private.sign(signing_input))}"


async def _counts(admin_dsn: str, database: str) -> tuple[int, int, int]:
    values = conninfo_to_dict(admin_dsn)
    values["dbname"] = database
    async with await psycopg.AsyncConnection.connect(make_conninfo(**values)) as connection:
        result: list[int] = []
        for table in ("application_events", "agent_events", "tool_events"):
            exists = await (
                await connection.execute("SELECT to_regclass(%s)", (f"erp_ai_audit.{table}",))
            ).fetchone()
            if exists == (None,):
                result.append(0)
            else:
                row = await (
                    await connection.execute(
                        sql.SQL("SELECT count(*) FROM erp_ai_audit.{}").format(
                            sql.Identifier(table)
                        )
                    )
                ).fetchone()
                result.append(row[0])
        return tuple(result)  # type: ignore[return-value]


async def _exercise(monkeypatch: pytest.MonkeyPatch) -> None:
    admin_dsn = _required()
    static_config, databases = await _prepare(admin_dsn)
    audit_config = RuntimeAuditDatabaseConfig.from_static(static_config)
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    scopes = {
        _b64(b"g" * 32): ("customer_1", "general"),
        _b64(b"a" * 32): ("customer_1", "exact_read"),
        _b64(b"b" * 32): ("customer_2", "exact_read"),
    }

    async def erp_handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        request_id = payload["request_id"]
        if request.url.path.endswith("/resolve"):
            customer, intent = scopes[payload["resolver_reference"]]
            response = {
                "contract_version": 1,
                "request_id": request_id,
                "trusted_request_context": {
                    "context_version": 1,
                    "request_id": request_id,
                    "customer_environment_id": customer,
                    "user_id": "same_user",
                    "employee_id": "same_employee",
                    "roles": ["employee"],
                    "permission_codes": ["synthetic.read"],
                    "legal_entity_ids": ["same_entity"],
                    "enabled_modules": ["synthetic"],
                    "locale": "en",
                    "timezone": "Africa/Cairo",
                    "purpose": "test",
                    "issued_at": NOW.isoformat(),
                    "authorization_snapshot_id": "same_snapshot",
                },
                "trusted_route_intent": {
                    "intent_contract_version": 1,
                    "intent_code": intent,
                    "issued_at": NOW.isoformat(),
                    "expires_at": (NOW + timedelta(seconds=30)).isoformat(),
                    "request_id": request_id,
                    "customer_environment_id": customer,
                    "user_id": "same_user",
                    "authorization_snapshot_id": "same_snapshot",
                },
            }
        else:
            response = {"contract_version": 1, **payload, "status": "current"}
        return httpx.Response(
            200,
            stream=AsyncBody(json.dumps(response, separators=(",", ":")).encode()),
            headers={"content-type": "application/json"},
        )

    def client_factory(config: ErpTrustHttpConfig, context: ssl.SSLContext) -> ErpTrustHttpClient:
        return ErpTrustHttpClient(config, context, test_transport=httpx.MockTransport(erp_handler))

    monkeypatch.setattr("erp_ai.runtime.composition.ErpTrustHttpClient", client_factory)
    descriptor = ToolDescriptor(
        tool_name="synthetic_read",
        version="1.0.0",
        operation="read",
        required_permissions_all=("synthetic.read",),
        required_roles_any=(),
        allowed_purposes=("test",),
        data_classification="internal",
        audit_action="synthetic.read",
        requires_employee_context=True,
    )
    registry = CapabilityRegistry(
        (
            CapabilityManifest(
                capability_code="synthetic",
                version="1.0.0",
                required_modules=("synthetic",),
                tools=(descriptor,),
            ),
        )
    )
    provider_lifecycle = ProviderLifecycle()
    bundle = ExternalRuntimeBundle(
        transport_config=InternalHttpTransportConfig(allowed_hosts=("ai.internal",)),
        assertion_config=ErpAssertionVerifierConfig(
            issuer=SecretStr("synthetic-erp"),
            audience=SecretStr("synthetic-ai"),
            keys=(
                ErpAssertionVerificationKey(
                    kid="test_key",
                    public_key=SecretBytes(public),
                    activates_at=NOW - timedelta(hours=1),
                    retires_at=NOW + timedelta(hours=1),
                ),
            ),
            maximum_lifetime=timedelta(seconds=60),
            maximum_clock_skew=timedelta(seconds=5),
        ),
        erp_trust_config=ErpTrustHttpConfig(
            origin=SecretStr("https://erp.invalid"),
            connect_timeout_seconds=1.0,
            read_timeout_seconds=1.0,
            write_timeout_seconds=1.0,
            pool_timeout_seconds=1.0,
            maximum_connections=2,
            maximum_keepalive_connections=1,
            maximum_response_bytes=16_384,
        ),
        erp_ssl_context=ssl.create_default_context(),
        audit_config=audit_config,
        route_catalog=TrustedRouteCatalog(
            (
                TrustedRouteEntry(
                    intent_code="general",
                    route=AgentRoutingPolicy(mode=AgentRouteMode.GENERAL_ONLY),
                ),
                TrustedRouteEntry(
                    intent_code="exact_read",
                    route=AgentRoutingPolicy(
                        mode=AgentRouteMode.EXACT_READ_THEN_FINAL,
                        tool_name="synthetic_read",
                        version="1.0.0",
                    ),
                ),
            )
        ),
        registry=registry,
        handlers=(SyntheticHandler(),),
        model_provider=SyntheticModel(),
        provider_lifecycle_lease=ProviderLifecycleLease(provider_lifecycle),
        agent_limits=AgentLimits(),
        maximum_intent_lifetime=timedelta(minutes=1),
        request_id_factory=RequestIds(),
        clock=Clock(),
    )
    runtime = compose_production_runtime(bundle)
    assert runtime.state is RuntimeState.CREATED
    request = PublicChatRequest(message="Synthetic request")
    body = request.model_dump_json(exclude_none=True).encode()
    digest = canonical_public_chat_digest(request)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=runtime.application),
        base_url="https://ai.internal",
    ) as client:
        assert (await client.get("/health/ready")).status_code == 503
        async with runtime.application.router.lifespan_context(runtime.application):
            assert runtime.state is RuntimeState.READY
            assert (await client.get("/health/ready")).status_code == 204
            invalid = await client.post(
                "/v1/chat",
                content=body,
                headers={"content-type": "application/json", "authorization": "Bearer invalid"},
            )
            assert invalid.status_code == 401
            for resolver_ref in scopes:
                assertion = _assertion(private, resolver_ref, digest)
                response = await client.post(
                    "/v1/chat",
                    content=body,
                    headers={
                        "content-type": "application/json",
                        "authorization": f"Bearer {assertion}",
                    },
                )
                assert response.status_code == 200, response.text
                UUID(response.headers["x-request-id"])
        assert runtime.state is RuntimeState.CLOSED
        assert (await client.get("/health/ready")).status_code == 503
        after = await client.post(
            "/v1/chat",
            content=body,
            headers={"content-type": "application/json", "authorization": "Bearer invalid"},
        )
        assert after.status_code == 503

    assert provider_lifecycle.closed
    assert await _counts(admin_dsn, databases[0]) == (4, 0, 0)
    assert await _counts(admin_dsn, databases[1]) == (0, 2, 1)
    assert await _counts(admin_dsn, databases[2]) == (0, 1, 1)
    assert "migration_dsn" not in repr(runtime) + str(runtime)


def test_live_production_runtime_composition(monkeypatch: pytest.MonkeyPatch) -> None:
    _run(_exercise(monkeypatch))
