import asyncio
import base64
import ctypes
import json
import ssl
from datetime import UTC
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
import uvicorn
from pydantic import ValidationError
from test_deployment_config_and_secrets import payload

from erp_ai.application import TrustedRouteEntry
from erp_ai.deployment import bootstrap
from erp_ai.deployment.admin import (
    load_administrative_config,
    migrate_control_audit,
    migrate_customer_audit,
    migrate_customer_knowledge,
    production_preflight,
)
from erp_ai.deployment.composition import compose_deployed_runtime
from erp_ai.deployment.config import ProductionDeploymentConfig
from erp_ai.deployment.factory import (
    AggregateProviderLifecycle,
    ConfiguredProductionDependencyFactory,
    CustomerKnowledgeProvider,
    ErpTrustDeploymentCatalog,
    FileOpenAICredentialProvider,
    LaravelDeploymentCatalog,
    ProductionRuntimeCatalog,
    SecureRequestIdFactory,
    SystemClock,
    _assertion_config,
    _RuntimeOpenAIProductionConfig,
    _strict_catalog,
    _strict_value,
    _validated_json,
)
from erp_ai.deployment.launcher import main, run_server
from erp_ai.deployment.logging import emit_lifecycle_event
from erp_ai.deployment.migrations import MigrationTarget, run_one_migration
from erp_ai.deployment.preflight import run_preflight
from erp_ai.deployment.secrets import FileSecretProvider
from erp_ai.deployment.ssl import create_verified_ssl_context, load_client_identity
from erp_ai.infrastructure.erp_trust import ErpTrustHttpConfig
from erp_ai.infrastructure.laravel_erp import LaravelErpReadConfig
from erp_ai.infrastructure.openai import OpenAIProductionConfig
from erp_ai.infrastructure.postgres import (
    ProductionKnowledgeRoute,
    SemanticRetrievalPolicy,
)
from erp_ai.knowledge import KnowledgeRetrievalRequest
from erp_ai.orchestration import AgentLimits, AgentRouteMode, AgentRoutingPolicy
from erp_ai.transport.http import InternalHttpTransportConfig
from tests.unit.test_embedding_models import profile
from tests.unit.test_erp_trust import key_config
from tests.unit.test_openai_production_provider import attestation
from tests.unit.test_openai_production_provider import route as openai_route
from tests.unit.test_production_rag import route as knowledge_route


class Check:
    def __init__(self, failure: BaseException | None = None) -> None:
        self.calls = 0
        self.failure = failure

    async def verify(self) -> None:
        self.calls += 1
        if self.failure:
            raise self.failure


class Migration:
    def __init__(self, failure: BaseException | None = None) -> None:
        self.calls: list[tuple[MigrationTarget, str]] = []
        self.failure = failure

    async def migrate_one(self, target: MigrationTarget, route_reference: str) -> None:
        self.calls.append((target, route_reference))
        if self.failure:
            raise self.failure


def config() -> ProductionDeploymentConfig:
    return ProductionDeploymentConfig.model_validate(payload(), strict=True)


def test_preflight_order_failure_and_cancellation() -> None:
    first, second = Check(), Check()
    asyncio.run(run_preflight((first, second)))
    assert first.calls == second.calls == 1
    with pytest.raises(RuntimeError, match="deployment preflight failed"):
        asyncio.run(run_preflight((Check(RuntimeError("private")),)))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_preflight((Check(asyncio.CancelledError()),)))


def test_one_target_migration_contract() -> None:
    migration = Migration()
    asyncio.run(run_one_migration(migration, MigrationTarget.CUSTOMER_AUDIT, "route-one"))
    assert migration.calls == [(MigrationTarget.CUSTOMER_AUDIT, "route-one")]
    for invalid in ("", "*"):
        with pytest.raises(ValueError):
            asyncio.run(run_one_migration(migration, MigrationTarget.CONTROL_AUDIT, invalid))
    with pytest.raises(RuntimeError, match="migration failed"):
        asyncio.run(
            run_one_migration(
                Migration(RuntimeError("private")), MigrationTarget.CUSTOMER_KNOWLEDGE, "one"
            )
        )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            run_one_migration(
                Migration(asyncio.CancelledError()), MigrationTarget.CUSTOMER_KNOWLEDGE, "one"
            )
        )


def test_lifecycle_logging_is_allowlisted(capsys: pytest.CaptureFixture[str]) -> None:
    emit_lifecycle_event("runtime.start", "erp_ai", "ready", "info", "synthetic-v1")
    value = json.loads(capsys.readouterr().err)
    assert set(value) == {"event", "component", "outcome", "severity", "deployment_version"}


def test_ssl_context_and_identity_fail_safely(tmp_path: Path) -> None:
    cafile = ssl.get_default_verify_paths().cafile
    if cafile is None:
        pytest.skip("system CA file is unavailable")
    context = create_verified_ssl_context(Path(cafile))
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2
    marker = tmp_path / "private-marker.pem"
    marker.write_text("private-marker", encoding="utf-8")
    with pytest.raises(ValueError, match="TLS identity is unavailable") as error:
        load_client_identity(context, marker, marker)
    assert "private-marker" not in str(error.value)
    with pytest.raises(TypeError):
        load_client_identity(object(), marker, marker)  # type: ignore[arg-type]


def test_composition_requires_concrete_factory(tmp_path: Path) -> None:
    root = tmp_path / "secrets"
    root.mkdir()
    with pytest.raises(TypeError, match="production dependency factory is required"):
        compose_deployed_runtime(config(), FileSecretProvider(root), object())  # type: ignore[arg-type]


def test_composition_delegates_validated_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "secrets"
    root.mkdir()
    sentinel = object()

    class Factory:
        def build(
            self, received: ProductionDeploymentConfig, secrets: FileSecretProvider
        ) -> object:
            assert received == config()
            assert isinstance(secrets, FileSecretProvider)
            return sentinel

    monkeypatch.setattr(
        "erp_ai.deployment.composition.compose_production_runtime",
        lambda bundle: ("composed", bundle),
    )
    assert compose_deployed_runtime(  # type: ignore[arg-type]
        config(), FileSecretProvider(root), Factory()
    ) == ("composed", sentinel)


def test_launcher_configuration_and_packaged_main_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class Server:
        started = True

        def __init__(self, configuration: object) -> None:
            observed["configuration"] = configuration

        async def serve(self) -> None:
            observed["served"] = True

    monkeypatch.setattr("erp_ai.deployment.launcher.uvicorn.Server", Server)
    run_server(config(), lambda: object())  # type: ignore[arg-type,return-value]
    configuration = observed["configuration"]
    assert isinstance(configuration, uvicorn.Config)
    assert configuration.workers == 1
    assert configuration.access_log is False
    assert configuration.proxy_headers is False
    assert observed["served"] is True
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1


def test_launcher_fails_when_lifespan_startup_never_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Server:
        started = False

        def __init__(self, configuration: object) -> None:
            del configuration

        async def serve(self) -> None:
            return None

    monkeypatch.setattr("erp_ai.deployment.launcher.uvicorn.Server", Server)
    with pytest.raises(SystemExit) as error:
        run_server(config(), lambda: object())  # type: ignore[arg-type,return-value]
    assert error.value.code == 1


def test_launcher_propagates_cancellation_and_contains_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Server:
        def __init__(self, configuration: object) -> None:
            del configuration

        async def serve(self) -> None:
            raise asyncio.CancelledError

    monkeypatch.setattr("erp_ai.deployment.launcher.uvicorn.Server", Server)
    with pytest.raises(asyncio.CancelledError):
        run_server(config(), lambda: object())  # type: ignore[arg-type,return-value]

    async def fail(self: object) -> None:
        del self
        raise RuntimeError("private")

    monkeypatch.setattr(Server, "serve", fail)
    with pytest.raises(SystemExit) as error:
        run_server(config(), lambda: object())  # type: ignore[arg-type,return-value]
    assert error.value.code == 1


def test_launcher_main_builds_and_runs_or_propagates_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deployment = config()
    application = object()
    runtime = type("Runtime", (), {"application": application})()
    observed: list[object] = []
    monkeypatch.setattr("erp_ai.deployment.launcher.load_production_config", lambda: deployment)
    monkeypatch.setattr(
        "erp_ai.deployment.launcher.compose_deployed_runtime", lambda *args: runtime
    )
    monkeypatch.setattr(
        "erp_ai.deployment.launcher.run_server",
        lambda supplied, factory: observed.extend((supplied, factory())),
    )
    main()
    assert observed == [deployment, application]
    monkeypatch.setattr(
        "erp_ai.deployment.launcher.load_production_config",
        lambda: (_ for _ in ()).throw(asyncio.CancelledError()),
    )
    with pytest.raises(asyncio.CancelledError):
        main()


def test_system_clock_uuid_and_strict_json() -> None:
    assert SystemClock().now().tzinfo is UTC
    assert UUID(SecureRequestIdFactory().create()).version == 4
    assert _strict_value(b'{"one":1}') == {"one": 1}
    for raw in (b'{"one":1,"one":2}', b'{"one":NaN}', b"\xff"):
        with pytest.raises((ValueError, UnicodeError)):
            _strict_value(raw)


def test_alpine_libpq_discovery_is_narrow_verified_and_restored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = ctypes.util.find_library
    observed: list[str] = []
    monkeypatch.setattr(bootstrap.sys, "platform", "linux")
    monkeypatch.setattr(bootstrap.ctypes.util, "find_library", lambda name: None)
    monkeypatch.setattr(bootstrap.ctypes, "CDLL", lambda name: observed.append(name))
    replaced = bootstrap.ctypes.util.find_library
    with bootstrap._system_libpq_discovery():
        assert bootstrap.ctypes.util.find_library("pq") == "libpq.so.5"
        assert bootstrap.ctypes.util.find_library("other") is None
    assert bootstrap.ctypes.util.find_library is replaced
    assert observed == ["libpq.so.5"]
    monkeypatch.setattr(bootstrap.ctypes.util, "find_library", original)


def test_libpq_bootstrap_fails_closed_and_invokes_all_operations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bootstrap.sys, "platform", "linux")
    monkeypatch.setattr(bootstrap.ctypes.util, "find_library", lambda name: None)
    monkeypatch.setattr(
        bootstrap.ctypes, "CDLL", lambda name: (_ for _ in ()).throw(OSError("private"))
    )
    with (
        pytest.raises(RuntimeError, match="runtime library is unavailable") as error,
        bootstrap._system_libpq_discovery(),
    ):
        pytest.fail("unreachable")
    assert "private" not in str(error.value)

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        bootstrap, "_invoke", lambda module, function: calls.append((module, function))
    )
    bootstrap.serve()
    bootstrap.migrate_control_audit()
    bootstrap.migrate_customer_audit()
    bootstrap.migrate_customer_knowledge()
    bootstrap.production_preflight()
    assert len(calls) == 5


def test_bootstrap_imports_then_invokes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    module = SimpleNamespace(operation=lambda: calls.append("invoked"))
    monkeypatch.setattr(bootstrap.importlib, "import_module", lambda name: module)
    monkeypatch.setattr(bootstrap.sys, "platform", "win32")
    bootstrap._invoke("synthetic.module", "operation")
    assert calls == ["invoked"]


class Lifecycle:
    def __init__(self, name: str, events: list[str], failure: str | None = None) -> None:
        self.name, self.events, self.failure = name, events, failure

    async def open(self) -> None:
        self.events.append(f"open:{self.name}")
        if self.failure == "open":
            raise RuntimeError("private")

    async def close(self) -> None:
        self.events.append(f"close:{self.name}")
        if self.failure == "close":
            raise RuntimeError("private")


def test_aggregate_provider_lifecycle_order_rollback_and_failure() -> None:
    events: list[str] = []
    aggregate = AggregateProviderLifecycle((Lifecycle("one", events), Lifecycle("two", events)))
    asyncio.run(aggregate.open())
    asyncio.run(aggregate.close())
    asyncio.run(aggregate.close())
    assert events == ["open:one", "open:two", "close:two", "close:one"]
    with pytest.raises(RuntimeError):
        asyncio.run(aggregate.open())

    events = []
    failed = AggregateProviderLifecycle(
        (Lifecycle("one", events), Lifecycle("two", events, "open"))
    )
    with pytest.raises(RuntimeError, match="private"):
        asyncio.run(failed.open())
    assert events == ["open:one", "open:two", "close:one"]
    with pytest.raises(TypeError):
        AggregateProviderLifecycle(())

    close_failed = AggregateProviderLifecycle((Lifecycle("one", [], "close"),))
    asyncio.run(close_failed.open())
    with pytest.raises(RuntimeError, match="provider shutdown failed"):
        asyncio.run(close_failed.close())

    cancellation_events: list[str] = []

    class CancelLifecycle(Lifecycle):
        async def close(self) -> None:
            self.events.append(f"close:{self.name}")
            raise asyncio.CancelledError

    cancelled = AggregateProviderLifecycle(
        (Lifecycle("one", cancellation_events), CancelLifecycle("two", cancellation_events))
    )
    asyncio.run(cancelled.open())
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(cancelled.close())
    assert cancellation_events[-2:] == ["close:two", "close:one"]


class Retrieval:
    async def retrieve(self, request: KnowledgeRetrievalRequest) -> tuple[object, ...]:
        return ()


def test_customer_knowledge_provider_routes_or_denies() -> None:
    request = KnowledgeRetrievalRequest(
        namespace="hr",
        query="synthetic",
        maximum_results=1,
        customer_environment_id="customer-a",
        enabled_modules=("hr_core",),
        permission_codes=("hr.knowledge.read",),
        roles=(),
        authorized_legal_entity_ids=(),
        purpose="employee_self_service",
        locale="en",
        effective_at=SystemClock().now(),
    )
    provider = CustomerKnowledgeProvider({"customer-a": Retrieval()})  # type: ignore[arg-type]
    assert asyncio.run(provider.retrieve(request)) == ()
    with pytest.raises(ValueError, match="knowledge route is unavailable"):
        asyncio.run(CustomerKnowledgeProvider({}).retrieve(request))


def test_file_openai_credential_provider_is_exactly_bound(tmp_path: Path) -> None:
    root = tmp_path / "secrets"
    (root / "openai").mkdir(parents=True)
    (root / "openai" / "key").write_text("synthetic-key", encoding="utf-8")
    route = type(
        "Route",
        (),
        {
            "customer_environment_id": "synthetic-customer",
            "credential_reference": "credential-ref",
            "organization_id": "organization",
            "project_id": "synthetic-project-route",
        },
    )()
    catalog = type("Catalog", (), {"routes": (route,)})()
    provider = FileOpenAICredentialProvider(  # type: ignore[arg-type]
        config(), catalog, FileSecretProvider(root)
    )
    value = asyncio.run(
        provider.resolve("credential-ref", "organization", "synthetic-project-route")
    )
    assert value.get_secret_value() == "synthetic-key"
    with pytest.raises(ValueError, match="credential is unavailable"):
        asyncio.run(provider.resolve("wrong", "organization", "synthetic-project-route"))


def test_administrative_config_and_entrypoint_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "admin.json"
    path.write_text(
        json.dumps(
            {
                "contract_version": "1.0.0",
                "target": "control_audit",
                "migration_dsn_reference": "postgres/admin.dsn",
                "expected_database_name": "audit",
                "expected_migration_owner": "owner",
                "database_identity": "identity",
                "writer_role": "writer",
            }
        ),
        encoding="utf-8",
    )
    assert load_administrative_config(path).target == "control_audit"
    path.write_text("not-json", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid administrative configuration"):
        load_administrative_config(path)
    path.write_text('{"contract_version":"1.0.0","contract_version":"1.0.0"}')
    with pytest.raises(ValueError, match="invalid administrative configuration"):
        load_administrative_config(path)
    for raw in (b"", (b'{"x":' * 13) + b"null" + (b"}" * 13)):
        path.write_bytes(raw)
        with pytest.raises(ValueError, match="invalid administrative configuration"):
            load_administrative_config(path)

    async def fail() -> None:
        raise RuntimeError("private")

    monkeypatch.setattr("erp_ai.deployment.admin._audit", lambda target: fail())
    with pytest.raises(SystemExit) as error:
        migrate_control_audit()
    assert error.value.code == 1
    monkeypatch.setattr("erp_ai.deployment.admin._preflight", fail)
    with pytest.raises(SystemExit):
        production_preflight()


def test_administrative_wrappers_and_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    from erp_ai.deployment import admin as admin_module

    original_run = admin_module._run
    operations: list[str] = []
    monkeypatch.setattr(
        "erp_ai.deployment.admin._run", lambda operation: operations.append(operation.__name__)
    )
    migrate_customer_audit()
    migrate_customer_knowledge()
    assert operations == ["<lambda>", "_knowledge"]

    async def cancelled() -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr("erp_ai.deployment.admin._run", original_run)
    monkeypatch.setattr("erp_ai.deployment.admin._audit", lambda target: cancelled())
    with pytest.raises(asyncio.CancelledError):
        migrate_control_audit()


def test_strict_catalog_and_unknown_openai_route_fail_closed() -> None:
    with pytest.raises(ValidationError):
        _strict_catalog(b"{}")
    with pytest.raises(ValueError, match="catalog is unavailable"):
        _strict_catalog((b'{"nested":' * 13) + b"null" + (b"}" * 13))
    project = openai_route(customer="another-customer", project_id="unknown-project")
    privacy = attestation(policy_id=project.privacy_attestation_id, project_id=project.project_id)
    with pytest.raises(ValueError, match="credential route is unavailable"):
        FileOpenAICredentialProvider(
            config(),
            OpenAIProductionConfig(routes=(project,), attestations=(privacy,)),
            FileSecretProvider(),
        )


def test_runtime_openai_catalog_preserves_strict_nested_json_semantics() -> None:
    project = openai_route(customer="synthetic-customer", project_id="synthetic-project")
    privacy = attestation(
        policy_id=project.privacy_attestation_id,
        project_id=project.project_id,
    )
    raw = OpenAIProductionConfig(routes=(project,), attestations=(privacy,)).model_dump(mode="json")

    parsed = _RuntimeOpenAIProductionConfig(routes=raw["routes"], attestations=raw["attestations"])
    reconstructed = _RuntimeOpenAIProductionConfig(
        routes=parsed.routes, attestations=parsed.attestations
    )

    assert reconstructed == parsed
    assert parsed.routes == (project,)
    assert parsed.attestations == (privacy,)


def test_concrete_factory_builds_complete_graph_without_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "secrets"
    for relative, value in (
        ("config/catalog.json", b"runtime"),
        ("config/trust.json", b"{}"),
        ("config/laravel.json", b"{}"),
        ("postgres/control.dsn", b"postgresql://writer:x@db.invalid/control"),
        ("postgres/audit.dsn", b"postgresql://writer:x@db.invalid/customer"),
        ("postgres/knowledge.dsn", b"postgresql://reader:x@db.invalid/knowledge"),
        ("openai/api-key", b"synthetic-key"),
        ("tls/ca.pem", b"ca"),
        ("tls/cert.pem", b"cert"),
        ("tls/key.pem", b"key"),
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)

    embedding = profile(
        provider_id="openai",
        model_id="text-embedding-3-large",
        model_revision="deployment-eval-revision-1",
    )
    knowledge = knowledge_route(customer="synthetic-customer", database="knowledge")
    knowledge = ProductionKnowledgeRoute.model_validate(
        {
            **knowledge.model_dump(),
            "embedding_model_id": embedding.model_id,
            "embedding_model_version": embedding.model_revision,
            "embedding_provider_id": embedding.provider_id,
            "embedding_profile_sha256": embedding.profile_sha256,
            "embedding_dimensions": embedding.dimensions,
        }
    )
    project = openai_route(customer="synthetic-customer", project_id="synthetic-project-route")
    privacy = attestation(
        policy_id=project.privacy_attestation_id,
        project_id=project.project_id,
    )
    openai = OpenAIProductionConfig(routes=(project,), attestations=(privacy,))
    catalog = ProductionRuntimeCatalog.model_construct(
        transport_config=InternalHttpTransportConfig(allowed_hosts=("ai.internal",)),
        audit_config={
            "control": {
                "expected_database_name": "control",
                "expected_database_identity": "control_identity",
                "writer_role": "writer",
            },
            "customers": (
                {
                    "customer_environment_id": "synthetic-customer",
                    "expected_database_name": "customer",
                    "expected_database_identity": "customer_identity",
                    "writer_role": "writer",
                },
            ),
        },
        knowledge_config={
            "routes": (
                {
                    key: value
                    for key, value in knowledge.model_dump(mode="json").items()
                    if key != "runtime_dsn"
                },
            )
        },
        openai_config=openai,
        embedding_profiles=(embedding,),
        retrieval_policies=(
            SemanticRetrievalPolicy(
                namespace="hr",
                embedding_profile_sha256=embedding.profile_sha256,
                minimum_relevance_score=0.8,
                policy_version="1.0.0",
            ),
        ),
        trusted_routes=(
            TrustedRouteEntry(
                intent_code="general",
                route=AgentRoutingPolicy(mode=AgentRouteMode.GENERAL_ONLY),
            ),
        ),
        agent_limits=AgentLimits(),
        maximum_intent_lifetime_seconds=60,
    )
    _, assertion = key_config()
    erp = ErpTrustDeploymentCatalog.model_construct(
        assertion_config=assertion,
        http_config=ErpTrustHttpConfig(
            origin="https://erp.invalid",
            connect_timeout_seconds=1.0,
            read_timeout_seconds=1.0,
            write_timeout_seconds=1.0,
            pool_timeout_seconds=1.0,
            maximum_connections=1,
            maximum_keepalive_connections=0,
            maximum_response_bytes=4096,
        ),
        ca_reference="tls/ca.pem",
        certificate_reference="tls/cert.pem",
        private_key_reference="tls/key.pem",
    )
    laravel = LaravelDeploymentCatalog.model_construct(
        http_config=LaravelErpReadConfig(
            origin="https://laravel.invalid",
            connect_timeout_seconds=1.0,
            read_timeout_seconds=1.0,
            write_timeout_seconds=1.0,
            pool_timeout_seconds=1.0,
            maximum_connections=1,
            maximum_keepalive_connections=0,
            maximum_request_bytes=4096,
            maximum_response_bytes=4096,
        ),
        ca_reference="tls/ca.pem",
        certificate_reference="tls/cert.pem",
        private_key_reference="tls/key.pem",
    )
    monkeypatch.setattr("erp_ai.deployment.factory._strict_catalog", lambda raw: catalog)
    monkeypatch.setattr(
        "erp_ai.deployment.factory._validated_json",
        lambda model, raw: erp if model is ErpTrustDeploymentCatalog else laravel,
    )
    context = ssl.create_default_context()
    monkeypatch.setattr(
        "erp_ai.deployment.factory.create_verified_ssl_context", lambda path: context
    )
    monkeypatch.setattr("erp_ai.deployment.factory.load_client_identity", lambda *args: None)
    deployment = config().model_copy(
        update={
            "customer_routes": (
                config()
                .customer_routes[0]
                .model_copy(update={"openai_project_route_id": "synthetic-project-route"}),
            )
        }
    )
    bundle = ConfiguredProductionDependencyFactory().build(deployment, FileSecretProvider(root))
    assert len(bundle.handlers) == 5
    assert len(bundle.registry.manifests) == 3

    extra_route = deployment.customer_routes[0].model_copy(
        update={
            "customer_environment_id": "synthetic-customer-two",
            "openai_project_route_id": "synthetic-project-route-two",
        }
    )
    incomplete = deployment.model_copy(
        update={"customer_routes": (*deployment.customer_routes, extra_route)}
    )
    with pytest.raises(ValueError, match="customer routes are incomplete"):
        ConfiguredProductionDependencyFactory().build(incomplete, FileSecretProvider(root))

    incomplete_catalog = catalog.model_copy(update={"retrieval_policies": ()})
    monkeypatch.setattr("erp_ai.deployment.factory._strict_catalog", lambda raw: incomplete_catalog)
    with pytest.raises(ValueError, match="embedding routes are incomplete"):
        ConfiguredProductionDependencyFactory().build(deployment, FileSecretProvider(root))


def test_strict_deployment_json_boundary_decodes_assertion_key() -> None:
    private, assertion = key_config()
    key = assertion.keys[0]
    encoded = base64.urlsafe_b64encode(key.public_key.get_secret_value()).rstrip(b"=").decode()
    parsed = _assertion_config(
        {
            "issuer": assertion.issuer.get_secret_value(),
            "audience": assertion.audience.get_secret_value(),
            "keys": [
                {
                    "kid": key.kid,
                    "public_key": encoded,
                    "activates_at": key.activates_at.isoformat(),
                    "retires_at": key.retires_at.isoformat(),
                }
            ],
            "maximum_lifetime": assertion.maximum_lifetime.total_seconds(),
            "maximum_clock_skew": assertion.maximum_clock_skew.total_seconds(),
            "maximum_token_bytes": assertion.maximum_token_bytes,
            "maximum_segment_bytes": assertion.maximum_segment_bytes,
        }
    )
    assert private is not None
    assert parsed.keys[0].public_key.get_secret_value() == key.public_key.get_secret_value()


@pytest.mark.parametrize(
    "value",
    (
        "invalid",
        {"keys": [{}]},
        {"keys": [{"public_key": "A" * 43, "activates_at": 1, "retires_at": "x"}]},
        {"keys": [], "maximum_lifetime": True, "maximum_clock_skew": 1},
    ),
)
def test_assertion_catalog_rejects_malformed_internal_values(value: object) -> None:
    with pytest.raises(ValueError, match="assertion configuration is unavailable"):
        _assertion_config(value)


def test_deployment_catalog_uses_strict_json_semantics() -> None:
    raw = json.dumps(
        {
            "assertion_config": {},
            "http_config": {
                "origin": "https://erp.invalid",
                "connect_timeout_seconds": 1.0,
                "read_timeout_seconds": 1.0,
                "write_timeout_seconds": 1.0,
                "pool_timeout_seconds": 1.0,
                "maximum_connections": 1,
                "maximum_keepalive_connections": 0,
                "maximum_response_bytes": 4096,
            },
            "ca_reference": "tls/ca.pem",
            "certificate_reference": "tls/cert.pem",
            "private_key_reference": "tls/key.pem",
        },
        separators=(",", ":"),
    ).encode()
    parsed = _validated_json(ErpTrustDeploymentCatalog, raw)
    assert isinstance(parsed, ErpTrustDeploymentCatalog)
