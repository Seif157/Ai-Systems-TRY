"""Atomic PostgreSQL persistence for complete generation embedding sets."""

import asyncio
import json
from typing import Any
from uuid import uuid4

from psycopg import AsyncConnection
from psycopg.errors import UniqueViolation

from erp_ai.capabilities import DataClassification
from erp_ai.context.models import Identifier
from erp_ai.infrastructure.postgres.errors import (
    KnowledgeDatabaseIdentityError,
    KnowledgeStorageError,
    KnowledgeStorageUnavailable,
)
from erp_ai.infrastructure.postgres.routing import KnowledgeDatabaseAccess, KnowledgeDatabaseRouter
from erp_ai.knowledge.embeddings import (
    EmbeddingGenerationSource,
    EmbeddingInput,
    EmbeddingInputKind,
    EmbeddingMaterializationResult,
    PreparedEmbeddingSet,
)
from erp_ai.knowledge.indexing import KnowledgeIndexScope


class EmbeddingMaterializationConflict(KnowledgeStorageError):
    pass


def _vector_literal(values: tuple[float, ...]) -> str:
    return "[" + ",".join(format(value, ".9g") for value in values) + "]"


class PostgresEmbeddingRepository:  # pragma: no cover - PostgreSQL integration boundary
    __slots__ = ("_customer", "_router")

    def __init__(
        self, router: KnowledgeDatabaseRouter, customer_environment_id: Identifier
    ) -> None:
        self._router = router
        self._customer = customer_environment_id

    async def _establish(self, connection: AsyncConnection[tuple[Any, ...]]) -> None:
        await connection.execute(
            "SELECT set_config('erp_ai.customer_environment_id', %s, true)", (self._customer,)
        )
        identity = await (
            await connection.execute(
                """SELECT customer_environment_id FROM erp_ai_knowledge.database_identity
                WHERE singleton=true"""
            )
        ).fetchone()
        if identity != (self._customer,):
            raise KnowledgeDatabaseIdentityError("knowledge database identity mismatch")

    async def load_generation_source(
        self, scope: KnowledgeIndexScope, generation_id: object
    ) -> EmbeddingGenerationSource:
        if scope.customer_environment_id != self._customer:
            raise KnowledgeDatabaseIdentityError("knowledge database identity mismatch")
        pool = self._router.pool(self._customer, KnowledgeDatabaseAccess.PUBLISHER)
        try:
            async with pool.connection() as connection, connection.transaction():
                await connection.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
                await self._establish(connection)
                generation = await (
                    await connection.execute(
                        """SELECT generation_id,generation_digest,chunk_count
                        FROM erp_ai_knowledge.generations WHERE customer_environment_id=%s
                        AND namespace=%s AND generation_id=%s""",
                        (self._customer, scope.namespace, generation_id),
                    )
                ).fetchone()
                if generation is None:
                    raise KnowledgeStorageUnavailable("embedding generation is unavailable")
                rows = await (
                    await connection.execute(
                        """SELECT chunk_id,content,content_sha256,data_classification
                        FROM erp_ai_knowledge.chunks
                        WHERE customer_environment_id=%s AND generation_id=%s AND namespace=%s
                        ORDER BY chunk_id""",
                        (self._customer, generation_id, scope.namespace),
                    )
                ).fetchall()
                if len(rows) != generation[2]:
                    raise KnowledgeStorageUnavailable("embedding generation is incomplete")
                return EmbeddingGenerationSource(
                    scope=scope,
                    generation_id=generation[0],
                    generation_digest=generation[1],
                    chunks=tuple(
                        EmbeddingInput(
                            input_id=row[0],
                            text=row[1],
                            content_sha256=row[2],
                            data_classification=DataClassification(row[3]),
                            input_kind=EmbeddingInputKind.DOCUMENT,
                        )
                        for row in rows
                    ),
                )
        except asyncio.CancelledError:
            raise
        except (KnowledgeDatabaseIdentityError, KnowledgeStorageUnavailable):
            raise
        except Exception:
            raise KnowledgeStorageUnavailable("embedding generation lookup failed") from None

    async def persist(
        self,
        prepared: PreparedEmbeddingSet,
        *,
        operation_id: Identifier,
        request_id: Identifier,
        actor_id: Identifier,
    ) -> EmbeddingMaterializationResult:
        if prepared.scope.customer_environment_id != self._customer:
            raise KnowledgeDatabaseIdentityError("knowledge database identity mismatch")
        pool = self._router.pool(self._customer, KnowledgeDatabaseAccess.PUBLISHER)
        try:
            async with pool.connection() as connection, connection.transaction():
                await connection.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
                await self._establish(connection)
                existing = await (
                    await connection.execute(
                        """SELECT namespace,generation_id,profile_sha256,embedding_set_sha256,result
                        FROM erp_ai_knowledge.embedding_operations
                        WHERE customer_environment_id=%s AND operation_id=%s""",
                        (self._customer, operation_id),
                    )
                ).fetchone()
                binding = (
                    prepared.scope.namespace,
                    prepared.generation_id,
                    prepared.profile.profile_sha256,
                    prepared.embedding_set_sha256,
                )
                if existing is not None:
                    if existing[:4] != binding:
                        raise EmbeddingMaterializationConflict("embedding operation conflict")
                    payload = (
                        existing[4] if isinstance(existing[4], dict) else json.loads(existing[4])
                    )
                    return EmbeddingMaterializationResult.model_validate_json(json.dumps(payload))
                await self._insert_profile(connection, prepared)
                await connection.execute(
                    """INSERT INTO erp_ai_knowledge.embedding_sets
                    (customer_environment_id,namespace,generation_id,generation_digest,
                     profile_sha256,embedding_set_sha256,embedding_count,status)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,'building')""",
                    (
                        self._customer,
                        prepared.scope.namespace,
                        prepared.generation_id,
                        prepared.generation_digest,
                        prepared.profile.profile_sha256,
                        prepared.embedding_set_sha256,
                        len(prepared.embeddings),
                    ),
                )
                async with connection.cursor() as cursor:
                    await cursor.executemany(
                        """INSERT INTO erp_ai_knowledge.chunk_embeddings
                        (customer_environment_id,namespace,generation_id,profile_sha256,chunk_id,
                         content_sha256,vector_sha256,embedding)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s::public.vector)""",
                        [
                            (
                                self._customer,
                                prepared.scope.namespace,
                                prepared.generation_id,
                                prepared.profile.profile_sha256,
                                item.chunk_id,
                                item.content_sha256,
                                item.vector_sha256,
                                _vector_literal(item.values),
                            )
                            for item in prepared.embeddings
                        ],
                    )
                verified = await (
                    await connection.execute(
                        """SELECT count(*),bool_and(public.vector_dims(e.embedding)=p.dimensions),
                        bool_and(e.content_sha256=c.content_sha256)
                        FROM erp_ai_knowledge.chunk_embeddings e
                        JOIN erp_ai_knowledge.embedding_profiles p USING
                          (customer_environment_id,profile_sha256)
                        JOIN erp_ai_knowledge.chunks c USING
                          (customer_environment_id,generation_id,chunk_id)
                        WHERE e.customer_environment_id=%s AND e.namespace=%s
                          AND e.generation_id=%s AND e.profile_sha256=%s""",
                        (
                            self._customer,
                            prepared.scope.namespace,
                            prepared.generation_id,
                            prepared.profile.profile_sha256,
                        ),
                    )
                ).fetchone()
                if verified != (len(prepared.embeddings), True, True):
                    raise KnowledgeStorageUnavailable("stored embedding verification failed")
                await connection.execute(
                    """UPDATE erp_ai_knowledge.embedding_sets
                    SET status='ready',ready_at=clock_timestamp()
                    WHERE customer_environment_id=%s AND namespace=%s AND generation_id=%s
                      AND profile_sha256=%s AND status='building'""",
                    (
                        self._customer,
                        prepared.scope.namespace,
                        prepared.generation_id,
                        prepared.profile.profile_sha256,
                    ),
                )
                result = EmbeddingMaterializationResult(
                    operation_id=operation_id,
                    scope=prepared.scope,
                    generation_id=prepared.generation_id,
                    generation_digest=prepared.generation_digest,
                    profile_id=prepared.profile.profile_id,
                    profile_sha256=prepared.profile.profile_sha256,
                    embedding_set_sha256=prepared.embedding_set_sha256,
                    embedding_count=len(prepared.embeddings),
                    disposition="materialized",
                )
                await connection.execute(
                    """INSERT INTO erp_ai_knowledge.embedding_operations
                    (customer_environment_id,operation_id,namespace,generation_id,profile_sha256,
                     embedding_set_sha256,result) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)""",
                    (
                        self._customer,
                        operation_id,
                        prepared.scope.namespace,
                        prepared.generation_id,
                        prepared.profile.profile_sha256,
                        prepared.embedding_set_sha256,
                        result.model_dump_json(),
                    ),
                )
                await connection.execute(
                    """INSERT INTO erp_ai_knowledge.embedding_audit_outbox
                    (customer_environment_id,outbox_id,operation_id,request_id,actor_id,namespace,
                     generation_id,generation_digest,embedding_set_sha256,embedding_count,
                     action,outcome)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    'knowledge.embeddings.materialize','succeeded')""",
                    (
                        self._customer,
                        uuid4(),
                        operation_id,
                        request_id,
                        actor_id,
                        prepared.scope.namespace,
                        prepared.generation_id,
                        prepared.generation_digest,
                        prepared.embedding_set_sha256,
                        len(prepared.embeddings),
                    ),
                )
                return result
        except asyncio.CancelledError:
            raise
        except (EmbeddingMaterializationConflict, KnowledgeDatabaseIdentityError):
            raise
        except UniqueViolation:
            raise EmbeddingMaterializationConflict("embedding materialization conflict") from None
        except Exception:
            raise KnowledgeStorageUnavailable("embedding materialization failed") from None

    async def _insert_profile(
        self, connection: AsyncConnection[tuple[Any, ...]], prepared: PreparedEmbeddingSet
    ) -> None:
        profile = prepared.profile
        await connection.execute(
            """INSERT INTO erp_ai_knowledge.embedding_profiles
            (customer_environment_id,profile_sha256,profile_id,contract_version,provider_id,
             model_id,model_revision,dimensions,distance_metric,storage_representation,
             input_normalization_version,allowed_data_classifications)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (customer_environment_id,profile_sha256) DO NOTHING""",
            (
                self._customer,
                profile.profile_sha256,
                profile.profile_id,
                profile.contract_version,
                profile.provider_id,
                profile.model_id,
                profile.model_revision,
                profile.dimensions,
                profile.distance_metric.value,
                profile.storage_representation.value,
                profile.input_normalization_version,
                [item.value for item in profile.allowed_data_classifications],
            ),
        )
        row = await (
            await connection.execute(
                """SELECT profile_id,contract_version,provider_id,model_id,model_revision,
                dimensions,distance_metric,storage_representation,input_normalization_version,
                allowed_data_classifications FROM erp_ai_knowledge.embedding_profiles
                WHERE customer_environment_id=%s AND profile_sha256=%s""",
                (self._customer, profile.profile_sha256),
            )
        ).fetchone()
        expected = (
            profile.profile_id,
            profile.contract_version,
            profile.provider_id,
            profile.model_id,
            profile.model_revision,
            profile.dimensions,
            profile.distance_metric.value,
            profile.storage_representation.value,
            profile.input_normalization_version,
            [item.value for item in profile.allowed_data_classifications],
        )
        if row != expected:
            raise EmbeddingMaterializationConflict("embedding profile conflict")
