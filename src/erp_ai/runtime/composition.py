"""The single deterministic production composition root."""

from contextlib import suppress

from erp_ai.application import compose_application
from erp_ai.infrastructure.erp_trust import (
    ErpAuthorizationSnapshotVerifier,
    ErpSignedAssertionAuthenticator,
    ErpTrustedRequestResolver,
    ErpTrustHttpClient,
)
from erp_ai.infrastructure.postgres_audit import (
    PostgresAgentAuditSink,
    PostgresApplicationAuditSink,
    PostgresToolAuditSink,
    StaticAuditDatabaseRouter,
)
from erp_ai.orchestration import AgentOrchestrator
from erp_ai.tools import ReadToolGateway
from erp_ai.transport.http import create_internal_http_app

from .bundle import ExternalRuntimeBundle
from .errors import RuntimeCompositionError
from .lifecycle import ProductionRuntimeLifecycle, ProviderLifecycleLease
from .models import ComposedRuntime


def compose_production_runtime(bundle: ExternalRuntimeBundle) -> ComposedRuntime:
    """Construct a closed runtime without environment, file, database, or network I/O."""

    ownership_token: object | None = None
    lease: ProviderLifecycleLease | None = None
    try:
        bundle = ExternalRuntimeBundle(
            **{name: getattr(bundle, name) for name in ExternalRuntimeBundle.__slots__}
        )
        registry = bundle.registry
        expected = {
            tool.tool_name: tool.version
            for manifest in registry.manifests
            for tool in manifest.tools
        }
        installed = {handler.tool_name: handler.version for handler in bundle.handlers}
        if expected != installed:
            raise ValueError("installed registry and handlers must match exactly")
        if any(
            tool.operation != "read" for manifest in registry.manifests for tool in manifest.tools
        ):
            raise ValueError("command tools are forbidden")

        audit_router = StaticAuditDatabaseRouter(bundle.audit_config)
        application_sink = PostgresApplicationAuditSink(audit_router, bundle.audit_config)
        agent_sink = PostgresAgentAuditSink(audit_router, bundle.audit_config)
        tool_sink = PostgresToolAuditSink(audit_router, bundle.audit_config)
        authenticator = ErpSignedAssertionAuthenticator(bundle.assertion_config, bundle.clock)
        erp_client = ErpTrustHttpClient(bundle.erp_trust_config, bundle.erp_ssl_context)
        resolver = ErpTrustedRequestResolver(erp_client)
        snapshot = ErpAuthorizationSnapshotVerifier(erp_client)
        gateway = ReadToolGateway(registry, bundle.handlers, tool_sink)
        bundle.route_catalog.validate_startup(registry, gateway)
        lease = bundle.provider_lifecycle_lease
        ownership_token = lease.claim()
        orchestrator = AgentOrchestrator(
            registry, gateway, bundle.model_provider, agent_sink, bundle.agent_limits
        )
        application = compose_application(
            registry=registry,
            orchestrator=orchestrator,
            resolver=resolver,
            snapshot_verifier=snapshot,
            route_catalog=bundle.route_catalog,
            audit_sink=application_sink,
            clock=bundle.clock,
            maximum_intent_lifetime=bundle.maximum_intent_lifetime,
        ).application
        lifecycle = ProductionRuntimeLifecycle(audit_router, erp_client, lease.lifecycle)
        app = create_internal_http_app(
            config=bundle.transport_config,
            authenticator=authenticator,
            request_id_factory=bundle.request_id_factory,
            application=application,
            application_audit_sink=application_sink,
            lifecycle=lifecycle,
        )
        runtime = ComposedRuntime(app, lifecycle)
        lease.commit(ownership_token)
        return runtime
    except Exception:
        if lease is not None and ownership_token is not None:
            with suppress(Exception):
                lease.release(ownership_token)
        raise RuntimeCompositionError("production runtime composition failed") from None
