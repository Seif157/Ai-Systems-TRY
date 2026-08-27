import asyncio
import ssl
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import pytest
from pydantic import SecretBytes, SecretStr, ValidationError

from erp_ai.application import TrustedRouteCatalog, TrustedRouteEntry
from erp_ai.capabilities import CapabilityManifest, CapabilityRegistry, ToolDescriptor
from erp_ai.infrastructure.erp_trust import (
    ErpAssertionVerificationKey,
    ErpAssertionVerifierConfig,
    ErpTrustHttpConfig,
    ErpTrustUnavailable,
)
from erp_ai.infrastructure.postgres_audit import (
    ControlAuditDatabaseConfig,
    CustomerAuditDatabaseRoute,
    RuntimeAuditDatabaseConfig,
    StaticAuditDatabaseConfig,
)
from erp_ai.orchestration import (
    AgentLimits,
    AgentRouteMode,
    AgentRoutingPolicy,
    ModelFinalAnswer,
    ModelTurnRequest,
)
from erp_ai.runtime import (
    ExternalRuntimeBundle,
    ProductionRuntimeLifecycle,
    ProviderLifecycleLease,
    RuntimeCompositionError,
    RuntimeLifecycleError,
    RuntimeState,
    compose_production_runtime,
)
from erp_ai.transport.http import InternalHttpTransportConfig


class Clock:
    def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=UTC)


class Ids:
    def create(self) -> str:
        return str(uuid4())


class Model:
    async def complete_turn(self, request: ModelTurnRequest) -> ModelFinalAnswer:
        return ModelFinalAnswer(answer="synthetic", answer_basis="general")


class Resource:
    def __init__(
        self, name: str, events: list[str], fail_open: bool = False, fail_close: bool = False
    ) -> None:
        self.name, self.events = name, events
        self.fail_open, self.fail_close = fail_open, fail_close

    async def open(self) -> None:
        self.events.append(f"open:{self.name}")
        if self.fail_open:
            raise RuntimeError("SENSITIVE_OPEN_MARKER")

    async def close(self) -> None:
        self.events.append(f"close:{self.name}")
        if self.fail_close:
            raise RuntimeError("SENSITIVE_CLOSE_MARKER")


def static_audit_config() -> StaticAuditDatabaseConfig:
    return StaticAuditDatabaseConfig(
        control=ControlAuditDatabaseConfig(
            writer_dsn=SecretStr("postgresql://writer:CONTROL_MARKER@db.invalid/control_audit"),
            migration_dsn=SecretStr("postgresql://owner:MIGRATION_MARKER@db.invalid/control_audit"),
            expected_database_name="control_audit",
            expected_database_identity="control_identity",
            writer_role="audit_writer",
        ),
        customers=(
            CustomerAuditDatabaseRoute(
                customer_environment_id="customer_a",
                writer_dsn=SecretStr("postgresql://writer:CUSTOMER_MARKER@db.invalid/customer_a"),
                migration_dsn=SecretStr(
                    "postgresql://owner:MIGRATION_MARKER@db.invalid/customer_a"
                ),
                expected_database_name="customer_a",
                expected_database_identity="customer_a_identity",
                writer_role="audit_writer",
            ),
        ),
    )


def bundle() -> ExternalRuntimeBundle:
    now = datetime(2025, 1, 1, tzinfo=UTC)
    audit = RuntimeAuditDatabaseConfig.from_static(static_audit_config())
    return ExternalRuntimeBundle(
        transport_config=InternalHttpTransportConfig(allowed_hosts=("ai.internal",)),
        assertion_config=ErpAssertionVerifierConfig(
            issuer=SecretStr("erp-issuer"),
            audience=SecretStr("erp-ai"),
            keys=(
                ErpAssertionVerificationKey(
                    kid="key_1",
                    public_key=SecretBytes(bytes(range(32))),
                    activates_at=now,
                    retires_at=now + timedelta(days=3650),
                ),
            ),
            maximum_lifetime=timedelta(minutes=1),
            maximum_clock_skew=timedelta(seconds=10),
        ),
        erp_trust_config=ErpTrustHttpConfig(
            origin=SecretStr("https://erp-trust.invalid"),
            connect_timeout_seconds=1.0,
            read_timeout_seconds=1.0,
            write_timeout_seconds=1.0,
            pool_timeout_seconds=1.0,
            maximum_connections=1,
            maximum_keepalive_connections=0,
            maximum_response_bytes=4096,
        ),
        erp_ssl_context=ssl.create_default_context(),
        audit_config=audit,
        route_catalog=TrustedRouteCatalog(
            (
                TrustedRouteEntry(
                    intent_code="general",
                    route=AgentRoutingPolicy(mode=AgentRouteMode.GENERAL_ONLY),
                ),
            )
        ),
        registry=CapabilityRegistry(()),
        handlers=(),
        model_provider=Model(),
        provider_lifecycle_lease=ProviderLifecycleLease(Resource("providers", [])),
        agent_limits=AgentLimits(),
        maximum_intent_lifetime=timedelta(minutes=1),
        request_id_factory=Ids(),
        clock=Clock(),
    )


def test_runtime_audit_projection_discards_migration_authority() -> None:
    projected = RuntimeAuditDatabaseConfig.from_static(static_audit_config())
    dumped = repr(projected) + str(projected.model_dump())
    assert "migration" not in dumped.lower()
    assert "MIGRATION_MARKER" not in dumped
    with pytest.raises(ValidationError):
        RuntimeAuditDatabaseConfig.model_validate({**projected.model_dump(), "migration_dsn": "x"})
    raw = projected.model_dump(mode="python")
    customer = raw["customers"][0]
    for mutation in (
        {**raw, "customers": (customer, customer)},
        {**raw, "customers": ({**customer, "expected_database_name": "control_audit"},)},
        {**raw, "minimum_pool_size": 6, "maximum_pool_size": 5},
    ):
        with pytest.raises(ValidationError):
            RuntimeAuditDatabaseConfig.model_validate(mutation, strict=True)


def test_bundle_and_composition_are_repr_safe_and_immutable() -> None:
    supplied = bundle()
    runtime = compose_production_runtime(supplied)
    assert runtime.state is RuntimeState.CREATED
    assert repr(runtime) == "ComposedRuntime(state='created')"
    assert "MARKER" not in repr(supplied) + repr(runtime)
    with pytest.raises((AttributeError, TypeError)):
        runtime.application = None  # type: ignore[misc,assignment]


def test_ssl_context_is_revalidated_immediately_before_open() -> None:
    supplied = bundle()
    runtime = compose_production_runtime(supplied)
    supplied.erp_ssl_context.check_hostname = False
    supplied.erp_ssl_context.verify_mode = ssl.CERT_NONE
    with pytest.raises(ErpTrustUnavailable):
        asyncio.run(runtime._lifecycle._erp.open())
    assert runtime.state is RuntimeState.CREATED
    second = compose_production_runtime(bundle())
    object.__setattr__(second._lifecycle._erp, "_ssl_context", None)
    with pytest.raises(ErpTrustUnavailable):
        asyncio.run(second._lifecycle._erp.open())


def test_bundle_copies_caller_collections_and_runtimes_are_isolated() -> None:
    supplied = bundle()
    mutable_handlers: list[Any] = []
    values = {name: getattr(supplied, name) for name in ExternalRuntimeBundle.__slots__}
    copied = ExternalRuntimeBundle(**{**values, "handlers": mutable_handlers})  # type: ignore[arg-type]
    mutable_handlers.append(object())
    assert copied.handlers == ()
    first = compose_production_runtime(copied)
    second = compose_production_runtime(bundle())
    assert first.application is not second.application
    assert first._lifecycle is not second._lifecycle


def test_composition_rejects_constructed_invalid_bundle() -> None:
    forged = object.__new__(ExternalRuntimeBundle)
    with pytest.raises(RuntimeCompositionError, match="composition failed"):
        compose_production_runtime(forged)


def test_provider_lease_is_local_concurrent_and_single_use() -> None:
    lease = ProviderLifecycleLease(Resource("provider", []))

    def claim() -> object:
        return lease.claim()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future for future in (pool.submit(claim), pool.submit(claim))]
        outcomes: list[object] = []
        failures = 0
        for future in results:
            try:
                outcomes.append(future.result())
            except RuntimeLifecycleError:
                failures += 1
    assert len(outcomes) == 1 and failures == 1
    lease.release(outcomes[0])
    token = lease.claim()
    lease.commit(token)
    with pytest.raises(RuntimeLifecycleError):
        lease.claim()
    with pytest.raises(RuntimeLifecycleError):
        lease.release(token)
    with pytest.raises(RuntimeLifecycleError):
        ProviderLifecycleLease(Resource("other", [])).commit(object())
    with pytest.raises(TypeError):
        ProviderLifecycleLease(object())  # type: ignore[arg-type]


def test_composition_failure_after_claim_releases_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    supplied = bundle()
    lease = supplied.provider_lifecycle_lease

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("SENSITIVE_CONSTRUCTION_MARKER")

    monkeypatch.setattr("erp_ai.runtime.composition.AgentOrchestrator", fail)
    with pytest.raises(RuntimeCompositionError) as caught:
        compose_production_runtime(supplied)
    assert "SENSITIVE" not in str(caught.value)
    token = lease.claim()
    lease.release(token)


def test_bundle_rejects_missing_security_dependencies() -> None:
    valid = bundle()
    values = {name: getattr(valid, name) for name in ExternalRuntimeBundle.__slots__}
    with pytest.raises(TypeError, match="SSL context"):
        ExternalRuntimeBundle(**{**values, "erp_ssl_context": object()})  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="model provider"):
        ExternalRuntimeBundle(**{**values, "model_provider": object()})  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="provider lifecycle lease"):
        ExternalRuntimeBundle(**{**values, "provider_lifecycle_lease": object()})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="intent lifetime"):
        ExternalRuntimeBundle(**{**values, "maximum_intent_lifetime": timedelta(0)})


def test_composition_rejects_handler_mismatch_and_commands() -> None:
    class ExtraHandler:
        tool_name = "extra"
        version = "1.0.0"

    valid = bundle()
    object.__setattr__(valid, "handlers", (ExtraHandler(),))
    with pytest.raises(RuntimeCompositionError):
        compose_production_runtime(valid)

    command = ToolDescriptor(
        tool_name="danger",
        version="1.0.0",
        operation="command",
        required_permissions_all=(),
        required_roles_any=(),
        allowed_purposes=("test",),
        data_classification="internal",
        audit_action="danger.command",
    )
    registry = CapabilityRegistry(
        (
            CapabilityManifest(
                capability_code="danger",
                version="1.0.0",
                required_modules=("danger",),
                tools=(command,),
            ),
        )
    )

    class Handler:
        tool_name = "danger"
        version = "1.0.0"

    commanded = bundle()
    object.__setattr__(commanded, "registry", registry)
    object.__setattr__(commanded, "handlers", (Handler(),))
    with pytest.raises(RuntimeCompositionError):
        compose_production_runtime(commanded)


def test_lifecycle_order_and_shutdown_before_startup() -> None:
    asyncio.run(_lifecycle_order_and_shutdown_before_startup())


async def _lifecycle_order_and_shutdown_before_startup() -> None:
    events: list[str] = []
    lifecycle = ProductionRuntimeLifecycle(
        cast(Any, Resource("audit", events)),
        cast(Any, Resource("erp", events)),
        Resource("providers", events),
    )
    await lifecycle.startup()
    assert lifecycle.state is RuntimeState.READY
    await lifecycle.shutdown()
    assert events == [
        "open:audit",
        "open:erp",
        "open:providers",
        "close:providers",
        "close:erp",
        "close:audit",
    ]
    assert lifecycle.state is RuntimeState.CLOSED
    with pytest.raises(RuntimeLifecycleError):
        await lifecycle.startup()
    with pytest.raises(RuntimeLifecycleError):
        await lifecycle.shutdown()

    unused = ProductionRuntimeLifecycle(
        cast(Any, Resource("a", [])), cast(Any, Resource("e", [])), Resource("p", [])
    )
    await unused.shutdown()
    assert unused.state is RuntimeState.CLOSED


def test_lifecycle_rolls_back_and_redacts_failures() -> None:
    asyncio.run(_lifecycle_rolls_back_and_redacts_failures())


async def _lifecycle_rolls_back_and_redacts_failures() -> None:
    events: list[str] = []
    lifecycle = ProductionRuntimeLifecycle(
        cast(Any, Resource("audit", events)),
        cast(Any, Resource("erp", events)),
        Resource("providers", events, fail_open=True),
    )
    with pytest.raises(RuntimeLifecycleError) as caught:
        await lifecycle.startup()
    assert "SENSITIVE" not in str(caught.value)
    assert events[-3:] == ["close:providers", "close:erp", "close:audit"]
    assert lifecycle.state is RuntimeState.FAILED
    await lifecycle.shutdown()
    assert lifecycle.state is RuntimeState.CLOSED
    assert events.count("close:audit") == 1

    errors: list[str] = []
    closing = ProductionRuntimeLifecycle(
        cast(Any, Resource("audit", errors, fail_close=True)),
        cast(Any, Resource("erp", errors, fail_close=True)),
        Resource("providers", errors, fail_close=True),
    )
    await closing.startup()
    with pytest.raises(RuntimeLifecycleError) as closed:
        await closing.shutdown()
    assert "SENSITIVE" not in str(closed.value)
    assert errors[-3:] == ["close:providers", "close:erp", "close:audit"]


def test_lifecycle_startup_cancellation_cleans_up() -> None:
    asyncio.run(_lifecycle_startup_cancellation_cleans_up())


async def _lifecycle_startup_cancellation_cleans_up() -> None:
    class Cancels(Resource):
        async def open(self) -> None:
            self.events.append(f"open:{self.name}")
            raise asyncio.CancelledError

    events: list[str] = []
    lifecycle = ProductionRuntimeLifecycle(
        cast(Any, Resource("audit", events)),
        cast(Any, Cancels("erp", events)),
        Resource("providers", events),
    )
    with pytest.raises(asyncio.CancelledError):
        await lifecycle.startup()
    assert events == ["open:audit", "open:erp", "close:erp", "close:audit"]
    assert lifecycle.state is RuntimeState.FAILED


def test_lifecycle_rejects_missing_provider_owner() -> None:
    with pytest.raises(TypeError, match="provider runtime lifecycle"):
        ProductionRuntimeLifecycle(cast(Any, object()), cast(Any, object()), object())  # type: ignore[arg-type]


def test_lifecycle_shutdown_cancellation_attempts_every_resource() -> None:
    class CancelClose(Resource):
        async def close(self) -> None:
            self.events.append(f"close:{self.name}")
            raise asyncio.CancelledError

    async def exercise() -> None:
        events: list[str] = []
        lifecycle = ProductionRuntimeLifecycle(
            cast(Any, Resource("audit", events)),
            cast(Any, Resource("erp", events)),
            CancelClose("providers", events),
        )
        await lifecycle.startup()
        with pytest.raises(asyncio.CancelledError):
            await lifecycle.shutdown()
        assert events[-3:] == ["close:providers", "close:erp", "close:audit"]
        assert lifecycle.state is RuntimeState.FAILED

    asyncio.run(exercise())


def test_lifecycle_serializes_concurrent_transitions() -> None:
    async def exercise() -> None:
        events: list[str] = []
        lifecycle = ProductionRuntimeLifecycle(
            cast(Any, Resource("audit", events)),
            cast(Any, Resource("erp", events)),
            Resource("providers", events),
        )
        starts = await asyncio.gather(
            lifecycle.startup(), lifecycle.startup(), return_exceptions=True
        )
        assert sum(isinstance(item, RuntimeLifecycleError) for item in starts) == 1
        stops = await asyncio.gather(
            lifecycle.shutdown(), lifecycle.shutdown(), return_exceptions=True
        )
        assert sum(isinstance(item, RuntimeLifecycleError) for item in stops) == 1
        assert events.count("open:audit") == 1
        assert events.count("close:audit") == 1

    asyncio.run(exercise())


def test_close_racing_with_start_waits_and_then_closes() -> None:
    class BlockingResource(Resource):
        def __init__(self, name: str, events: list[str]) -> None:
            super().__init__(name, events)
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def open(self) -> None:
            self.events.append(f"open:{self.name}")
            self.entered.set()
            await self.release.wait()

    async def exercise() -> None:
        events: list[str] = []
        audit = BlockingResource("audit", events)
        lifecycle = ProductionRuntimeLifecycle(
            cast(Any, audit), cast(Any, Resource("erp", events)), Resource("providers", events)
        )
        starting = asyncio.create_task(lifecycle.startup())
        await audit.entered.wait()
        assert lifecycle.state is RuntimeState.STARTING
        stopping = asyncio.create_task(lifecycle.shutdown())
        await asyncio.sleep(0)
        assert not stopping.done()
        audit.release.set()
        await starting
        await stopping
        assert lifecycle.state is RuntimeState.CLOSED
        assert events == [
            "open:audit",
            "open:erp",
            "open:providers",
            "close:providers",
            "close:erp",
            "close:audit",
        ]

    asyncio.run(exercise())
