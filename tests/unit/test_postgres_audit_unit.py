import asyncio
from copy import deepcopy
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from psycopg import Error
from pydantic import ValidationError

from erp_ai.application.audit import ApplicationAuditEvent
from erp_ai.capabilities import DataClassification
from erp_ai.infrastructure.postgres_audit.config import (
    ControlAuditDatabaseConfig,
    CustomerAuditDatabaseRoute,
    StaticAuditDatabaseConfig,
)
from erp_ai.infrastructure.postgres_audit.contracts import (
    CONTRACT_VERSION,
    CONTROL_DESCRIPTOR,
    CUSTOMER_DESCRIPTOR,
    AuditDatabaseKind,
    canonical_contract_bytes,
    contract_digest,
    event_digest,
    validate_contract_snapshot,
    validated_event_values,
)
from erp_ai.infrastructure.postgres_audit.errors import (
    AuditMigrationError,
    AuditStorageConflict,
    AuditStorageUnavailable,
)
from erp_ai.infrastructure.postgres_audit.migrations import migration_bytes, migration_checksums
from erp_ai.infrastructure.postgres_audit.routing import StaticAuditDatabaseRouter
from erp_ai.infrastructure.postgres_audit.sinks import (
    PostgresAgentAuditSink,
    PostgresApplicationAuditSink,
    PostgresToolAuditSink,
    _translate_driver_error,
    _verify_write_binding,
)
from erp_ai.orchestration.audit import AgentAuditEvent
from erp_ai.tools.audit import ToolAuditEvent

CONTROL_DIGEST = "3db29998e402f7362d8f166302af100fe3d71251d98cd2ab3beecf5639707ac3"
CUSTOMER_DIGEST = "5a2fd57e2d64e139115b74a5d7b800ec4c05f881a0fa8d98e69f96b973094c95"


def config() -> StaticAuditDatabaseConfig:
    return StaticAuditDatabaseConfig(
        control=ControlAuditDatabaseConfig(
            writer_dsn="postgresql://writer:secret@localhost/control",
            migration_dsn="postgresql://owner:secret@localhost/control",
            expected_database_name="audit_control",
            expected_database_identity="control_identity",
            writer_role="audit_control_writer",
        ),
        customers=(
            CustomerAuditDatabaseRoute(
                customer_environment_id="customer_a",
                writer_dsn="postgresql://writer:secret@localhost/customer_a",
                migration_dsn="postgresql://owner:secret@localhost/customer_a",
                expected_database_name="audit_customer_a",
                expected_database_identity="customer_a_identity",
                writer_role="audit_customer_writer",
            ),
        ),
    )


def application_event() -> ApplicationAuditEvent:
    return ApplicationAuditEvent(
        request_id="request_1",
        stage="orchestration",
        outcome="success",
        internal_reason="completed",
    )


def agent_event() -> AgentAuditEvent:
    return AgentAuditEvent(
        request_id="request_1",
        customer_environment_id="customer_a",
        user_id="user_1",
        purpose="employee_self_service",
        outcome="success",
        internal_reason="completed",
    )


def tool_event() -> ToolAuditEvent:
    return ToolAuditEvent(
        request_id="request_1",
        customer_environment_id="customer_a",
        user_id="user_1",
        tool_name="get_my_employee_profile",
        tool_version="1.0.0",
        audit_action="hr.profile.read_self",
        data_classification=DataClassification.RESTRICTED,
        outcome="success",
        internal_reason="completed",
        purpose="employee_self_service",
    )


def test_configuration_is_strict_frozen_redacted_and_unique() -> None:
    value = config()
    assert "secret" not in repr(value)
    assert isinstance(value.customers, tuple)
    with pytest.raises(ValidationError):
        StaticAuditDatabaseConfig.model_validate({**value.model_dump(), "unknown": True})
    with pytest.raises(ValidationError):
        value.maximum_pool_size = 9  # type: ignore[misc]
    customer = value.customers[0]
    other = customer.model_copy(update={"customer_environment_id": "customer_b"})
    for replacement in (
        customer.model_copy(update={"customer_environment_id": "customer_a"}),
        other.model_copy(update={"expected_database_name": value.control.expected_database_name}),
        other.model_copy(
            update={"expected_database_identity": value.control.expected_database_identity}
        ),
    ):
        with pytest.raises(ValidationError):
            StaticAuditDatabaseConfig(control=value.control, customers=(customer, replacement))
    with pytest.raises(ValidationError):
        StaticAuditDatabaseConfig(
            control=value.control, customers=(customer,), minimum_pool_size=6, maximum_pool_size=5
        )
    for invalid_dsn in ("postgresql://[", "dbname=audit_without_user"):
        with pytest.raises(ValidationError) as caught:
            ControlAuditDatabaseConfig(
                writer_dsn=invalid_dsn,
                migration_dsn=value.control.migration_dsn,
                expected_database_name="audit_control",
                expected_database_identity="control_identity",
                writer_role="audit_writer",
            )
        assert invalid_dsn not in str(caught.value)


def test_contract_and_event_digest_golden_values_and_drift() -> None:
    assert CONTRACT_VERSION == "1.0.0"
    assert contract_digest(CONTROL_DESCRIPTOR) == CONTROL_DIGEST
    assert contract_digest(CUSTOMER_DESCRIPTOR) == CUSTOMER_DIGEST
    assert canonical_contract_bytes(CONTROL_DESCRIPTOR) == (
        b'{"contract_version":"1.0.0","tables":[["erp_ai_audit.database_identity",'
        b'[["singleton","boolean"],["database_kind","character varying(16)"],'
        b'["database_identity","character varying(100)"],["customer_environment_id",'
        b'"character varying(100)"]]],'
        b'["erp_ai_audit.contract_metadata",[["singleton","boolean"],'
        b'["contract_version","character varying(20)"],["contract_sha256","character(64)"]]],'
        b'["erp_ai_audit.application_events",[["request_id","character varying(100)"],'
        b'["stage","character varying(32)"],["outcome","character varying(16)"],'
        b'["internal_reason","character varying(200)"],["event_digest","character(64)"],'
        b'["recorded_at","timestamp with time zone"]]]]}'
    )
    assert not canonical_contract_bytes(CONTROL_DESCRIPTOR).endswith(b"\n")
    changed = deepcopy(CONTROL_DESCRIPTOR)
    assert contract_digest(("1.0.1", changed[1])) != CONTROL_DIGEST
    assert (
        event_digest(application_event())
        != event_digest(agent_event())
        != event_digest(tool_event())
    )
    assert event_digest(application_event()) == event_digest(application_event())
    with pytest.raises(TypeError):
        event_digest(SimpleNamespace())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        validated_event_values(SimpleNamespace())  # type: ignore[arg-type]


def test_write_binding_requires_one_exact_identity_row() -> None:
    expected = (
        "audit_control",
        "audit_writer",
        "control",
        "control_identity",
        None,
    )

    class BindingCursor:
        def __init__(self, rows: list[tuple[object, ...]]) -> None:
            self.rows = rows

        async def fetchall(self) -> list[tuple[object, ...]]:
            return self.rows

    class BindingConnection:
        def __init__(self, rows: list[tuple[object, ...]]) -> None:
            self.rows = rows

        async def execute(self, _: str) -> BindingCursor:
            return BindingCursor(self.rows)

    values = dict(
        expected_database="audit_control",
        expected_role="audit_writer",
        expected_identity="control_identity",
        expected_kind="control",
        expected_customer=None,
    )
    asyncio.run(_verify_write_binding(BindingConnection([expected]), **values))  # type: ignore[arg-type]
    for rows in ([], [expected, expected], [(*expected[:-1], "wrong_customer")]):
        with pytest.raises(AuditStorageUnavailable):
            asyncio.run(_verify_write_binding(BindingConnection(rows), **values))  # type: ignore[arg-type]


def test_contract_digest_and_snapshot_fail_for_every_structural_drift() -> None:
    version, tables = CONTROL_DESCRIPTOR
    first_name, first_columns = tables[0]
    metadata_name, metadata_columns = tables[1]
    drifts = (
        ("1.0.1", tables),
        (version, (("erp_ai_audit.renamed_identity", first_columns), *tables[1:])),
        (version, (tables[1], tables[0], *tables[2:])),
        (
            version,
            ((first_name, (("renamed", first_columns[0][1]), *first_columns[1:])), *tables[1:]),
        ),
        (version, ((first_name, tuple(reversed(first_columns))), *tables[1:])),
        (version, ((first_name, ((first_columns[0][0], "text"), *first_columns[1:])), *tables[1:])),
        (version, (tables[0], ("erp_ai_audit.renamed_metadata", metadata_columns), *tables[2:])),
        (version, (tables[0], (metadata_name, tuple(reversed(metadata_columns))), *tables[2:])),
    )
    for drift in drifts:
        assert contract_digest(drift) != CONTROL_DIGEST
        with pytest.raises(AuditStorageUnavailable):
            validate_contract_snapshot(
                descriptor=drift,
                reported_version=CONTRACT_VERSION,
                reported_digest=CONTROL_DIGEST,
                actual_tables=drift[1],
            )
    with pytest.raises(AuditStorageUnavailable):
        validate_contract_snapshot(
            descriptor=CONTROL_DESCRIPTOR,
            reported_version="1.0.1",
            reported_digest=CONTROL_DIGEST,
            actual_tables=tables,
        )
    with pytest.raises(AuditStorageUnavailable):
        validate_contract_snapshot(
            descriptor=CONTROL_DESCRIPTOR,
            reported_version=CONTRACT_VERSION,
            reported_digest=CONTROL_DIGEST,
            actual_tables=drifts[1][1],
        )


def test_packaged_migration_allowlists_and_checksums() -> None:
    assert migration_checksums(AuditDatabaseKind.CONTROL) == (
        (
            "0001_control_audit.sql",
            "5647c7a1dca311a393946282a2824f532bc9cb303a571f2c1065f23b169a98d4",
        ),
    )
    assert migration_checksums(AuditDatabaseKind.CUSTOMER) == (
        (
            "0001_customer_audit.sql",
            "e00021111de6783cf0d4238ae7f4fb74ba44520dfa5eb83a38a8f32d8f778f71",
        ),
    )
    assert b"application_events" in migration_bytes(
        AuditDatabaseKind.CONTROL, "0001_control_audit.sql"
    )
    assert b"FORCE ROW LEVEL SECURITY" in migration_bytes(
        AuditDatabaseKind.CUSTOMER, "0001_customer_audit.sql"
    )
    with pytest.raises(AuditMigrationError):
        migration_bytes(AuditDatabaseKind.CONTROL, "unknown.sql")


class Cursor:
    def __init__(self, rowcount: int = 1, row: tuple[str] | None = None) -> None:
        self.rowcount, self._row = rowcount, row

    async def fetchone(self) -> tuple[str] | None:
        return self._row


class Transaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_: object) -> None:
        return None


class Connection:
    def __init__(
        self, *, duplicate: str | None = None, failure: BaseException | None = None
    ) -> None:
        self.duplicate, self.failure, self.calls = duplicate, failure, []

    def transaction(self) -> Transaction:
        return Transaction()

    async def execute(self, query: str, params: object = None) -> Cursor:
        self.calls.append((query, params))
        if self.failure is not None:
            raise self.failure
        if query.startswith("INSERT") and self.duplicate is not None:
            return Cursor(0)
        if query.startswith("SELECT event_digest"):
            return Cursor(row=None if self.duplicate == "missing" else (self.duplicate,))
        return Cursor()


class ConnectionContext:
    def __init__(self, connection: Connection) -> None:
        self.value = connection

    async def __aenter__(self) -> Connection:
        return self.value

    async def __aexit__(self, *_: object) -> None:
        return None


class Pool:
    def __init__(self, connection: Connection) -> None:
        self.value = connection

    def connection(self) -> ConnectionContext:
        return ConnectionContext(self.value)


class Router:
    def __init__(self, connection: Connection) -> None:
        self.value = Pool(connection)

    def control_pool(self) -> Pool:
        return self.value

    def customer_pool(self, customer_environment_id: str) -> Pool:
        if customer_environment_id != "customer_a":
            raise AuditStorageUnavailable("unavailable")
        return self.value


@pytest.mark.parametrize(
    ("sink_type", "event"),
    (
        (PostgresApplicationAuditSink, application_event()),
        (PostgresAgentAuditSink, agent_event()),
        (PostgresToolAuditSink, tool_event()),
    ),
)
def test_sinks_insert_idempotently_and_conflicts_fail_closed(
    sink_type: type[Any], event: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def verified(*_: object, **__: object) -> None:
        return None

    monkeypatch.setattr(
        "erp_ai.infrastructure.postgres_audit.sinks._verify_write_binding", verified
    )
    first = Connection()
    asyncio.run(sink_type(Router(first), config()).record(event))
    assert sum(query.startswith("INSERT") for query, _ in first.calls) == 1
    asyncio.run(
        sink_type(Router(Connection(duplicate=event_digest(event))), config()).record(event)
    )


class SyntheticDriverError(Error):
    def __init__(self, state: str | None) -> None:
        self._state = state
        super().__init__("private driver detail")

    @property
    def sqlstate(self) -> str | None:
        return self._state


def test_driver_error_translation_uses_only_fixed_conflict_state() -> None:
    assert isinstance(_translate_driver_error(SyntheticDriverError("P2301")), AuditStorageConflict)
    assert isinstance(
        _translate_driver_error(SyntheticDriverError("08006")), AuditStorageUnavailable
    )


@pytest.mark.parametrize(
    ("sink_type", "event"),
    (
        (PostgresApplicationAuditSink, application_event()),
        (PostgresAgentAuditSink, agent_event()),
        (PostgresToolAuditSink, tool_event()),
    ),
)
def test_each_sink_translates_driver_conflict_and_unavailability(
    sink_type: type[Any], event: Any
) -> None:
    with pytest.raises(AuditStorageConflict):
        asyncio.run(
            sink_type(
                Router(Connection(failure=AuditStorageConflict("conflict"))), config()
            ).record(event)
        )
    with pytest.raises(AuditStorageConflict):
        asyncio.run(
            sink_type(Router(Connection(failure=SyntheticDriverError("P2301"))), config()).record(
                event
            )
        )
    with pytest.raises(AuditStorageUnavailable):
        asyncio.run(
            sink_type(Router(Connection(failure=SyntheticDriverError("08006"))), config()).record(
                event
            )
        )


@pytest.mark.parametrize(
    ("sink_type", "event"),
    (
        (PostgresApplicationAuditSink, application_event()),
        (PostgresAgentAuditSink, agent_event()),
        (PostgresToolAuditSink, tool_event()),
    ),
)
def test_sinks_revalidate_translate_errors_and_preserve_cancellation(
    sink_type: type[Any], event: Any
) -> None:
    invalid = event.model_construct(request_id="")
    with pytest.raises(AuditStorageUnavailable, match="audit storage is unavailable"):
        asyncio.run(sink_type(Router(Connection()), config()).record(invalid))
    with pytest.raises(AuditStorageUnavailable, match="audit storage is unavailable"):
        asyncio.run(
            sink_type(Router(Connection(failure=RuntimeError("private"))), config()).record(event)
        )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            sink_type(Router(Connection(failure=asyncio.CancelledError())), config()).record(event)
        )


def test_router_fails_closed_before_open_and_unknown_customer() -> None:
    router = StaticAuditDatabaseRouter(config())
    with pytest.raises(AuditStorageUnavailable):
        router.control_pool()
    with pytest.raises(AuditStorageUnavailable):
        router.customer_pool("customer_a")


class PoolConnectionContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *_: object) -> None:
        return None


class FakeAsyncPool:
    instances: ClassVar[list["FakeAsyncPool"]] = []
    failure: ClassVar[BaseException | None] = None

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.closed = False
        self.instances.append(self)

    async def open(self, *, wait: bool) -> None:
        assert wait is True
        if self.failure is not None:
            raise self.failure

    async def close(self) -> None:
        self.closed = True

    def connection(self) -> PoolConnectionContext:
        return PoolConnectionContext()


def test_router_open_route_close_and_repeated_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    import erp_ai.infrastructure.postgres_audit.routing as routing

    FakeAsyncPool.instances = []
    FakeAsyncPool.failure = None
    verified: list[dict[str, object]] = []

    async def verify(_: object, **values: object) -> None:
        verified.append(values)

    monkeypatch.setattr(routing, "AsyncConnectionPool", FakeAsyncPool)
    monkeypatch.setattr(routing, "verify_database_contract", verify)
    router = StaticAuditDatabaseRouter(config())

    async def exercise() -> None:
        await router.open()
        await router.open()
        assert router.control_pool() is FakeAsyncPool.instances[0]
        assert router.customer_pool("customer_a") is FakeAsyncPool.instances[1]
        with pytest.raises(AuditStorageUnavailable):
            router.customer_pool("unknown")
        await router.close()
        await router.close()

    asyncio.run(exercise())
    assert len(FakeAsyncPool.instances) == 2
    assert all(pool.closed for pool in FakeAsyncPool.instances)
    assert [item["expected_kind"] for item in verified] == [
        AuditDatabaseKind.CONTROL,
        AuditDatabaseKind.CUSTOMER,
    ]


@pytest.mark.parametrize("failure", (RuntimeError("private"), asyncio.CancelledError()))
def test_router_partial_startup_closes_all_pools(
    monkeypatch: pytest.MonkeyPatch, failure: BaseException
) -> None:
    import erp_ai.infrastructure.postgres_audit.routing as routing

    FakeAsyncPool.instances = []
    FakeAsyncPool.failure = failure
    monkeypatch.setattr(routing, "AsyncConnectionPool", FakeAsyncPool)
    router = StaticAuditDatabaseRouter(config())
    expected = (
        asyncio.CancelledError
        if isinstance(failure, asyncio.CancelledError)
        else AuditStorageUnavailable
    )
    with pytest.raises(expected):
        asyncio.run(router.open())
    assert len(FakeAsyncPool.instances) == 2
    assert all(pool.closed for pool in FakeAsyncPool.instances)
