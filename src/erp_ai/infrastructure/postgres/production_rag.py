"""Reader-only production routing and lifecycle for customer knowledge databases."""

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from erp_ai.context.models import Identifier
from erp_ai.infrastructure.postgres.errors import KnowledgeStorageUnavailable
from erp_ai.infrastructure.postgres.migrations import MIGRATIONS, _migration_bytes
from erp_ai.infrastructure.postgres.routing import KnowledgeDatabaseAccess
from erp_ai.infrastructure.postgres.semantic_retrieval import (
    SEMANTIC_MAXIMUM_RESULTS,
    SEMANTIC_NAMESPACE,
    SEMANTIC_QUERY_PARAMETER_ORDER,
    PostgresSemanticKnowledgeRetrievalProvider,
    SemanticRetrievalPolicy,
)
from erp_ai.knowledge import KnowledgeRetrievalRequest
from erp_ai.knowledge.embeddings import EmbeddingProfile, EmbeddingProvider

KNOWLEDGE_READ_CONTRACT_VERSION = "1.0.0"
KNOWLEDGE_DATABASE_KIND = "customer_knowledge"
APPROVED_PGVECTOR_VERSION = "0.8.6"
SUPPORTED_POSTGRESQL_MAJORS = (15, 16, 17, 18)
KNOWLEDGE_MIGRATION_CHECKSUMS = tuple(
    (name, hashlib.sha256(_migration_bytes(name)).hexdigest()) for name in MIGRATIONS
)
KNOWLEDGE_READ_RELATION_SIGNATURE = (
    ("active_generations", "customer_environment_id", "text"),
    ("active_generations", "namespace", "text"),
    ("active_generations", "generation_id", "uuid"),
    ("active_generations", "generation_digest", "text"),
    ("active_generations", "publication_contract_version", "integer"),
    ("chunk_embeddings", "customer_environment_id", "text"),
    ("chunk_embeddings", "namespace", "text"),
    ("chunk_embeddings", "generation_id", "uuid"),
    ("chunk_embeddings", "profile_sha256", "text"),
    ("chunk_embeddings", "chunk_id", "text"),
    ("chunk_embeddings", "content_sha256", "text"),
    ("chunk_embeddings", "vector_sha256", "text"),
    ("chunk_embeddings", "embedding", "public.vector"),
    ("chunks", "customer_environment_id", "text"),
    ("chunks", "generation_id", "uuid"),
    ("chunks", "document_id", "uuid"),
    ("chunks", "chunk_id", "text"),
    ("chunks", "citation_id", "text"),
    ("chunks", "document_version", "character varying(64)"),
    ("chunks", "chunk_ordinal", "integer"),
    ("chunks", "namespace", "text"),
    ("chunks", "source_type", "text"),
    ("chunks", "document_customer_environment_id", "text"),
    ("chunks", "required_modules_all", "text[]"),
    ("chunks", "required_permissions_all", "text[]"),
    ("chunks", "allowed_purposes", "text[]"),
    ("chunks", "legal_entity_ids", "text[]"),
    ("chunks", "data_classification", "text"),
    ("chunks", "language", "text"),
    ("chunks", "title", "text"),
    ("chunks", "section", "text"),
    ("chunks", "effective_from", "timestamp with time zone"),
    ("chunks", "effective_to", "timestamp with time zone"),
    ("chunks", "content", "text"),
    ("chunks", "content_sha256", "text"),
    ("chunks", "search_vector", "tsvector"),
    ("database_identity", "singleton", "boolean"),
    ("database_identity", "customer_environment_id", "text"),
    ("database_identity", "provisioned_at", "timestamp with time zone"),
    ("database_identity", "schema_contract_version", "integer"),
    ("documents", "customer_environment_id", "text"),
    ("documents", "generation_id", "uuid"),
    ("documents", "document_id", "uuid"),
    ("documents", "document_version", "character varying(64)"),
    ("documents", "namespace", "text"),
    ("documents", "source_type", "text"),
    ("documents", "document_customer_environment_id", "text"),
    ("documents", "normalized_content_sha256", "text"),
    ("documents", "governance_sha256", "text"),
    ("documents", "document_fingerprint", "text"),
    ("documents", "source_provenance_sha256", "text"),
    ("embedding_profiles", "customer_environment_id", "text"),
    ("embedding_profiles", "profile_sha256", "text"),
    ("embedding_profiles", "profile_id", "text"),
    ("embedding_profiles", "contract_version", "integer"),
    ("embedding_profiles", "provider_id", "text"),
    ("embedding_profiles", "model_id", "text"),
    ("embedding_profiles", "model_revision", "text"),
    ("embedding_profiles", "dimensions", "integer"),
    ("embedding_profiles", "distance_metric", "text"),
    ("embedding_profiles", "storage_representation", "text"),
    ("embedding_profiles", "input_normalization_version", "integer"),
    ("embedding_profiles", "allowed_data_classifications", "text[]"),
    ("embedding_profiles", "created_at", "timestamp with time zone"),
    ("embedding_sets", "customer_environment_id", "text"),
    ("embedding_sets", "namespace", "text"),
    ("embedding_sets", "generation_id", "uuid"),
    ("embedding_sets", "generation_digest", "text"),
    ("embedding_sets", "profile_sha256", "text"),
    ("embedding_sets", "embedding_set_sha256", "text"),
    ("embedding_sets", "embedding_count", "integer"),
    ("embedding_sets", "status", "text"),
    ("embedding_sets", "created_at", "timestamp with time zone"),
    ("embedding_sets", "ready_at", "timestamp with time zone"),
    ("generations", "customer_environment_id", "text"),
    ("generations", "namespace", "text"),
    ("generations", "generation_id", "uuid"),
    ("generations", "generation_digest", "text"),
    ("generations", "publication_contract_version", "integer"),
    ("generations", "document_count", "integer"),
    ("generations", "chunk_count", "integer"),
    ("generations", "total_normalized_bytes", "bigint"),
    ("generations", "status", "text"),
    ("generations", "created_at", "timestamp with time zone"),
    ("schema_migrations", "migration_name", "text"),
    ("schema_migrations", "sha256", "text"),
    ("schema_migrations", "applied_at", "timestamp with time zone"),
)
KNOWLEDGE_READER_RELATIONS = (
    "active_generations",
    "chunk_embeddings",
    "chunks",
    "database_identity",
    "documents",
    "embedding_profiles",
    "embedding_sets",
    "generations",
    "schema_migrations",
)
KNOWLEDGE_RLS_SIGNATURE = tuple(
    (name, True, True) for name in KNOWLEDGE_READER_RELATIONS if name != "schema_migrations"
)
_TENANT_SCOPE_EXPRESSION = "(customer_environment_id = erp_ai_knowledge.runtime_customer_id())"
KNOWLEDGE_POLICY_SIGNATURE = (
    (
        "active_generations",
        "tenant_active_generations",
        "ALL",
        "{public}",
        _TENANT_SCOPE_EXPRESSION,
        _TENANT_SCOPE_EXPRESSION,
    ),
    (
        "chunk_embeddings",
        "tenant_chunk_embeddings",
        "ALL",
        "{public}",
        _TENANT_SCOPE_EXPRESSION,
        _TENANT_SCOPE_EXPRESSION,
    ),
    (
        "chunks",
        "tenant_chunks",
        "ALL",
        "{public}",
        _TENANT_SCOPE_EXPRESSION,
        _TENANT_SCOPE_EXPRESSION,
    ),
    ("database_identity", "tenant_identity", "ALL", "{public}", _TENANT_SCOPE_EXPRESSION, None),
    (
        "documents",
        "tenant_documents",
        "ALL",
        "{public}",
        _TENANT_SCOPE_EXPRESSION,
        _TENANT_SCOPE_EXPRESSION,
    ),
    (
        "embedding_profiles",
        "tenant_embedding_profiles",
        "ALL",
        "{public}",
        _TENANT_SCOPE_EXPRESSION,
        _TENANT_SCOPE_EXPRESSION,
    ),
    (
        "embedding_sets",
        "tenant_embedding_sets",
        "ALL",
        "{public}",
        _TENANT_SCOPE_EXPRESSION,
        _TENANT_SCOPE_EXPRESSION,
    ),
    (
        "generations",
        "tenant_generations",
        "ALL",
        "{public}",
        _TENANT_SCOPE_EXPRESSION,
        _TENANT_SCOPE_EXPRESSION,
    ),
)
_CONTRACT_DESCRIPTOR: dict[str, Any] = {
    "contract_version": KNOWLEDGE_READ_CONTRACT_VERSION,
    "database_kind": KNOWLEDGE_DATABASE_KIND,
    "identity_relation": "erp_ai_knowledge.database_identity",
    "customer_identity_column": "customer_environment_id",
    "migrations": [
        {"name": name, "sha256": digest} for name, digest in KNOWLEDGE_MIGRATION_CHECKSUMS
    ],
    "relation_signature": [list(item) for item in KNOWLEDGE_READ_RELATION_SIGNATURE],
    "security": {
        "reader_relations": list(KNOWLEDGE_READER_RELATIONS),
        "migration_metadata_columns": ["migration_name", "sha256"],
        "rls_signature": [list(item) for item in KNOWLEDGE_RLS_SIGNATURE],
        "policy_signature": [list(item) for item in KNOWLEDGE_POLICY_SIGNATURE],
        "required_indexes": [["chunks_search_vector_gin", "gin"]],
        "forbidden_vector_indexes": ["hnsw", "ivfflat"],
        "runtime_role": {
            "login": True,
            "owner": False,
            "superuser": False,
            "bypass_rls": False,
            "create_role": False,
            "create_database": False,
            "database_create": False,
            "database_temporary": False,
            "schema_create": False,
            "write_privileges": [],
            "role_memberships": [],
        },
    },
    "compatibility": {
        "postgresql_majors": list(SUPPORTED_POSTGRESQL_MAJORS),
        "pgvector_version": APPROVED_PGVECTOR_VERSION,
        "extension_schema": "public",
        "vector_type": "public.vector",
    },
    "publication_binding": [
        "generation_id",
        "generation_digest",
        "publication_contract_version",
        "active_status",
        "ready_embedding_set",
    ],
    "embedding_binding": [
        "profile_sha256",
        "provider_id",
        "model_id",
        "model_revision",
        "dimensions",
        "cosine",
        "float32",
    ],
    "retrieval": {
        "algorithm": "exact_pgvector_cosine_v1",
        "distance_operator": "OPERATOR(public.<=>)",
        "distance_range": [0, 2],
        "score_formula": "1-distance/2",
        "score_range": [0, 1],
        "order": ["cosine_distance_asc", "chunk_id_asc"],
        "namespace": SEMANTIC_NAMESPACE,
        "maximum_results": SEMANTIC_MAXIMUM_RESULTS,
        "ann": False,
        "parameter_order": list(SEMANTIC_QUERY_PARAMETER_ORDER),
    },
}


def _canonical_contract_json(descriptor: dict[str, Any]) -> str:
    return json.dumps(descriptor, ensure_ascii=False, separators=(",", ":"))


KNOWLEDGE_READ_CONTRACT_CANONICAL_JSON = _canonical_contract_json(_CONTRACT_DESCRIPTOR)
KNOWLEDGE_READ_CONTRACT_DIGEST = hashlib.sha256(
    KNOWLEDGE_READ_CONTRACT_CANONICAL_JSON.encode("utf-8")
).hexdigest()


class ProductionKnowledgeRoute(BaseModel):
    """One immutable, trusted, reader-only customer database route."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    customer_environment_id: Identifier
    expected_database_name: Identifier = Field(repr=False)
    expected_database_identity: Identifier = Field(repr=False)
    runtime_dsn: SecretStr = Field(repr=False)
    expected_runtime_role: Identifier = Field(repr=False)
    expected_extension_owner: Identifier = Field(repr=False)
    knowledge_contract_version: str = Field(pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
    knowledge_contract_digest: str = Field(pattern=r"^[0-9a-f]{64}$", repr=False)
    embedding_model_id: Identifier = Field(repr=False)
    embedding_model_version: Identifier = Field(repr=False)
    embedding_provider_id: Identifier = Field(repr=False)
    embedding_profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", repr=False)
    embedding_dimensions: int = Field(strict=True, ge=1, le=4096)
    expected_generation_id: UUID = Field(repr=False)
    expected_generation_digest: str = Field(pattern=r"^[0-9a-f]{64}$", repr=False)
    minimum_pool_size: int = Field(default=1, strict=True, ge=0, le=20)
    maximum_pool_size: int = Field(default=5, strict=True, ge=1, le=50)
    connection_timeout_seconds: float = Field(default=5.0, strict=True, gt=0, le=60)
    statement_timeout_ms: int = Field(default=5_000, strict=True, ge=100, le=60_000)
    lock_timeout_ms: int = Field(default=2_000, strict=True, ge=100, le=60_000)
    idle_transaction_timeout_ms: int = Field(default=10_000, strict=True, ge=100, le=120_000)

    @model_validator(mode="after")
    def validate_route(self) -> "ProductionKnowledgeRoute":
        if self.minimum_pool_size > self.maximum_pool_size:
            raise ValueError("minimum pool size cannot exceed maximum pool size")
        if (
            self.knowledge_contract_version != KNOWLEDGE_READ_CONTRACT_VERSION
            or self.knowledge_contract_digest != KNOWLEDGE_READ_CONTRACT_DIGEST
        ):
            raise ValueError("unsupported knowledge read contract")
        return self


class ProductionKnowledgeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    routes: tuple[ProductionKnowledgeRoute, ...] = Field(min_length=1, repr=False)

    @field_validator("routes", mode="before")
    @classmethod
    def immutable_routes(cls, value: Any) -> Any:
        if not isinstance(value, (list, tuple)):
            return value
        return tuple(
            ProductionKnowledgeRoute.model_validate(
                (
                    item.model_dump(mode="python")
                    if isinstance(item, ProductionKnowledgeRoute)
                    else item
                ),
                strict=True,
            )
            for item in value
        )

    @model_validator(mode="after")
    def unique_routes(self) -> "ProductionKnowledgeConfig":
        customers = [route.customer_environment_id for route in self.routes]
        identities = [route.expected_database_identity for route in self.routes]
        databases = [route.expected_database_name for route in self.routes]
        if len(customers) != len(set(customers)):
            raise ValueError("duplicate customer knowledge routes are forbidden")
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate knowledge database identities are forbidden")
        if len(databases) != len(set(databases)):
            raise ValueError("duplicate customer knowledge databases are forbidden")
        return self


@runtime_checkable
class KnowledgeContractVerifier(Protocol):
    async def verify(self, pool: AsyncConnectionPool, route: ProductionKnowledgeRoute) -> None: ...


class PostgresKnowledgeContractVerifier:  # pragma: no cover - live PostgreSQL boundary
    """Fail-closed catalog verification performed before a route becomes available."""

    async def verify(self, pool: AsyncConnectionPool, route: ProductionKnowledgeRoute) -> None:
        try:
            async with pool.connection() as connection, connection.transaction():
                await connection.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
                await connection.execute(
                    "SELECT set_config('erp_ai.customer_environment_id', %s, true)",
                    (route.customer_environment_id,),
                )
                identity = await (
                    await connection.execute(
                        """SELECT current_database(),current_user,session_user,
                        current_setting('server_version_num')::integer,
                        d.customer_environment_id,d.schema_contract_version,
                        r.rolsuper,r.rolbypassrls,r.rolcreaterole,r.rolcreatedb,r.rolcanlogin
                        FROM erp_ai_knowledge.database_identity d
                        JOIN pg_roles r ON r.rolname=current_user WHERE d.singleton=true"""
                    )
                ).fetchone()
                if identity is None:
                    raise KnowledgeStorageUnavailable("knowledge database contract mismatch")
                server_version = int(identity[3])
                if (
                    identity
                    != (
                        route.expected_database_name,
                        route.expected_runtime_role,
                        route.expected_runtime_role,
                        identity[3],
                        route.expected_database_identity,
                        1,
                        False,
                        False,
                        False,
                        False,
                        True,
                    )
                    or server_version // 10_000 not in SUPPORTED_POSTGRESQL_MAJORS
                ):
                    raise KnowledgeStorageUnavailable("knowledge database contract mismatch")
                vector = await (
                    await connection.execute(
                        """SELECT e.extversion,n.nspname,r.rolname
                        FROM pg_catalog.pg_extension e
                        JOIN pg_catalog.pg_namespace n ON n.oid=e.extnamespace
                        JOIN pg_catalog.pg_roles r ON r.oid=e.extowner
                        WHERE e.extname='vector'"""
                    )
                ).fetchone()
                if vector != (
                    APPROVED_PGVECTOR_VERSION,
                    "public",
                    route.expected_extension_owner,
                ):
                    raise KnowledgeStorageUnavailable("knowledge database contract mismatch")
                vector_objects = await (
                    await connection.execute(
                        """SELECT
                        (SELECT count(*) FROM pg_catalog.pg_type t
                         JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace
                         WHERE n.nspname='public' AND t.typname='vector'),
                        (SELECT count(*) FROM pg_catalog.pg_operator o
                         JOIN pg_catalog.pg_namespace n ON n.oid=o.oprnamespace
                         JOIN pg_catalog.pg_type l ON l.oid=o.oprleft
                         JOIN pg_catalog.pg_namespace ln ON ln.oid=l.typnamespace
                         JOIN pg_catalog.pg_type r ON r.oid=o.oprright
                         JOIN pg_catalog.pg_namespace rn ON rn.oid=r.typnamespace
                         WHERE n.nspname='public' AND o.oprname='<=>'
                           AND ln.nspname='public' AND l.typname='vector'
                           AND rn.nspname='public' AND r.typname='vector')"""
                    )
                ).fetchone()
                if vector_objects != (1, 1):
                    raise KnowledgeStorageUnavailable("knowledge database contract mismatch")
                migrations = tuple(
                    await (
                        await connection.execute(
                            """SELECT migration_name,sha256
                            FROM erp_ai_knowledge.schema_migrations ORDER BY migration_name"""
                        )
                    ).fetchall()
                )
                if migrations != KNOWLEDGE_MIGRATION_CHECKSUMS:
                    raise KnowledgeStorageUnavailable("knowledge database contract mismatch")
                signature = tuple(
                    await (
                        await connection.execute(
                            """SELECT c.relname,a.attname,
                            pg_catalog.format_type(a.atttypid,a.atttypmod)
                            FROM pg_catalog.pg_class c
                            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
                            JOIN pg_catalog.pg_attribute a ON a.attrelid=c.oid
                            WHERE n.nspname='erp_ai_knowledge'
                              AND c.relname=ANY(%s::text[])
                              AND a.attnum>0 AND NOT a.attisdropped
                            ORDER BY c.relname,a.attnum""",
                            (sorted({item[0] for item in KNOWLEDGE_READ_RELATION_SIGNATURE}),),
                        )
                    ).fetchall()
                )
                if signature != KNOWLEDGE_READ_RELATION_SIGNATURE:
                    raise KnowledgeStorageUnavailable("knowledge database contract mismatch")
                profile = await (
                    await connection.execute(
                        """SELECT model_id,model_revision,dimensions
                        FROM erp_ai_knowledge.embedding_profiles
                        WHERE customer_environment_id=%s AND model_id=%s AND model_revision=%s
                        ORDER BY profile_sha256 LIMIT 1""",
                        (
                            route.customer_environment_id,
                            route.embedding_model_id,
                            route.embedding_model_version,
                        ),
                    )
                ).fetchone()
                if profile != (
                    route.embedding_model_id,
                    route.embedding_model_version,
                    route.embedding_dimensions,
                ):
                    raise KnowledgeStorageUnavailable("knowledge database contract mismatch")
                publication = await (
                    await connection.execute(
                        """SELECT a.generation_id,a.generation_digest,
                        a.publication_contract_version,g.status,s.status,s.profile_sha256
                        FROM erp_ai_knowledge.active_generations a
                        JOIN erp_ai_knowledge.generations g
                          ON g.customer_environment_id=a.customer_environment_id
                         AND g.namespace=a.namespace AND g.generation_id=a.generation_id
                         AND g.generation_digest=a.generation_digest
                        JOIN erp_ai_knowledge.embedding_sets s
                          ON s.customer_environment_id=a.customer_environment_id
                         AND s.namespace=a.namespace AND s.generation_id=a.generation_id
                         AND s.generation_digest=a.generation_digest
                        WHERE a.customer_environment_id=%s AND a.namespace=%s
                          AND s.profile_sha256=%s""",
                        (
                            route.customer_environment_id,
                            SEMANTIC_NAMESPACE,
                            route.embedding_profile_sha256,
                        ),
                    )
                ).fetchone()
                if publication != (
                    route.expected_generation_id,
                    route.expected_generation_digest,
                    1,
                    "active",
                    "ready",
                    route.embedding_profile_sha256,
                ):
                    raise KnowledgeStorageUnavailable("knowledge database contract mismatch")
                unsafe = await (
                    await connection.execute(
                        """SELECT has_database_privilege(current_user,current_database(),'CREATE')
                        OR has_database_privilege(current_user,current_database(),'TEMP'),
                        has_schema_privilege(current_user,'erp_ai_knowledge','CREATE')
                        OR has_schema_privilege(current_user,'public','CREATE')"""
                    )
                ).fetchone()
                if unsafe != (False, False):
                    raise KnowledgeStorageUnavailable("knowledge database role is unsafe")
                role_contract = await (
                    await connection.execute(
                        """SELECT
                        (SELECT count(*) FROM pg_catalog.pg_auth_members m
                         JOIN pg_catalog.pg_roles r ON r.oid=m.member
                         WHERE r.rolname=current_user),
                        (SELECT d.datdba=(SELECT oid FROM pg_catalog.pg_roles
                                         WHERE rolname=current_user)
                         FROM pg_catalog.pg_database d WHERE d.datname=current_database()),
                        (SELECT count(*) FROM pg_catalog.pg_class c
                         JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
                         WHERE n.nspname='erp_ai_knowledge' AND c.relkind IN ('r','p')
                           AND c.relowner=(SELECT oid FROM pg_catalog.pg_roles
                                          WHERE rolname=current_user)),
                        (SELECT count(*) FROM pg_catalog.pg_class c
                         JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
                         WHERE n.nspname='erp_ai_knowledge' AND c.relkind IN ('r','p')
                           AND has_table_privilege(current_user,c.oid,
                           'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')),
                        (SELECT count(*) FROM pg_catalog.pg_class c
                         JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
                         WHERE n.nspname='erp_ai_knowledge' AND c.relkind IN ('r','p')
                           AND has_table_privilege(current_user,c.oid,'SELECT'))"""
                    )
                ).fetchone()
                if role_contract != (0, False, 0, 0, len(KNOWLEDGE_READER_RELATIONS) - 1):
                    raise KnowledgeStorageUnavailable("knowledge database role is unsafe")
                selected_relations = tuple(
                    row[0]
                    for row in await (
                        await connection.execute(
                            """SELECT c.relname FROM pg_catalog.pg_class c
                            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
                            WHERE n.nspname='erp_ai_knowledge' AND c.relkind IN ('r','p','v','m')
                              AND has_table_privilege(current_user,c.oid,'SELECT')
                            ORDER BY c.relname"""
                        )
                    ).fetchall()
                )
                if selected_relations != tuple(
                    item for item in KNOWLEDGE_READER_RELATIONS if item != "schema_migrations"
                ):
                    raise KnowledgeStorageUnavailable("knowledge database role is unsafe")
                migration_access = await (
                    await connection.execute(
                        """SELECT
                        has_column_privilege(current_user,
                          'erp_ai_knowledge.schema_migrations','migration_name','SELECT'),
                        has_column_privilege(current_user,
                          'erp_ai_knowledge.schema_migrations','sha256','SELECT'),
                        has_column_privilege(current_user,
                          'erp_ai_knowledge.schema_migrations','applied_at','SELECT'),
                        has_table_privilege(current_user,
                          'erp_ai_knowledge.schema_migrations','INSERT,UPDATE,DELETE,TRUNCATE')"""
                    )
                ).fetchone()
                if migration_access != (True, True, False, False):
                    raise KnowledgeStorageUnavailable("knowledge database role is unsafe")
                owner_contract = tuple(
                    await (
                        await connection.execute(
                            """SELECT DISTINCT r.rolname FROM pg_catalog.pg_class c
                            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
                            JOIN pg_catalog.pg_roles r ON r.oid=c.relowner
                            WHERE n.nspname='erp_ai_knowledge'
                              AND c.relname=ANY(%s::text[]) ORDER BY r.rolname""",
                            (list(KNOWLEDGE_READER_RELATIONS),),
                        )
                    ).fetchall()
                )
                if owner_contract != ((route.expected_extension_owner,),):
                    raise KnowledgeStorageUnavailable("knowledge database role is unsafe")
                sequence_writes = await (
                    await connection.execute(
                        """SELECT count(*) FROM pg_catalog.pg_class c
                        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
                        WHERE n.nspname='erp_ai_knowledge' AND c.relkind='S'
                          AND (has_sequence_privilege(current_user,c.oid,'USAGE')
                            OR has_sequence_privilege(current_user,c.oid,'UPDATE'))"""
                    )
                ).fetchone()
                if sequence_writes != (0,):
                    raise KnowledgeStorageUnavailable("knowledge database role is unsafe")
                rls = tuple(
                    await (
                        await connection.execute(
                            """SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity
                            FROM pg_catalog.pg_class c
                            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
                            WHERE n.nspname='erp_ai_knowledge'
                              AND c.relname=ANY(%s::text[]) ORDER BY c.relname""",
                            ([item[0] for item in KNOWLEDGE_RLS_SIGNATURE],),
                        )
                    ).fetchall()
                )
                if rls != KNOWLEDGE_RLS_SIGNATURE:
                    raise KnowledgeStorageUnavailable("knowledge database contract mismatch")
                policies = tuple(
                    await (
                        await connection.execute(
                            """SELECT tablename,policyname,cmd,roles::text,qual,with_check
                            FROM pg_catalog.pg_policies
                            WHERE schemaname='erp_ai_knowledge'
                              AND tablename=ANY(%s::text[])
                            ORDER BY tablename,policyname""",
                            ([item[0] for item in KNOWLEDGE_POLICY_SIGNATURE],),
                        )
                    ).fetchall()
                )
                if policies != KNOWLEDGE_POLICY_SIGNATURE:
                    raise KnowledgeStorageUnavailable("knowledge database contract mismatch")
                index_contract = await (
                    await connection.execute(
                        """SELECT count(*) FILTER (WHERE c.relname='chunks_search_vector_gin'
                                                   AND am.amname='gin'),
                        count(*) FILTER (WHERE am.amname IN ('hnsw','ivfflat'))
                        FROM pg_catalog.pg_class c
                        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
                        JOIN pg_catalog.pg_index i ON i.indexrelid=c.oid
                        JOIN pg_catalog.pg_am am ON am.oid=c.relam
                        WHERE n.nspname='erp_ai_knowledge'"""
                    )
                ).fetchone()
                if index_contract != (1, 0):
                    raise KnowledgeStorageUnavailable("knowledge database contract mismatch")
                functions = tuple(
                    await (
                        await connection.execute(
                            """SELECT p.proname,r.rolname,p.prosecdef,
                            has_function_privilege(current_user,p.oid,'EXECUTE')
                            FROM pg_catalog.pg_proc p
                            JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
                            JOIN pg_catalog.pg_roles r ON r.oid=p.proowner
                            WHERE n.nspname='erp_ai_knowledge' ORDER BY p.proname"""
                        )
                    ).fetchall()
                )
                if functions != (
                    ("reject_embedding_mutation", route.expected_extension_owner, False, False),
                    (
                        "reject_immutable_generation_content",
                        route.expected_extension_owner,
                        False,
                        False,
                    ),
                    (
                        "reject_ready_embedding_set_mutation",
                        route.expected_extension_owner,
                        False,
                        False,
                    ),
                    ("runtime_customer_id", route.expected_extension_owner, False, True),
                    ("validate_chunk_embedding", route.expected_extension_owner, False, False),
                ):
                    raise KnowledgeStorageUnavailable("knowledge database role is unsafe")
                default_acl_count = await (
                    await connection.execute(
                        """SELECT count(*) FROM pg_catalog.pg_default_acl d
                        LEFT JOIN pg_catalog.pg_namespace n ON n.oid=d.defaclnamespace
                        WHERE (n.nspname='erp_ai_knowledge' OR d.defaclnamespace=0)
                          AND EXISTS (SELECT 1 FROM aclexplode(d.defaclacl) x
                          LEFT JOIN pg_catalog.pg_roles grantee ON grantee.oid=x.grantee
                          WHERE (x.grantee=0 OR grantee.rolname=current_user)
                            AND x.privilege_type IN
                              ('INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER',
                               'CREATE','TEMPORARY'))"""
                    )
                ).fetchone()
                if default_acl_count != (0,):
                    raise KnowledgeStorageUnavailable("knowledge database role is unsafe")
        except asyncio.CancelledError:
            raise
        except KnowledgeStorageUnavailable:
            raise
        except Exception:
            raise KnowledgeStorageUnavailable("knowledge database verification failed") from None


class BoundKnowledgeTransactionVerifier:  # pragma: no cover - live PostgreSQL boundary
    """Revalidates immutable route, release, and embedding bindings on every retrieval."""

    __slots__ = ("_route",)

    def __init__(self, route: ProductionKnowledgeRoute) -> None:
        self._route = ProductionKnowledgeRoute.model_validate(
            route.model_dump(mode="python"), strict=True
        )

    async def verify(
        self,
        connection: Any,
        request: KnowledgeRetrievalRequest,
        profile: EmbeddingProfile,
    ) -> None:
        try:
            binding = await (
                await connection.execute(
                    """SELECT current_database(),current_user,session_user,
                    current_setting('search_path'),
                    current_setting('erp_ai.customer_environment_id',true),
                    d.customer_environment_id,d.schema_contract_version
                    FROM erp_ai_knowledge.database_identity d WHERE d.singleton=true"""
                )
            ).fetchone()
            if binding != (
                self._route.expected_database_name,
                self._route.expected_runtime_role,
                self._route.expected_runtime_role,
                "pg_catalog",
                self._route.customer_environment_id,
                self._route.expected_database_identity,
                1,
            ):
                raise KnowledgeStorageUnavailable("knowledge database binding mismatch")
            if (
                request.customer_environment_id != self._route.customer_environment_id
                or request.namespace != SEMANTIC_NAMESPACE
                or request.maximum_results > SEMANTIC_MAXIMUM_RESULTS
                or profile.profile_sha256 != self._route.embedding_profile_sha256
                or profile.provider_id != self._route.embedding_provider_id
                or profile.model_id != self._route.embedding_model_id
                or profile.model_revision != self._route.embedding_model_version
                or profile.dimensions != self._route.embedding_dimensions
            ):
                raise KnowledgeStorageUnavailable("knowledge database binding mismatch")
            migrations = tuple(
                await (
                    await connection.execute(
                        """SELECT migration_name,sha256
                        FROM erp_ai_knowledge.schema_migrations ORDER BY migration_name"""
                    )
                ).fetchall()
            )
            if migrations != KNOWLEDGE_MIGRATION_CHECKSUMS:
                raise KnowledgeStorageUnavailable("knowledge database binding mismatch")
            publication = await (
                await connection.execute(
                    """SELECT a.generation_id,a.generation_digest,
                    a.publication_contract_version,g.status,s.status,s.profile_sha256,
                    p.provider_id,p.model_id,p.model_revision,p.dimensions,
                    s.embedding_count,g.chunk_count
                    FROM erp_ai_knowledge.active_generations a
                    JOIN erp_ai_knowledge.generations g
                      ON g.customer_environment_id=a.customer_environment_id
                     AND g.namespace=a.namespace AND g.generation_id=a.generation_id
                     AND g.generation_digest=a.generation_digest
                    JOIN erp_ai_knowledge.embedding_sets s
                      ON s.customer_environment_id=a.customer_environment_id
                     AND s.namespace=a.namespace AND s.generation_id=a.generation_id
                     AND s.generation_digest=a.generation_digest
                    JOIN erp_ai_knowledge.embedding_profiles p
                      ON p.customer_environment_id=s.customer_environment_id
                     AND p.profile_sha256=s.profile_sha256
                    WHERE a.customer_environment_id=%s AND a.namespace=%s
                      AND s.profile_sha256=%s""",
                    (
                        self._route.customer_environment_id,
                        SEMANTIC_NAMESPACE,
                        self._route.embedding_profile_sha256,
                    ),
                )
            ).fetchone()
            if (
                publication is None
                or publication[:10]
                != (
                    self._route.expected_generation_id,
                    self._route.expected_generation_digest,
                    1,
                    "active",
                    "ready",
                    self._route.embedding_profile_sha256,
                    self._route.embedding_provider_id,
                    self._route.embedding_model_id,
                    self._route.embedding_model_version,
                    self._route.embedding_dimensions,
                )
                or publication[10] <= 0
                or publication[10] != publication[11]
            ):
                raise KnowledgeStorageUnavailable("knowledge database binding mismatch")
        except asyncio.CancelledError:
            raise
        except KnowledgeStorageUnavailable:
            raise
        except Exception:
            raise KnowledgeStorageUnavailable("knowledge database binding mismatch") from None


class ProductionKnowledgeDatabaseRouter:
    """Owns only reader pools; administrative credentials cannot be represented."""

    __slots__ = ("_config", "_lock", "_pools", "_state", "_verifier")

    def __init__(
        self, config: ProductionKnowledgeConfig, verifier: KnowledgeContractVerifier
    ) -> None:
        if not isinstance(verifier, KnowledgeContractVerifier):
            raise TypeError("knowledge contract verifier is required")
        self._config = ProductionKnowledgeConfig.model_validate(
            config.model_dump(mode="python"), strict=True
        )
        self._verifier = verifier
        self._pools: dict[str, AsyncConnectionPool] = {}
        self._state = "created"
        self._lock = asyncio.Lock()

    async def open(self) -> None:
        async with self._lock:
            if self._state == "ready":
                return
            if self._state != "created":
                raise KnowledgeStorageUnavailable("knowledge database startup is unavailable")
            self._state = "opening"
            pools: dict[str, AsyncConnectionPool] = {}
            try:
                for route in self._config.routes:
                    pool = AsyncConnectionPool(
                        conninfo=route.runtime_dsn.get_secret_value(),
                        min_size=route.minimum_pool_size,
                        max_size=route.maximum_pool_size,
                        timeout=route.connection_timeout_seconds,
                        open=False,
                        kwargs={"autocommit": False},
                    )
                    pools[route.customer_environment_id] = pool
                    await pool.open(wait=True)
                    await self._verifier.verify(pool, route)
            except asyncio.CancelledError:
                for pool in reversed(tuple(pools.values())):
                    await pool.close()
                self._state = "failed"
                raise
            except Exception:
                for pool in reversed(tuple(pools.values())):
                    await pool.close()
                self._state = "failed"
                raise KnowledgeStorageUnavailable("knowledge database startup failed") from None
            self._pools, self._state = pools, "ready"

    async def close(self) -> None:
        async with self._lock:
            if self._state == "closed":
                return
            pools, self._pools = self._pools, {}
            self._state = "closing"
            try:
                for pool in reversed(tuple(pools.values())):
                    await pool.close()
            finally:
                self._state = "closed"

    def pool(
        self, customer_environment_id: Identifier, access: KnowledgeDatabaseAccess
    ) -> AsyncConnectionPool:
        if access is not KnowledgeDatabaseAccess.READER:
            raise KnowledgeStorageUnavailable("knowledge database authority is unavailable")
        if self._state != "ready":
            raise KnowledgeStorageUnavailable("knowledge database router is unavailable")
        try:
            return self._pools[customer_environment_id]
        except KeyError:
            raise KnowledgeStorageUnavailable("knowledge database route is unavailable") from None


@dataclass(frozen=True, slots=True)
class ProductionRagBundle:
    """Externally composed provider plus its single explicit reader-pool lifecycle owner."""

    provider: PostgresSemanticKnowledgeRetrievalProvider = field(repr=False)
    router: ProductionKnowledgeDatabaseRouter = field(repr=False)


def build_production_rag_bundle(
    *,
    config: ProductionKnowledgeConfig,
    customer_environment_id: Identifier,
    embedding_profile: EmbeddingProfile,
    embedding_provider: EmbeddingProvider,
    retrieval_policy: SemanticRetrievalPolicy,
    verifier: KnowledgeContractVerifier,
) -> ProductionRagBundle:
    """Pure construction: performs no I/O and does not own the embedding lifecycle."""

    route = next(
        (item for item in config.routes if item.customer_environment_id == customer_environment_id),
        None,
    )
    if route is None:
        raise KnowledgeStorageUnavailable("knowledge database route is unavailable")
    if (
        route.embedding_profile_sha256 != embedding_profile.profile_sha256
        or route.embedding_provider_id != embedding_profile.provider_id
        or route.embedding_model_id != embedding_profile.model_id
        or route.embedding_model_version != embedding_profile.model_revision
        or route.embedding_dimensions != embedding_profile.dimensions
    ):
        raise ValueError("embedding profile does not match the customer knowledge route")
    router = ProductionKnowledgeDatabaseRouter(config, verifier)
    provider = PostgresSemanticKnowledgeRetrievalProvider(
        router,
        customer_environment_id,
        embedding_profile,
        embedding_provider,
        retrieval_policy,
        (
            route.statement_timeout_ms,
            route.lock_timeout_ms,
            route.idle_transaction_timeout_ms,
        ),
        BoundKnowledgeTransactionVerifier(route),
    )
    return ProductionRagBundle(provider=provider, router=router)
