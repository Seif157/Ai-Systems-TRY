"""Opt-in installed-image rehearsal of the complete production composition root."""

import asyncio
import base64
import hashlib
import json
import os
import selectors
import socket
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key
from cryptography.x509.oid import NameOID
from psycopg import sql
from psycopg.conninfo import make_conninfo

from erp_ai.api import PublicChatRequest
from erp_ai.application import TrustedRouteEntry
from erp_ai.capabilities import DataClassification
from erp_ai.infrastructure.laravel_erp import (
    LARAVEL_ERP_READ_CONTRACT_DIGEST,
    LARAVEL_ERP_READ_SERVICE_IDENTITY,
)
from erp_ai.infrastructure.openai import (
    OPENAI_ALLOWED_ENDPOINTS,
    OpenAIProductionConfig,
    OpenAIProjectPrivacyAttestation,
    OpenAIProjectRoute,
    OpenAIRequestLimits,
)
from erp_ai.infrastructure.postgres import (
    KNOWLEDGE_READ_CONTRACT_DIGEST,
    KNOWLEDGE_READ_CONTRACT_VERSION,
    KnowledgeDatabaseRouteConfig,
    PostgresEmbeddingRepository,
    PostgresKnowledgeIndexRepository,
    ProductionKnowledgeRoute,
    SemanticRetrievalPolicy,
    StaticKnowledgeDatabaseConfig,
    StaticKnowledgeDatabaseRouter,
)
from erp_ai.infrastructure.postgres.migrations import (
    grant_runtime_roles as grant_knowledge_roles,
)
from erp_ai.infrastructure.postgres.migrations import (
    provision_database_identity as provision_knowledge_identity,
)
from erp_ai.infrastructure.postgres.migrations import run_migrations as run_knowledge_migrations
from erp_ai.infrastructure.postgres_audit import AuditDatabaseKind
from erp_ai.infrastructure.postgres_audit.migrations import grant_writer_role
from erp_ai.infrastructure.postgres_audit.migrations import (
    provision_identity as provision_audit_identity,
)
from erp_ai.infrastructure.postgres_audit.migrations import run_migrations as run_audit_migrations
from erp_ai.knowledge import KnowledgeSourceType
from erp_ai.knowledge.embeddings import (
    EmbeddingBatchRequest,
    EmbeddingBatchResult,
    EmbeddingMaterializer,
    EmbeddingProfile,
    EmbeddingVector,
)
from erp_ai.knowledge.indexing import KnowledgeIndexPublisher
from erp_ai.orchestration import AgentLimits, AgentRouteMode, AgentRoutingPolicy
from erp_ai.transport.http.parsing import canonical_public_chat_digest
from tests.unit.test_knowledge_index_publication import bundle, context

pytestmark = pytest.mark.postgres

CUSTOMER = "synthetic-customer"
EMPLOYEE = "20000000-0000-4000-8000-000000000001"
LEGAL_ENTITY = "30000000-0000-4000-8000-000000000001"
IMAGE = os.getenv("ERP_AI_PRODUCTION_REHEARSAL_IMAGE", "erp-ai-step30:provisional")
REQUIRED = os.getenv("ERP_AI_REQUIRE_PRODUCTION_CONTAINER_REHEARSAL") == "1"


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, text=True, capture_output=True)


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait(predicate, timeout: float = 60) -> None:  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.25)
    raise AssertionError("synthetic dependency did not become ready")


def _internal_http(
    client_container: str,
    method: str,
    path: str,
    body: bytes = b"",
    headers: dict[str, str] | None = None,
) -> tuple[int, bytes]:
    envelope = json.dumps(
        {
            "method": method,
            "path": path,
            "body": base64.b64encode(body).decode("ascii"),
            "headers": headers or {},
        },
        separators=(",", ":"),
    )
    code = (
        "import base64,http.client,json,sys;"
        "v=json.load(sys.stdin);"
        "c=http.client.HTTPConnection('application',8080,timeout=10);"
        "c.request(v['method'],v['path'],base64.b64decode(v['body']),"
        "{'Host':'ai.internal',**v['headers']});"
        "r=c.getresponse();b=r.read();"
        "print(json.dumps({'status':r.status,'body':base64.b64encode(b).decode('ascii')}))"
    )
    completed = subprocess.run(
        ["docker", "exec", "-i", client_container, "/opt/venv/bin/python", "-c", code],
        input=envelope,
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        return 0, b""
    value = json.loads(completed.stdout)
    return int(value["status"]), base64.b64decode(value["body"])


def _application_ready(client_container: str, application_container: str) -> bool:
    state = _run(
        "docker",
        "inspect",
        application_container,
        "--format",
        "{{.State.Running}} {{.State.ExitCode}}",
    ).stdout.strip()
    if state.startswith("false"):
        raise AssertionError(f"installed application exited during startup ({state})")
    return _internal_http(client_container, "GET", "/health/ready")[0] == 204


def _async_run(coroutine):  # type: ignore[no-untyped-def]
    if os.name == "nt":
        with asyncio.Runner(
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())
        ) as runner:
            return runner.run(coroutine)
    return asyncio.run(coroutine)


def _postgres_ready(dsn: str) -> bool:
    try:
        with psycopg.connect(dsn, connect_timeout=1):
            return True
    except psycopg.Error:
        return False


def _database_rows(admin_dsn: str, database: str, statement: str) -> list[tuple[object, ...]]:
    with psycopg.connect(make_conninfo(admin_dsn, dbname=database)) as connection:
        return list(connection.execute(statement).fetchall())


def _container_stopped(container: str) -> bool:
    return (
        _run("docker", "inspect", container, "--format", "{{.State.Running}}").stdout.strip()
        == "false"
    )


def _pem(path: Path, value: bytes) -> None:
    path.write_bytes(value)


def _certificates(root: Path) -> tuple[Path, Path, Path, Path, Path]:
    now = datetime.now(UTC)
    ca_key = generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ERP AI synthetic CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(ca_key, hashes.SHA256())
    )

    def issue(name: str, sans: tuple[str, ...], client: bool) -> tuple[bytes, bytes]:
        key = generate_private_key(public_exponent=65537, key_size=2048)
        builder = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)]))
            .issuer_name(ca.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(hours=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(
                x509.ExtendedKeyUsage(
                    [
                        x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH
                        if client
                        else x509.oid.ExtendedKeyUsageOID.SERVER_AUTH
                    ]
                ),
                critical=True,
            )
        )
        if sans:
            builder = builder.add_extension(
                x509.SubjectAlternativeName([x509.DNSName(item) for item in sans]),
                critical=False,
            )
        certificate = builder.sign(ca_key, hashes.SHA256())
        return (
            certificate.public_bytes(serialization.Encoding.PEM),
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
        )

    server_cert, server_key = issue(
        "synthetic-services", ("synthetic-services", "api.openai.com"), False
    )
    client_cert, client_key = issue("erp-ai-client", (), True)
    paths = tuple(
        root / item for item in ("ca.pem", "server.pem", "server.key", "client.pem", "client.key")
    )
    _pem(paths[0], ca.public_bytes(serialization.Encoding.PEM))
    for path, value in zip(
        paths[1:],
        (server_cert, server_key, client_cert, client_key),
        strict=True,
    ):
        _pem(path, value)
    return paths  # type: ignore[return-value]


async def _create_databases(admin_dsn: str) -> dict[str, str]:
    names = {
        "control": "rehearsal_control",
        "audit": "rehearsal_customer_audit",
        "knowledge": "rehearsal_knowledge",
    }
    roles = {
        "control_owner": "rehearsal_control_owner",
        "audit_owner": "rehearsal_audit_owner",
        "control_writer": "rehearsal_control_writer",
        "audit_writer": "rehearsal_audit_writer",
        "knowledge_reader": "rehearsal_knowledge_reader",
        "knowledge_publisher": "rehearsal_knowledge_publisher",
    }
    async with await psycopg.AsyncConnection.connect(admin_dsn, autocommit=True) as admin:
        for database in names.values():
            await admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s",
                (database,),
            )
            await admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database))
            )
        for role in roles.values():
            await admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))
        for role in roles.values():
            await admin.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN PASSWORD 'synthetic_password' NOSUPERUSER NOBYPASSRLS"
                ).format(sql.Identifier(role))
            )
        await admin.execute(
            sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(names["control"]), sql.Identifier(roles["control_owner"])
            )
        )
        await admin.execute(
            sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(names["audit"]), sql.Identifier(roles["audit_owner"])
            )
        )
        await admin.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(names["knowledge"]))
        )
        for database in names.values():
            await admin.execute(
                sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database))
            )
        for database, role_names in (
            (names["control"], (roles["control_owner"], roles["control_writer"])),
            (names["audit"], (roles["audit_owner"], roles["audit_writer"])),
            (
                names["knowledge"],
                (roles["knowledge_reader"], roles["knowledge_publisher"]),
            ),
        ):
            for role in role_names:
                await admin.execute(
                    sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                        sql.Identifier(database), sql.Identifier(role)
                    )
                )

    def dsn(database: str, user: str, password: str) -> str:
        return make_conninfo(admin_dsn, dbname=database, user=user, password=password)

    for kind, database, owner, writer, identity, customer in (
        (
            AuditDatabaseKind.CONTROL,
            names["control"],
            roles["control_owner"],
            roles["control_writer"],
            "rehearsal-control-id",
            None,
        ),
        (
            AuditDatabaseKind.CUSTOMER,
            names["audit"],
            roles["audit_owner"],
            roles["audit_writer"],
            "rehearsal-audit-id",
            CUSTOMER,
        ),
    ):
        async with await psycopg.AsyncConnection.connect(
            dsn(database, owner, "synthetic_password")
        ) as connection:
            await run_audit_migrations(
                connection,
                kind=kind,
                expected_database_name=database,
                expected_migration_owner=owner,
            )
            await provision_audit_identity(
                connection, kind=kind, database_identity=identity, customer_environment_id=customer
            )
            await grant_writer_role(connection, kind=kind, writer_role=writer)

    knowledge_admin = dsn(names["knowledge"], "postgres", "synthetic_admin")
    async with await psycopg.AsyncConnection.connect(knowledge_admin) as connection:
        await run_knowledge_migrations(connection)
        await provision_knowledge_identity(connection, CUSTOMER)
        await grant_knowledge_roles(
            connection,
            reader_role=roles["knowledge_reader"],
            publisher_role=roles["knowledge_publisher"],
        )
    return {**names, **roles, "admin": admin_dsn}


class _EmbeddingProvider:
    async def embed(self, request: EmbeddingBatchRequest) -> EmbeddingBatchResult:
        return EmbeddingBatchResult(
            profile_sha256=request.profile.profile_sha256,
            vectors=tuple(
                EmbeddingVector(input_id=item.input_id, values=(1.0, 0.0, 0.0))
                for item in request.inputs
            ),
        )


async def _publish_knowledge(
    admin_dsn: str, state: dict[str, str]
) -> tuple[EmbeddingProfile, object, str]:
    def dsn(user: str) -> str:
        return make_conninfo(
            admin_dsn, dbname=state["knowledge"], user=user, password="synthetic_password"
        )

    router = StaticKnowledgeDatabaseRouter(
        StaticKnowledgeDatabaseConfig(
            routes=(
                KnowledgeDatabaseRouteConfig(
                    customer_environment_id=CUSTOMER,
                    reader_dsn=dsn(state["knowledge_reader"]),
                    publisher_dsn=dsn(state["knowledge_publisher"]),
                    migration_dsn=make_conninfo(admin_dsn, dbname=state["knowledge"]),
                ),
            ),
            minimum_pool_size=0,
        )
    )
    profile = EmbeddingProfile(
        contract_version=1,
        profile_id="knowledge_v1",
        provider_id="openai",
        model_id="text-embedding-3-large",
        model_revision="deployment-eval-revision-1",
        dimensions=3,
        distance_metric="cosine",
        storage_representation="float32",
        input_normalization_version=1,
        document_transform_version=1,
        query_transform_version=1,
        query_instruction="Synthetic query instruction",
        allowed_data_classifications=(
            DataClassification.INTERNAL,
            DataClassification.RESTRICTED,
        ),
    )
    prepared = bundle(
        customer=CUSTOMER,
        source_type=KnowledgeSourceType.CUSTOMER_POLICY,
        legal_entities=(LEGAL_ENTITY,),
        content="Synthetic handbook evidence",
        classification=DataClassification.RESTRICTED,
    )
    await router.open()
    try:
        repository = PostgresKnowledgeIndexRepository(router, CUSTOMER)
        publication = await KnowledgeIndexPublisher(repository).publish(
            context(customer=CUSTOMER, installed_modules=("hr_core",)),
            (prepared,),
            expected_active_generation_id=None,
        )
        embeddings = PostgresEmbeddingRepository(router, CUSTOMER)
        source = await embeddings.load_generation_source(
            publication.scope, publication.generation_id
        )
        materialized = await EmbeddingMaterializer(_EmbeddingProvider()).materialize(
            source, profile
        )
        result = await embeddings.persist(
            materialized,
            operation_id="rehearsal-embedding",
            request_id="rehearsal-embedding-request",
            actor_id="rehearsal-admin",
        )
        assert result.embedding_count == len(source.chunks)
        return profile, publication, prepared.chunks[0].citation_id
    finally:
        await router.close()


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _assertion(private: Ed25519PrivateKey, body: bytes, resolver: str) -> str:
    now = int(datetime.now(UTC).timestamp())
    header = {"alg": "EdDSA", "kid": "rehearsal-key", "typ": "erp-ai-request+jws"}
    public = PublicChatRequest.model_validate_json(body, strict=True)
    payload = {
        "v": 1,
        "iss": "synthetic-erp",
        "aud": "synthetic-ai",
        "jti": str(uuid4()),
        "iat": now,
        "exp": now + 60,
        "method": "POST",
        "path": "/v1/chat",
        "body_sha256": canonical_public_chat_digest(public),
        "resolver_ref": resolver,
    }
    first = _b64(json.dumps(header, separators=(",", ":")).encode())
    second = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signed = f"{first}.{second}".encode()
    return f"{first}.{second}.{_b64(private.sign(signed))}"


def test_installed_production_container_rehearsal(tmp_path: Path) -> None:
    if not REQUIRED:
        pytest.skip("installed production-container rehearsal is opt-in")
    suffix = uuid4().hex[:8]
    network = f"erp-ai-rehearsal-{suffix}"
    postgres = f"erp-ai-rehearsal-postgres-{suffix}"
    services = f"erp-ai-rehearsal-services-{suffix}"
    application = f"erp-ai-rehearsal-app-{suffix}"
    partial_application = f"erp-ai-rehearsal-partial-{suffix}"
    postgres_port = _free_port()
    _run("docker", "network", "create", "--internal", network)
    try:
        _run(
            "docker",
            "run",
            "-d",
            "--name",
            postgres,
            "--network",
            network,
            "--network-alias",
            "postgres",
            "-e",
            "POSTGRES_PASSWORD=synthetic_admin",
            "-p",
            f"127.0.0.1:{postgres_port}:5432",
            "pgvector/pgvector:0.8.6-pg17-bookworm@sha256:cf134a767f474095eeba57e0117be8e568e011a63f33fbf252f14c9b760f8e6f",
        )
        # The database alone receives a temporary host-admin path for migrations
        # and post-run assertions. The application remains on the internal network.
        _run("docker", "network", "connect", "bridge", postgres)
        _wait(
            lambda: _run(
                "docker", "exec", postgres, "pg_isready", "-U", "postgres", check=False
            ).returncode
            == 0
        )
        admin_dsn = f"postgresql://postgres:synthetic_admin@127.0.0.1:{postgres_port}/postgres?sslmode=disable"
        _wait(lambda: _postgres_ready(admin_dsn))
        state = _async_run(_create_databases(admin_dsn))
        profile, publication, citation = _async_run(_publish_knowledge(admin_dsn, state))
        ca, _, _, client_cert, client_key = _certificates(tmp_path)
        private = Ed25519PrivateKey.generate()
        public = private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        resolvers = {
            name: _b64(hashlib.sha256(name.encode()).digest())
            for name in ("general", "profile", "knowledge")
        }
        routes_path = tmp_path / "routes.json"
        routes_path.write_text(
            json.dumps({value: key for key, value in resolvers.items()}), encoding="utf-8"
        )
        state_path = tmp_path / "events.jsonl"
        state_path.write_text("", encoding="utf-8")
        service_script = Path(__file__).parents[1] / "support" / "production_rehearsal_service.py"
        _run(
            "docker",
            "run",
            "-d",
            "--name",
            services,
            "--network",
            network,
            "--network-alias",
            "synthetic-services",
            "--network-alias",
            "api.openai.com",
            "-v",
            f"{service_script.resolve()}:/synthetic/service.py:ro",
            "-v",
            f"{tmp_path.resolve()}:/synthetic/data",
            "-e",
            "SYNTHETIC_STATE_PATH=/synthetic/data/events.jsonl",
            "-e",
            "SYNTHETIC_ROUTES_PATH=/synthetic/data/routes.json",
            "-e",
            f"SYNTHETIC_LARAVEL_DIGEST={LARAVEL_ERP_READ_CONTRACT_DIGEST}",
            "-e",
            f"SYNTHETIC_CITATION_ID={citation}",
            "-e",
            "SYNTHETIC_CA_CERT=/synthetic/data/ca.pem",
            "-e",
            "SYNTHETIC_SERVER_CERT=/synthetic/data/server.pem",
            "-e",
            "SYNTHETIC_SERVER_KEY=/synthetic/data/server.key",
            "--entrypoint",
            "/opt/venv/bin/python",
            IMAGE,
            "/synthetic/service.py",
        )
        _wait(lambda: "services.ready" in state_path.read_text(encoding="utf-8"))

        secrets = tmp_path / "secrets"
        (secrets / "config").mkdir(parents=True)
        (secrets / "postgres").mkdir()
        (secrets / "openai").mkdir()
        (secrets / "tls").mkdir()
        for source, target in (
            (ca, "ca.pem"),
            (client_cert, "client.pem"),
            (client_key, "client.key"),
        ):
            (secrets / "tls" / target).write_bytes(source.read_bytes())

        def network_dsn(database: str, user: str) -> str:
            return (
                f"postgresql://{user}:synthetic_password@postgres:5432/{database}?sslmode=disable"
            )

        (secrets / "postgres" / "control.dsn").write_text(
            network_dsn(state["control"], state["control_writer"]), encoding="utf-8"
        )
        (secrets / "postgres" / "audit.dsn").write_text(
            network_dsn(state["audit"], state["audit_writer"]), encoding="utf-8"
        )
        (secrets / "postgres" / "knowledge.dsn").write_text(
            network_dsn(state["knowledge"], state["knowledge_reader"]), encoding="utf-8"
        )
        (secrets / "openai" / "key").write_text("synthetic-openai-key", encoding="utf-8")
        now = datetime.now(UTC)
        limits = OpenAIRequestLimits(
            connect_timeout_seconds=2.0,
            read_timeout_seconds=10.0,
            write_timeout_seconds=2.0,
            pool_timeout_seconds=2.0,
            maximum_request_bytes=131072,
            maximum_response_bytes=131072,
            maximum_input_bytes=65536,
            maximum_input_tokens=16384,
            maximum_output_tokens=4096,
        )
        classifications = (DataClassification.INTERNAL, DataClassification.RESTRICTED)
        purposes = ("employee_self_service", "general")
        openai_route = OpenAIProjectRoute(
            customer_environment_id=CUSTOMER,
            organization_id="synthetic-org",
            project_id="synthetic-project",
            credential_reference="synthetic-credential",
            privacy_attestation_id="synthetic-policy",
            chat_model="gpt-5.1-2025-11-13",
            embedding_model=profile.model_id,
            embedding_revision=profile.model_revision,
            embedding_dimensions=3,
            maximum_attestation_lifetime_seconds=2678400,
            allowed_data_classifications=classifications,
            allowed_purposes=purposes,
            reasoning_effort="none",
            limits=limits,
        )
        attestation = OpenAIProjectPrivacyAttestation(
            organization_id="synthetic-org",
            project_id="synthetic-project",
            retention_mode="zero_data_retention",
            training_data_sharing_opt_in=False,
            allowed_endpoints=OPENAI_ALLOWED_ENDPOINTS,
            allowed_data_classifications=classifications,
            allowed_purposes=purposes,
            approved_at=now - timedelta(days=1),
            expires_at=now + timedelta(days=1),
            policy_id="synthetic-policy",
            policy_digest="a" * 64,
        )
        knowledge_route = ProductionKnowledgeRoute(
            customer_environment_id=CUSTOMER,
            expected_database_name=state["knowledge"],
            expected_database_identity=CUSTOMER,
            runtime_dsn="postgresql://placeholder",
            expected_runtime_role=state["knowledge_reader"],
            expected_extension_owner="postgres",
            knowledge_contract_version=KNOWLEDGE_READ_CONTRACT_VERSION,
            knowledge_contract_digest=KNOWLEDGE_READ_CONTRACT_DIGEST,
            embedding_model_id=profile.model_id,
            embedding_model_version=profile.model_revision,
            embedding_provider_id=profile.provider_id,
            embedding_profile_sha256=profile.profile_sha256,
            embedding_dimensions=3,
            expected_generation_id=publication.generation_id,
            expected_generation_digest=publication.generation_digest,
            minimum_pool_size=0,
            maximum_pool_size=2,
        )
        trusted_routes = (
            TrustedRouteEntry(
                intent_code="general", route=AgentRoutingPolicy(mode=AgentRouteMode.GENERAL_ONLY)
            ),
            TrustedRouteEntry(
                intent_code="profile",
                route=AgentRoutingPolicy(
                    mode=AgentRouteMode.EXACT_READ_THEN_FINAL,
                    tool_name="get_my_employee_profile",
                    version="1.0.0",
                ),
            ),
            TrustedRouteEntry(
                intent_code="knowledge",
                route=AgentRoutingPolicy(
                    mode=AgentRouteMode.EXACT_READ_THEN_FINAL,
                    tool_name="search_hr_knowledge",
                    version="1.0.0",
                ),
            ),
        )
        runtime_catalog = {
            "transport_config": {"allowed_hosts": ["ai.internal"], "require_https": False},
            "audit_config": {
                "control": {
                    "expected_database_name": state["control"],
                    "expected_database_identity": "rehearsal-control-id",
                    "writer_role": state["control_writer"],
                },
                "customers": [
                    {
                        "customer_environment_id": CUSTOMER,
                        "expected_database_name": state["audit"],
                        "expected_database_identity": "rehearsal-audit-id",
                        "writer_role": state["audit_writer"],
                    }
                ],
                "minimum_pool_size": 0,
                "maximum_pool_size": 2,
            },
            "knowledge_config": {
                "routes": [
                    {
                        key: value
                        for key, value in knowledge_route.model_dump(mode="json").items()
                        if key != "runtime_dsn"
                    }
                ]
            },
            "openai_config": OpenAIProductionConfig(
                routes=(openai_route,), attestations=(attestation,)
            ).model_dump(mode="json"),
            "embedding_profiles": [profile.model_dump(mode="json", exclude_computed_fields=True)],
            "retrieval_policies": [
                SemanticRetrievalPolicy(
                    namespace="hr",
                    embedding_profile_sha256=profile.profile_sha256,
                    minimum_relevance_score=0.0,
                    policy_version="1.0.0",
                ).model_dump(mode="json", exclude_computed_fields=True)
            ],
            "trusted_routes": [item.model_dump(mode="json") for item in trusted_routes],
            "agent_limits": AgentLimits().model_dump(mode="json"),
            "maximum_intent_lifetime_seconds": 60,
        }
        (secrets / "config" / "catalog.json").write_text(
            json.dumps(runtime_catalog, separators=(",", ":")), encoding="utf-8"
        )
        trust = {
            "assertion_config": {
                "issuer": "synthetic-erp",
                "audience": "synthetic-ai",
                "keys": [
                    {
                        "kid": "rehearsal-key",
                        "public_key": _b64(public),
                        "activates_at": (now - timedelta(days=1)).isoformat(),
                        "retires_at": (now + timedelta(days=1)).isoformat(),
                    }
                ],
                "maximum_lifetime": 300,
                "maximum_clock_skew": 60,
            },
            "http_config": {
                "origin": "https://synthetic-services:8443",
                "connect_timeout_seconds": 2.0,
                "read_timeout_seconds": 5.0,
                "write_timeout_seconds": 2.0,
                "pool_timeout_seconds": 2.0,
                "maximum_connections": 4,
                "maximum_keepalive_connections": 1,
                "maximum_response_bytes": 65536,
            },
            "ca_reference": "tls/ca.pem",
            "certificate_reference": "tls/client.pem",
            "private_key_reference": "tls/client.key",
        }
        (secrets / "config" / "trust.json").write_text(
            json.dumps(trust, separators=(",", ":")), encoding="utf-8"
        )
        laravel = {
            "http_config": {
                "origin": "https://synthetic-services:8444",
                "connect_timeout_seconds": 2.0,
                "read_timeout_seconds": 5.0,
                "write_timeout_seconds": 2.0,
                "pool_timeout_seconds": 2.0,
                "maximum_connections": 4,
                "maximum_keepalive_connections": 1,
                "maximum_request_bytes": 65536,
                "maximum_response_bytes": 65536,
                "expected_service_identity": LARAVEL_ERP_READ_SERVICE_IDENTITY,
                "expected_contract_version": "1.0.0",
                "expected_contract_digest": LARAVEL_ERP_READ_CONTRACT_DIGEST,
            },
            "ca_reference": "tls/ca.pem",
            "certificate_reference": "tls/client.pem",
            "private_key_reference": "tls/client.key",
        }
        (secrets / "config" / "laravel.json").write_text(
            json.dumps(laravel, separators=(",", ":")), encoding="utf-8"
        )
        runtime = {
            "contract_version": "1.0.0",
            "deployment_version": "rehearsal-v1",
            "server": {
                "bind_address": "0.0.0.0",
                "port": 8080,
                "workers": 1,
                "concurrency_limit": 8,
                "backlog": 16,
                "keep_alive_seconds": 5,
                "startup_timeout_seconds": 60,
                "graceful_shutdown_seconds": 30,
            },
            "runtime_catalog_reference": "config/catalog.json",
            "erp_trust_config_reference": "config/trust.json",
            "laravel_config_reference": "config/laravel.json",
            "audit_control_dsn_reference": "postgres/control.dsn",
            "customer_routes": [
                {
                    "customer_environment_id": CUSTOMER,
                    "audit_runtime_dsn_reference": "postgres/audit.dsn",
                    "knowledge_runtime_dsn_reference": "postgres/knowledge.dsn",
                    "openai_credential_reference": "openai/key",
                    "openai_project_route_id": "synthetic-project",
                }
            ],
        }
        runtime_path = tmp_path / "runtime.json"
        runtime_path.write_text(json.dumps(runtime, separators=(",", ":")), encoding="utf-8")
        _run(
            "docker",
            "run",
            "-d",
            "--name",
            application,
            "--network",
            network,
            "--network-alias",
            "application",
            "--user",
            "10001:10001",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=16m",
            "-v",
            f"{runtime_path.resolve()}:/etc/erp-ai/runtime.json:ro",
            "-v",
            f"{secrets.resolve()}:/run/secrets/erp-ai:ro",
            "-v",
            f"{ca.resolve()}:/etc/ssl/certs/ca-certificates.crt:ro",
            IMAGE,
        )
        _wait(lambda: _application_ready(services, application), timeout=90)
        assert _internal_http(services, "GET", "/health/live")[0] == 204
        outcomes: dict[str, tuple[int, str | None]] = {}
        for route in ("general", "profile", "knowledge"):
            body = json.dumps(
                {"message": f"Synthetic {route} request", "stream": False}, separators=(",", ":")
            ).encode()
            status, response_body = _internal_http(
                services,
                "POST",
                "/v1/chat",
                body,
                {
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + _assertion(private, body, resolvers[route]),
                },
            )
            safe_code = None
            if status != 200:
                try:
                    safe_code = str(json.loads(response_body)["safe_error_code"])
                except (KeyError, TypeError, ValueError):
                    safe_code = "malformed_safe_failure"
            outcomes[route] = (status, safe_code)
        assert outcomes == {
            "general": (200, None),
            "profile": (200, None),
            "knowledge": (200, None),
        }
        application_rows = _database_rows(
            admin_dsn,
            state["control"],
            "SELECT stage,outcome,internal_reason FROM erp_ai_audit.application_events "
            "ORDER BY recorded_at",
        )
        agent_rows = _database_rows(
            admin_dsn,
            state["audit"],
            "SELECT action,outcome,internal_reason FROM erp_ai_audit.agent_events "
            "ORDER BY recorded_at",
        )
        tool_rows = _database_rows(
            admin_dsn,
            state["audit"],
            "SELECT tool_name,outcome,internal_reason FROM erp_ai_audit.tool_events "
            "ORDER BY recorded_at",
        )
        assert application_rows == [("orchestration", "success", "completed")] * 3
        assert agent_rows == [("agent.chat", "success", "completed")] * 3
        assert tool_rows == [
            ("get_my_employee_profile", "success", "execution_succeeded"),
            ("search_hr_knowledge", "success", "execution_succeeded"),
        ]
        events = [json.loads(line)["event"] for line in state_path.read_text().splitlines()]
        assert events.count("erp.snapshot") == 3
        assert events.count("openai.forced.get_my_employee_profile") == 1
        assert events.count("openai.forced.search_hr_knowledge") == 1
        assert events.count("laravel.profile") == 1
        assert events.count("openai.embedding") == 1
        assert events.count("openai.final.general") == 1
        assert events.count("openai.final.erp_data") == 1
        assert events.count("openai.final.knowledge") == 1
        inspection = json.loads(_run("docker", "inspect", application).stdout)[0]
        assert inspection["Config"]["User"] == "10001:10001"
        assert inspection["HostConfig"]["ReadonlyRootfs"] is True
        assert inspection["HostConfig"]["CapDrop"] == ["ALL"]
        assert "no-new-privileges" in inspection["HostConfig"]["SecurityOpt"]
        assert inspection["HostConfig"]["Tmpfs"] == {"/tmp": "rw,noexec,nosuid,size=16m"}
        mounts = {item["Destination"] for item in inspection["Mounts"]}
        assert mounts == {
            "/etc/erp-ai/runtime.json",
            "/run/secrets/erp-ai",
            "/etc/ssl/certs/ca-certificates.crt",
        }
        audit_text = json.dumps([application_rows, agent_rows, tool_rows], separators=(",", ":"))
        application_logs = (
            _run("docker", "logs", application, check=False).stdout
            + _run("docker", "logs", application, check=False).stderr
        )
        forbidden = (
            EMPLOYEE,
            LEGAL_ENTITY,
            citation,
            "synthetic-openai-key",
            "Synthetic Person",
            "synthetic@example.invalid",
            "synthetic handbook",
            "[1.0,0.0,0.0]",
        )
        assert not any(value in audit_text or value in application_logs for value in forbidden)
        _run("docker", "kill", "--signal", "TERM", application)
        _wait(lambda: _container_stopped(application), timeout=35)
        assert _internal_http(services, "GET", "/health/ready")[0] != 204
        assert (
            _run("docker", "inspect", application, "--format", "{{.State.ExitCode}}").stdout.strip()
            == "0"
        )
        active_roles = _database_rows(
            admin_dsn,
            "postgres",
            "SELECT usename FROM pg_stat_activity WHERE usename LIKE 'rehearsal_%_writer' "
            "OR usename='rehearsal_knowledge_reader'",
        )
        assert active_roles == []

        partial_catalog = json.loads(json.dumps(runtime_catalog))
        partial_catalog["knowledge_config"]["routes"][0]["expected_generation_digest"] = "f" * 64
        (secrets / "config" / "catalog.json").write_text(
            json.dumps(partial_catalog, separators=(",", ":")), encoding="utf-8"
        )
        _run(
            "docker",
            "run",
            "-d",
            "--name",
            partial_application,
            "--network",
            network,
            "--user",
            "10001:10001",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=16m",
            "-v",
            f"{runtime_path.resolve()}:/etc/erp-ai/runtime.json:ro",
            "-v",
            f"{secrets.resolve()}:/run/secrets/erp-ai:ro",
            "-v",
            f"{ca.resolve()}:/etc/ssl/certs/ca-certificates.crt:ro",
            IMAGE,
        )
        _wait(lambda: _container_stopped(partial_application), timeout=90)
        assert (
            _run(
                "docker",
                "inspect",
                partial_application,
                "--format",
                "{{.State.ExitCode}}",
            ).stdout.strip()
            == "1"
        )
        partial_logs = _run("docker", "logs", partial_application, check=False)
        combined_partial_logs = partial_logs.stdout + partial_logs.stderr
        assert not any(value in combined_partial_logs for value in forbidden)
        events_after_partial = [
            json.loads(line)["event"] for line in state_path.read_text().splitlines()
        ]
        assert events_after_partial.count("laravel.contract") == 2
        assert (
            _database_rows(
                admin_dsn,
                "postgres",
                "SELECT usename FROM pg_stat_activity WHERE usename LIKE 'rehearsal_%_writer' "
                "OR usename='rehearsal_knowledge_reader'",
            )
            == []
        )
    finally:
        for name in (partial_application, application, services, postgres):
            _run("docker", "rm", "-f", name, check=False)
        _run("docker", "network", "rm", network, check=False)
