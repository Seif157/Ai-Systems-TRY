import asyncio
import copy
import hashlib
from typing import ClassVar
from uuid import UUID

import pytest
from pydantic import ValidationError

from erp_ai.infrastructure.postgres import (
    KNOWLEDGE_MIGRATION_CHECKSUMS,
    KNOWLEDGE_READ_CONTRACT_DIGEST,
    KNOWLEDGE_READ_CONTRACT_VERSION,
    KnowledgeDatabaseAccess,
    ProductionKnowledgeConfig,
    ProductionKnowledgeDatabaseRouter,
    ProductionKnowledgeRoute,
    SemanticRetrievalPolicy,
    build_production_rag_bundle,
)
from erp_ai.infrastructure.postgres.errors import KnowledgeStorageUnavailable
from erp_ai.infrastructure.postgres.production_rag import (
    _CONTRACT_DESCRIPTOR,
    KNOWLEDGE_READ_CONTRACT_CANONICAL_JSON,
    _canonical_contract_json,
)
from tests.unit.test_embedding_models import profile


def route(customer: str = "customer-a", database: str = "knowledge_a") -> ProductionKnowledgeRoute:
    return ProductionKnowledgeRoute(
        customer_environment_id=customer,
        expected_database_name=database,
        expected_database_identity=customer,
        runtime_dsn=f"postgresql://knowledge_reader:secret@db.example/{database}",
        expected_runtime_role="knowledge_reader",
        expected_extension_owner="knowledge_extension_owner",
        knowledge_contract_version=KNOWLEDGE_READ_CONTRACT_VERSION,
        knowledge_contract_digest=KNOWLEDGE_READ_CONTRACT_DIGEST,
        embedding_model_id="qwen3_embedding_0_6b",
        embedding_model_version="revision_1",
        embedding_provider_id="test_provider",
        embedding_profile_sha256="a" * 64,
        embedding_dimensions=1024,
        expected_generation_id=UUID("00000000-0000-4000-8000-000000000001"),
        expected_generation_digest="b" * 64,
    )


def test_production_read_contract_and_released_migration_hashes_are_golden() -> None:
    assert KNOWLEDGE_READ_CONTRACT_VERSION == "1.0.0"
    assert (
        KNOWLEDGE_READ_CONTRACT_DIGEST
        == "8ba30675da37ccab818d8b7ed8a6d243ca584aff28c84184f30105041be2ba0b"
    )
    assert not KNOWLEDGE_READ_CONTRACT_CANONICAL_JSON.endswith("\n")
    assert '": ' not in KNOWLEDGE_READ_CONTRACT_CANONICAL_JSON
    assert '", ' not in KNOWLEDGE_READ_CONTRACT_CANONICAL_JSON
    assert hashlib.sha256(KNOWLEDGE_READ_CONTRACT_CANONICAL_JSON.encode()).hexdigest() == (
        KNOWLEDGE_READ_CONTRACT_DIGEST
    )


def test_every_contract_section_participates_in_the_digest() -> None:
    variants: list[dict[str, object]] = []
    for top_level in _CONTRACT_DESCRIPTOR:
        changed = copy.deepcopy(_CONTRACT_DESCRIPTOR)
        value = changed[top_level]
        changed[top_level] = f"drift-{value}" if isinstance(value, str) else None
        variants.append(changed)
    for changed in variants:
        assert hashlib.sha256(_canonical_contract_json(changed).encode()).hexdigest() != (
            KNOWLEDGE_READ_CONTRACT_DIGEST
        )
    assert KNOWLEDGE_MIGRATION_CHECKSUMS == (
        (
            "0001_knowledge_schema.sql",
            "23a4fa93f005fd79c92b9243bbfb0daff9af02cb2868e65b6de6bda21d4f595b",
        ),
        (
            "0002_knowledge_security.sql",
            "2f2842df084e09670fa2284059d183d873d39b4c5e78ce04d0880082ab6e3455",
        ),
        (
            "0003_knowledge_embeddings.sql",
            "a6b0c8b8e586c964479d937e7555a894c1acfa6891450f9d0bd13b958a0f66d6",
        ),
        (
            "0004_force_database_identity_rls.sql",
            "ab0ee110e577440b4d8b2a7a04c797d8c1d7334eab65a4926eae5a8f56cb3187",
        ),
    )


def test_production_route_is_strict_frozen_and_repr_safe() -> None:
    item = route()
    rendered = repr(item)
    assert "secret" not in rendered
    assert "db.example" not in rendered
    assert "knowledge_a" not in rendered
    assert "knowledge_reader" not in rendered
    with pytest.raises(ValidationError):
        item.customer_environment_id = "other"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        ProductionKnowledgeRoute.model_validate({**item.model_dump(), "extra": True})


def test_production_route_rejects_contract_identity_and_resource_drift() -> None:
    item = route()
    for change in (
        {"knowledge_contract_version": "2.0.0"},
        {"knowledge_contract_digest": "0" * 64},
        {"embedding_dimensions": 0},
        {"minimum_pool_size": 2, "maximum_pool_size": 1},
    ):
        with pytest.raises(ValidationError):
            ProductionKnowledgeRoute.model_validate({**item.model_dump(), **change})


def test_config_copies_routes_and_rejects_duplicate_bindings() -> None:
    values = [route()]
    config = ProductionKnowledgeConfig(routes=values)
    values.append(route("customer-b", "knowledge_b"))
    assert len(config.routes) == 1
    assert isinstance(config.routes, tuple)
    with pytest.raises(ValidationError, match="customer"):
        ProductionKnowledgeConfig(routes=(route(), route()))
    with pytest.raises(ValidationError, match="identit"):
        ProductionKnowledgeConfig(
            routes=(
                route(),
                route("customer-b", "knowledge_b").model_copy(
                    update={"expected_database_identity": "customer-a"}
                ),
            )
        )
    with pytest.raises(ValidationError, match="databases"):
        ProductionKnowledgeConfig(routes=(route(), route("customer-b", "knowledge_a")))


class FakePool:
    instances: ClassVar[list["FakePool"]] = []
    fail_open: ClassVar[bool] = False

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.closed = False
        self.close_count = 0
        self.instances.append(self)

    async def open(self, *, wait: bool) -> None:
        assert wait
        if self.fail_open:
            raise RuntimeError("private database detail")

    async def close(self) -> None:
        self.closed = True
        self.close_count += 1


class FakeVerifier:
    def __init__(self, failure: BaseException | None = None) -> None:
        self.failure = failure
        self.routes: list[str] = []

    async def verify(self, pool: object, item: ProductionKnowledgeRoute) -> None:
        assert pool is FakePool.instances[-1]
        self.routes.append(item.customer_environment_id)
        if self.failure is not None:
            raise self.failure


def test_reader_router_lifecycle_authority_and_unknown_customer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import erp_ai.infrastructure.postgres.production_rag as production

    FakePool.instances = []
    FakePool.fail_open = False
    monkeypatch.setattr(production, "AsyncConnectionPool", FakePool)
    verifier = FakeVerifier()
    router = ProductionKnowledgeDatabaseRouter(
        ProductionKnowledgeConfig(routes=(route(),)), verifier
    )
    with pytest.raises(KnowledgeStorageUnavailable, match="router"):
        router.pool("customer-a", KnowledgeDatabaseAccess.READER)
    asyncio.run(router.open())
    asyncio.run(router.open())
    assert verifier.routes == ["customer-a"]
    assert len(FakePool.instances) == 1
    assert FakePool.instances[0].kwargs["conninfo"].endswith("/knowledge_a")  # type: ignore[union-attr]
    assert router.pool("customer-a", KnowledgeDatabaseAccess.READER) is FakePool.instances[0]
    with pytest.raises(KnowledgeStorageUnavailable, match="authority"):
        router.pool("customer-a", KnowledgeDatabaseAccess.PUBLISHER)
    with pytest.raises(KnowledgeStorageUnavailable, match="route") as error:
        router.pool("unknown", KnowledgeDatabaseAccess.READER)
    assert "unknown" not in str(error.value)
    asyncio.run(router.close())
    assert FakePool.instances[0].closed


def test_reader_router_concurrent_lifecycle_is_single_owner_and_irreversible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import erp_ai.infrastructure.postgres.production_rag as production

    FakePool.instances = []
    FakePool.fail_open = False
    monkeypatch.setattr(production, "AsyncConnectionPool", FakePool)
    router = ProductionKnowledgeDatabaseRouter(
        ProductionKnowledgeConfig(routes=(route(),)), FakeVerifier()
    )

    async def exercise() -> None:
        await asyncio.gather(router.open(), router.open())
        await asyncio.gather(router.close(), router.close())
        with pytest.raises(KnowledgeStorageUnavailable, match="startup"):
            await router.open()

    asyncio.run(exercise())
    assert len(FakePool.instances) == 1
    assert FakePool.instances[0].close_count == 1
    with pytest.raises(KnowledgeStorageUnavailable, match="router"):
        router.pool("customer-a", KnowledgeDatabaseAccess.READER)


def test_reader_router_state_is_isolated_per_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import erp_ai.infrastructure.postgres.production_rag as production

    FakePool.instances = []
    FakePool.fail_open = False
    monkeypatch.setattr(production, "AsyncConnectionPool", FakePool)
    first = ProductionKnowledgeDatabaseRouter(
        ProductionKnowledgeConfig(routes=(route(),)), FakeVerifier()
    )
    second = ProductionKnowledgeDatabaseRouter(
        ProductionKnowledgeConfig(routes=(route(),)), FakeVerifier()
    )

    async def exercise() -> None:
        await first.open()
        await first.close()
        await second.open()
        assert second.pool("customer-a", KnowledgeDatabaseAccess.READER) is FakePool.instances[1]
        await second.close()

    asyncio.run(exercise())
    assert len(FakePool.instances) == 2
    assert all(pool.close_count == 1 for pool in FakePool.instances)


@pytest.mark.parametrize("failure", [RuntimeError("secret"), asyncio.CancelledError()])
def test_reader_router_partial_startup_cleanup(
    monkeypatch: pytest.MonkeyPatch, failure: BaseException
) -> None:
    import erp_ai.infrastructure.postgres.production_rag as production

    FakePool.instances = []
    FakePool.fail_open = False
    monkeypatch.setattr(production, "AsyncConnectionPool", FakePool)
    router = ProductionKnowledgeDatabaseRouter(
        ProductionKnowledgeConfig(routes=(route(),)), FakeVerifier(failure)
    )
    if isinstance(failure, asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(router.open())
    else:
        with pytest.raises(KnowledgeStorageUnavailable, match="startup") as error:
            asyncio.run(router.open())
        assert "secret" not in str(error.value)
    assert FakePool.instances[0].closed


def test_router_requires_a_real_verifier() -> None:
    with pytest.raises(TypeError, match="verifier"):
        ProductionKnowledgeDatabaseRouter(ProductionKnowledgeConfig(routes=(route(),)), object())  # type: ignore[arg-type]


def test_config_rejects_non_collection_routes() -> None:
    with pytest.raises(ValidationError):
        ProductionKnowledgeConfig.model_validate({"routes": "customer-a"})


class FakeEmbeddingProvider:
    async def embed(self, request: object) -> object:
        raise AssertionError("construction must not perform embedding")


def test_bundle_is_pure_bound_and_rejects_route_or_profile_mismatch() -> None:
    embedding_profile = profile(
        model_id="qwen3_embedding_0_6b", model_revision="revision_1", dimensions=1024
    )
    policy = SemanticRetrievalPolicy(
        namespace="hr",
        embedding_profile_sha256=embedding_profile.profile_sha256,
        minimum_relevance_score=0.7,
        policy_version="1.0.0",
    )
    bound_route = route().model_copy(
        update={"embedding_profile_sha256": embedding_profile.profile_sha256}
    )
    config = ProductionKnowledgeConfig(routes=(bound_route,))
    bundle = build_production_rag_bundle(
        config=config,
        customer_environment_id="customer-a",
        embedding_profile=embedding_profile,
        embedding_provider=FakeEmbeddingProvider(),  # type: ignore[arg-type]
        retrieval_policy=policy,
        verifier=FakeVerifier(),
    )
    assert bundle.provider is not None and bundle.router is not None
    assert "qwen" not in repr(bundle)
    with pytest.raises(KnowledgeStorageUnavailable, match="route"):
        build_production_rag_bundle(
            config=config,
            customer_environment_id="unknown",
            embedding_profile=embedding_profile,
            embedding_provider=FakeEmbeddingProvider(),  # type: ignore[arg-type]
            retrieval_policy=policy,
            verifier=FakeVerifier(),
        )
    with pytest.raises(ValueError, match="embedding profile"):
        build_production_rag_bundle(
            config=config,
            customer_environment_id="customer-a",
            embedding_profile=profile(),
            embedding_provider=FakeEmbeddingProvider(),  # type: ignore[arg-type]
            retrieval_policy=policy,
            verifier=FakeVerifier(),
        )
