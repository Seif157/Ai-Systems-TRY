import asyncio
from pathlib import Path
from typing import ClassVar

import pytest
from pydantic import ValidationError

from erp_ai.infrastructure.postgres.config import (
    KnowledgeDatabaseRouteConfig,
    StaticKnowledgeDatabaseConfig,
)
from erp_ai.infrastructure.postgres.embedding_repository import _vector_literal as stored_vector
from erp_ai.infrastructure.postgres.errors import (
    KnowledgeMigrationError,
    KnowledgeStorageUnavailable,
)
from erp_ai.infrastructure.postgres.knowledge_repository import _provenance_digest
from erp_ai.infrastructure.postgres.migrations import (
    MIGRATIONS,
    _migration_bytes,
    validate_pgvector_version,
    validate_postgres_major,
)
from erp_ai.infrastructure.postgres.routing import (
    KnowledgeDatabaseAccess,
    StaticKnowledgeDatabaseRouter,
)
from erp_ai.infrastructure.postgres.semantic_retrieval import _vector_literal as query_vector
from erp_ai.knowledge.ingestion import SourceProvenance
from tests.unit.test_knowledge_index_publication import bundle


def route(customer: str = "customer-a") -> KnowledgeDatabaseRouteConfig:
    return KnowledgeDatabaseRouteConfig(
        customer_environment_id=customer,
        reader_dsn="postgresql://reader:secret@db.example/knowledge",
        publisher_dsn="postgresql://publisher:secret@db.example/knowledge",
        migration_dsn="postgresql://owner:secret@db.example/knowledge",
    )


def test_static_config_is_strict_repr_safe_and_rejects_duplicates() -> None:
    item = route()
    assert "secret" not in repr(item) and "db.example" not in repr(item)
    config = StaticKnowledgeDatabaseConfig(routes=[item])
    assert isinstance(config.routes, tuple) and "secret" not in repr(config)
    with pytest.raises(ValidationError, match="duplicate"):
        StaticKnowledgeDatabaseConfig(routes=(item, item))
    with pytest.raises(ValidationError, match="minimum"):
        StaticKnowledgeDatabaseConfig(routes=(item,), minimum_pool_size=2, maximum_pool_size=1)
    with pytest.raises(ValidationError):
        KnowledgeDatabaseRouteConfig(**{**item.model_dump(), "unknown": True})


@pytest.mark.parametrize("server_version", [150000, 160009, 170002, 180000])
def test_supported_postgres_versions(server_version: int) -> None:
    validate_postgres_major(server_version)


@pytest.mark.parametrize("server_version", [140013, 190000])
def test_unsupported_postgres_versions(server_version: int) -> None:
    with pytest.raises(KnowledgeMigrationError, match="unsupported"):
        validate_postgres_major(server_version)


@pytest.mark.parametrize("extension_version", ["0.8.6", "0.9.0", "1.0.0"])
def test_supported_pgvector_versions(extension_version: str) -> None:
    validate_pgvector_version(extension_version)


@pytest.mark.parametrize("extension_version", [None, "0.8.5", "invalid"])
def test_missing_old_or_invalid_pgvector(extension_version: str | None) -> None:
    with pytest.raises(KnowledgeMigrationError):
        validate_pgvector_version(extension_version)


def test_only_known_packaged_migrations_are_readable() -> None:
    assert MIGRATIONS == (
        "0001_knowledge_schema.sql",
        "0002_knowledge_security.sql",
        "0003_knowledge_embeddings.sql",
    )
    for name in MIGRATIONS:
        raw = _migration_bytes(name)
        assert raw and b"erp_ai_knowledge" in raw
    with pytest.raises(KnowledgeMigrationError, match="unknown"):
        _migration_bytes("../../secret")


class FakePool:
    instances: ClassVar[list["FakePool"]] = []
    failure: ClassVar[BaseException | None] = None

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.closed = False
        self.instances.append(self)

    async def open(self, *, wait: bool) -> None:
        assert wait
        if self.failure is not None:
            raise self.failure

    async def close(self) -> None:
        self.closed = True


def test_router_explicit_lifecycle_and_unknown_customer(monkeypatch: pytest.MonkeyPatch) -> None:
    import erp_ai.infrastructure.postgres.routing as routing

    FakePool.instances = []
    FakePool.failure = None
    monkeypatch.setattr(routing, "AsyncConnectionPool", FakePool)
    router = StaticKnowledgeDatabaseRouter(StaticKnowledgeDatabaseConfig(routes=(route(),)))
    with pytest.raises(KnowledgeStorageUnavailable, match="router"):
        router.pool("customer-a", KnowledgeDatabaseAccess.READER)
    asyncio.run(router.open())
    asyncio.run(router.open())
    assert len(FakePool.instances) == 3
    selected = router.pool("customer-a", KnowledgeDatabaseAccess.READER)
    assert selected is FakePool.instances[0]
    assert "secret" not in repr(router)
    with pytest.raises(KnowledgeStorageUnavailable, match="route") as error:
        router.pool("unknown", KnowledgeDatabaseAccess.READER)
    assert "postgresql" not in str(error.value)
    asyncio.run(router.close())
    assert all(pool.closed for pool in FakePool.instances)


@pytest.mark.parametrize("failure", [RuntimeError("failed"), asyncio.CancelledError()])
def test_router_open_failure_closes_partial_pools(
    monkeypatch: pytest.MonkeyPatch, failure: BaseException
) -> None:
    import erp_ai.infrastructure.postgres.routing as routing

    FakePool.instances = []
    FakePool.failure = failure
    monkeypatch.setattr(routing, "AsyncConnectionPool", FakePool)
    router = StaticKnowledgeDatabaseRouter(StaticKnowledgeDatabaseConfig(routes=(route(),)))
    if isinstance(failure, asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(router.open())
    else:
        with pytest.raises(KnowledgeStorageUnavailable, match="pools"):
            asyncio.run(router.open())
    assert all(pool.closed for pool in FakePool.instances)


def test_sql_contract_contains_rls_fts_identity_and_no_vector_column() -> None:
    sql_root = Path("src/erp_ai/infrastructure/postgres/sql")
    schema = (sql_root / "0001_knowledge_schema.sql").read_text(encoding="utf-8")
    security = (sql_root / "0002_knowledge_security.sql").read_text(encoding="utf-8")
    assert "database_identity" in schema
    assert "to_tsvector('simple'" in schema and "USING gin" in schema
    assert "embedding vector" not in schema.lower() and "using hnsw" not in schema.lower()
    assert "FORCE ROW LEVEL SECURITY" in security
    assert "current_setting('erp_ai.customer_environment_id', true)" in security


def test_embedding_migration_has_exact_vectors_rls_immutability_and_no_approximate_index() -> None:
    migration = Path(
        "src/erp_ai/infrastructure/postgres/sql/0003_knowledge_embeddings.sql"
    ).read_text(encoding="utf-8")
    lowered = migration.lower()
    assert "embedding vector not null" in lowered
    assert "vector_dims" in lowered
    assert "force row level security" in lowered
    assert "embedding_audit_outbox" in lowered
    assert "reject_embedding_mutation" in lowered
    assert "using hnsw" not in lowered and "using ivfflat" not in lowered
    assert stored_vector((0.1, -2.0)) == query_vector((0.1, -2.0)) == "[0.1,-2]"


def test_path_free_source_provenance_digest_is_stable() -> None:
    without = _provenance_digest(bundle())
    provenance = SourceProvenance(
        catalog_version=1,
        raw_source_sha256="a" * 64,
        parser_name="markdown-it-py",
        parser_major_version=4,
        adapter_contract_version=1,
    )
    with_provenance = _provenance_digest(bundle(provenance=provenance))
    assert without != with_provenance
