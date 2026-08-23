"""Psycopg async atomic persistence for Step 12 publication contracts."""

import asyncio
import hashlib
import json
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.errors import SerializationFailure, UniqueViolation

from erp_ai.context.models import Identifier
from erp_ai.infrastructure.postgres.errors import (
    KnowledgeDatabaseIdentityError,
    KnowledgeStorageUnavailable,
)
from erp_ai.infrastructure.postgres.routing import (
    KnowledgeDatabaseAccess,
    KnowledgeDatabaseRouter,
)
from erp_ai.knowledge.indexing import (
    KnowledgeIndexScope,
    KnowledgeIndexSnapshot,
    KnowledgePublicationConflict,
    KnowledgePublicationPlan,
    KnowledgePublicationResult,
    KnowledgeRollbackRequest,
    KnowledgeRollbackResult,
    PublicationDisposition,
)
from erp_ai.knowledge.indexing.models import KnowledgeOperationResult
from erp_ai.knowledge.ingestion.models import PreparedKnowledgeBundle


def _provenance_digest(plan_bundle: PreparedKnowledgeBundle) -> str:
    manifest = plan_bundle.manifest
    value = manifest.source_provenance
    payload = None if value is None else value.model_dump(mode="json")
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class PostgresKnowledgeIndexRepository:  # pragma: no cover - PostgreSQL integration boundary
    """One trusted-customer repository routed to that customer's physical database."""

    __slots__ = ("_customer", "_idle_timeout", "_lock_timeout", "_router", "_statement_timeout")

    def __init__(
        self,
        router: KnowledgeDatabaseRouter,
        customer_environment_id: Identifier,
        *,
        statement_timeout_ms: int = 5_000,
        lock_timeout_ms: int = 2_000,
        idle_transaction_timeout_ms: int = 10_000,
    ) -> None:
        self._router = router
        self._customer = customer_environment_id
        self._statement_timeout = statement_timeout_ms
        self._lock_timeout = lock_timeout_ms
        self._idle_timeout = idle_transaction_timeout_ms

    async def _establish_transaction(self, connection: AsyncConnection[tuple[Any, ...]]) -> None:
        await connection.execute(
            "SELECT set_config('erp_ai.customer_environment_id', %s, true)", (self._customer,)
        )
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (f"{self._statement_timeout}ms",),
        )
        await connection.execute(
            "SELECT set_config('lock_timeout', %s, true)", (f"{self._lock_timeout}ms",)
        )
        await connection.execute(
            "SELECT set_config('idle_in_transaction_session_timeout', %s, true)",
            (f"{self._idle_timeout}ms",),
        )
        row = await (
            await connection.execute(
                """SELECT customer_environment_id, schema_contract_version
                FROM erp_ai_knowledge.database_identity WHERE singleton=true"""
            )
        ).fetchone()
        if row is None or row[0] != self._customer or row[1] != 1:
            raise KnowledgeDatabaseIdentityError("knowledge database identity mismatch")

    def _assert_scope(self, customer: str) -> None:
        if customer != self._customer:
            raise KnowledgeDatabaseIdentityError("knowledge database identity mismatch")

    async def _operation(
        self, connection: AsyncConnection[tuple[Any, ...]], operation_id: Identifier
    ) -> KnowledgeOperationResult | None:
        row = await (
            await connection.execute(
                """SELECT operation_type, result FROM erp_ai_knowledge.operations
                WHERE customer_environment_id=%s AND operation_id=%s""",
                (self._customer, operation_id),
            )
        ).fetchone()
        if row is None:
            return None
        payload = row[1] if isinstance(row[1], dict) else json.loads(row[1])
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if row[0] == "publish":
            return KnowledgePublicationResult.model_validate_json(serialized)
        return KnowledgeRollbackResult.model_validate_json(serialized)

    async def get_operation_result(
        self, operation_id: Identifier
    ) -> KnowledgeOperationResult | None:
        pool = self._router.pool(self._customer, KnowledgeDatabaseAccess.PUBLISHER)
        try:
            async with pool.connection() as connection, connection.transaction():
                await self._establish_transaction(connection)
                return await self._operation(connection, operation_id)
        except asyncio.CancelledError:
            raise
        except KnowledgeDatabaseIdentityError:
            raise
        except Exception:
            raise KnowledgeStorageUnavailable("knowledge operation lookup failed") from None

    async def commit_generation(
        self, plan: KnowledgePublicationPlan, expected_active_generation_id: UUID | None
    ) -> KnowledgePublicationResult:
        self._assert_scope(plan.manifest.scope.customer_environment_id)
        pool = self._router.pool(self._customer, KnowledgeDatabaseAccess.PUBLISHER)
        try:
            async with pool.connection() as connection, connection.transaction():
                await connection.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
                await self._establish_transaction(connection)
                existing = await self._operation(connection, plan.context.operation_id)
                if existing is not None:
                    if (
                        not isinstance(existing, KnowledgePublicationResult)
                        or existing.operation_digest != plan.operation_digest
                    ):
                        raise KnowledgePublicationConflict("publication operation conflict")
                    return existing
                active = await (
                    await connection.execute(
                        """SELECT generation_id FROM erp_ai_knowledge.active_generations
                            WHERE customer_environment_id=%s AND namespace=%s FOR UPDATE""",
                        (self._customer, plan.manifest.scope.namespace),
                    )
                ).fetchone()
                current = None if active is None else active[0]
                if current != expected_active_generation_id:
                    raise KnowledgePublicationConflict("active generation changed")
                await self._insert_generation(connection, plan)
                if current is not None:
                    await connection.execute(
                        """UPDATE erp_ai_knowledge.generations SET status='retired'
                            WHERE customer_environment_id=%s AND generation_id=%s""",
                        (self._customer, current),
                    )
                await connection.execute(
                    """UPDATE erp_ai_knowledge.generations SET status='active'
                        WHERE customer_environment_id=%s AND generation_id=%s""",
                    (self._customer, plan.manifest.generation_id),
                )
                await connection.execute(
                    """INSERT INTO erp_ai_knowledge.active_generations
                        (customer_environment_id, namespace, generation_id, generation_digest,
                         publication_contract_version) VALUES (%s,%s,%s,%s,%s)
                        ON CONFLICT (customer_environment_id, namespace) DO UPDATE SET
                        generation_id=EXCLUDED.generation_id,
                        generation_digest=EXCLUDED.generation_digest,
                        publication_contract_version=EXCLUDED.publication_contract_version""",
                    (
                        self._customer,
                        plan.manifest.scope.namespace,
                        plan.manifest.generation_id,
                        plan.manifest.generation_digest,
                        plan.manifest.publication_contract_version,
                    ),
                )
                result = KnowledgePublicationResult(
                    operation_id=plan.context.operation_id,
                    scope=plan.manifest.scope,
                    generation_id=plan.manifest.generation_id,
                    previous_generation_id=current,
                    generation_digest=plan.manifest.generation_digest,
                    operation_digest=plan.operation_digest,
                    disposition=PublicationDisposition.PUBLISHED,
                )
                await self._persist_result_and_outbox(connection, plan, result, current)
                return result
        except asyncio.CancelledError:
            raise
        except (KnowledgePublicationConflict, KnowledgeDatabaseIdentityError):
            raise
        except (SerializationFailure, UniqueViolation):
            raise KnowledgePublicationConflict(
                "concurrent knowledge publication conflict"
            ) from None
        except Exception:
            raise KnowledgeStorageUnavailable("knowledge publication failed") from None

    async def _insert_generation(
        self, connection: AsyncConnection[tuple[Any, ...]], plan: KnowledgePublicationPlan
    ) -> None:
        manifest = plan.manifest
        await connection.execute(
            """INSERT INTO erp_ai_knowledge.generations
            (customer_environment_id,namespace,generation_id,generation_digest,
             publication_contract_version,document_count,chunk_count,total_normalized_bytes,status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'candidate')""",
            (
                self._customer,
                manifest.scope.namespace,
                manifest.generation_id,
                manifest.generation_digest,
                manifest.publication_contract_version,
                manifest.document_count,
                manifest.chunk_count,
                manifest.total_normalized_bytes,
            ),
        )
        document_rows: list[tuple[object, ...]] = []
        chunk_rows: list[tuple[object, ...]] = []
        for bundle in plan.bundles:
            source = bundle.manifest
            document_rows.append(
                (
                    self._customer,
                    manifest.generation_id,
                    source.document_id,
                    source.document_version,
                    source.namespace,
                    source.source_type.value,
                    source.customer_environment_id,
                    source.normalized_content_sha256,
                    source.governance_sha256,
                    source.document_fingerprint,
                    _provenance_digest(bundle),
                )
            )
            for chunk in bundle.chunks:
                chunk_rows.append(
                    (
                        self._customer,
                        manifest.generation_id,
                        chunk.document_id,
                        chunk.chunk_id,
                        chunk.citation_id,
                        chunk.document_version,
                        chunk.chunk_ordinal,
                        chunk.namespace,
                        chunk.source_type.value,
                        chunk.customer_environment_id,
                        list(chunk.required_modules_all),
                        list(chunk.required_permissions_all),
                        list(chunk.allowed_purposes),
                        list(chunk.legal_entity_ids),
                        chunk.data_classification.value,
                        chunk.language,
                        chunk.title,
                        chunk.heading,
                        chunk.effective_from,
                        chunk.effective_to,
                        chunk.content,
                        hashlib.sha256(chunk.content.encode()).hexdigest(),
                    )
                )
        async with connection.cursor() as cursor:
            await cursor.executemany(
                """INSERT INTO erp_ai_knowledge.documents
            (customer_environment_id,generation_id,document_id,document_version,namespace,
             source_type,document_customer_environment_id,normalized_content_sha256,
             governance_sha256,document_fingerprint,source_provenance_sha256)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                document_rows,
            )
            await cursor.executemany(
                """INSERT INTO erp_ai_knowledge.chunks
            (customer_environment_id,generation_id,document_id,chunk_id,citation_id,
             document_version,chunk_ordinal,namespace,source_type,document_customer_environment_id,
             required_modules_all,required_permissions_all,allowed_purposes,legal_entity_ids,
             data_classification,language,title,section,effective_from,effective_to,content,content_sha256)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                chunk_rows,
            )
        counts = await (
            await connection.execute(
                """SELECT
                (SELECT count(*) FROM erp_ai_knowledge.documents
                 WHERE customer_environment_id=%s AND generation_id=%s),
                (SELECT count(*) FROM erp_ai_knowledge.chunks
                 WHERE customer_environment_id=%s AND generation_id=%s),
                (SELECT generation_digest FROM erp_ai_knowledge.generations
                 WHERE customer_environment_id=%s AND generation_id=%s)""",
                (
                    self._customer,
                    manifest.generation_id,
                    self._customer,
                    manifest.generation_id,
                    self._customer,
                    manifest.generation_id,
                ),
            )
        ).fetchone()
        if counts != (
            manifest.document_count,
            manifest.chunk_count,
            manifest.generation_digest,
        ):
            raise KnowledgeStorageUnavailable("stored knowledge generation verification failed")

    async def _persist_result_and_outbox(
        self,
        connection: AsyncConnection[tuple[Any, ...]],
        plan: KnowledgePublicationPlan,
        result: KnowledgePublicationResult,
        previous: UUID | None,
    ) -> None:
        await connection.execute(
            """INSERT INTO erp_ai_knowledge.operations
            (customer_environment_id,operation_id,namespace,operation_type,operation_digest,result)
            VALUES (%s,%s,%s,'publish',%s,%s::jsonb)""",
            (
                self._customer,
                plan.context.operation_id,
                plan.manifest.scope.namespace,
                plan.operation_digest,
                result.model_dump_json(),
            ),
        )
        event = plan.outbox_event
        await connection.execute(
            """INSERT INTO erp_ai_knowledge.publication_audit_outbox
            (customer_environment_id,outbox_id,operation_id,request_id,actor_id,namespace,action,
             previous_generation_id,activated_generation_id,generation_digest,outcome)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                self._customer,
                event.outbox_id,
                event.operation_id,
                event.request_id,
                event.actor_id,
                event.namespace,
                event.action,
                previous,
                event.activated_generation_id,
                event.generation_digest,
                event.outcome,
            ),
        )

    async def get_active_snapshot(
        self, scope: KnowledgeIndexScope
    ) -> KnowledgeIndexSnapshot | None:
        self._assert_scope(scope.customer_environment_id)
        pool = self._router.pool(self._customer, KnowledgeDatabaseAccess.READER)
        try:
            async with pool.connection() as connection, connection.transaction():
                await connection.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
                await self._establish_transaction(connection)
                row = await (
                    await connection.execute(
                        """SELECT generation_id,generation_digest,publication_contract_version
                            FROM erp_ai_knowledge.active_generations
                            WHERE customer_environment_id=%s AND namespace=%s""",
                        (self._customer, scope.namespace),
                    )
                ).fetchone()
                if row is None:
                    return None
                return KnowledgeIndexSnapshot(
                    scope=scope,
                    active_generation_id=row[0],
                    generation_digest=row[1],
                    publication_contract_version=row[2],
                )
        except asyncio.CancelledError:
            raise
        except KnowledgeDatabaseIdentityError:
            raise
        except Exception:
            raise KnowledgeStorageUnavailable("knowledge snapshot lookup failed") from None

    async def commit_rollback(
        self, request: KnowledgeRollbackRequest, expected_active_generation_id: UUID
    ) -> KnowledgeRollbackResult:
        self._assert_scope(request.scope.customer_environment_id)
        pool = self._router.pool(self._customer, KnowledgeDatabaseAccess.PUBLISHER)
        try:
            async with pool.connection() as connection, connection.transaction():
                await connection.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
                await self._establish_transaction(connection)
                existing = await self._operation(connection, request.context.operation_id)
                if existing is not None:
                    if (
                        not isinstance(existing, KnowledgeRollbackResult)
                        or existing.operation_digest != request.operation_digest
                    ):
                        raise KnowledgePublicationConflict("rollback operation conflict")
                    return existing
                active = await (
                    await connection.execute(
                        """SELECT generation_id FROM erp_ai_knowledge.active_generations
                            WHERE customer_environment_id=%s AND namespace=%s FOR UPDATE""",
                        (self._customer, request.scope.namespace),
                    )
                ).fetchone()
                current = None if active is None else active[0]
                if current != expected_active_generation_id:
                    raise KnowledgePublicationConflict("active generation changed")
                target = await (
                    await connection.execute(
                        """SELECT generation_digest,publication_contract_version
                            FROM erp_ai_knowledge.generations
                            WHERE customer_environment_id=%s AND namespace=%s
                              AND generation_id=%s AND status='retired' FOR UPDATE""",
                        (self._customer, request.scope.namespace, request.target_generation_id),
                    )
                ).fetchone()
                if target is None:
                    raise KnowledgePublicationConflict("rollback target is unavailable")
                await connection.execute(
                    """UPDATE erp_ai_knowledge.generations SET status='retired'
                        WHERE customer_environment_id=%s AND generation_id=%s""",
                    (self._customer, current),
                )
                await connection.execute(
                    """UPDATE erp_ai_knowledge.generations SET status='active'
                        WHERE customer_environment_id=%s AND generation_id=%s""",
                    (self._customer, request.target_generation_id),
                )
                await connection.execute(
                    """UPDATE erp_ai_knowledge.active_generations
                        SET generation_id=%s,generation_digest=%s,publication_contract_version=%s
                        WHERE customer_environment_id=%s AND namespace=%s""",
                    (
                        request.target_generation_id,
                        target[0],
                        target[1],
                        self._customer,
                        request.scope.namespace,
                    ),
                )
                result = KnowledgeRollbackResult(
                    operation_id=request.context.operation_id,
                    scope=request.scope,
                    activated_generation_id=request.target_generation_id,
                    previous_generation_id=current,
                    generation_digest=target[0],
                    operation_digest=request.operation_digest,
                    disposition=PublicationDisposition.ROLLED_BACK,
                )
                await connection.execute(
                    """INSERT INTO erp_ai_knowledge.operations
                        (customer_environment_id,operation_id,namespace,operation_type,operation_digest,result)
                        VALUES (%s,%s,%s,'rollback',%s,%s::jsonb)""",
                    (
                        self._customer,
                        request.context.operation_id,
                        request.scope.namespace,
                        request.operation_digest,
                        result.model_dump_json(),
                    ),
                )
                await connection.execute(
                    """INSERT INTO erp_ai_knowledge.publication_audit_outbox
                        (customer_environment_id,outbox_id,operation_id,request_id,actor_id,namespace,
                         action,previous_generation_id,activated_generation_id,generation_digest,outcome)
                        VALUES (%s,%s,%s,%s,%s,%s,'knowledge.rollback',%s,%s,%s,'succeeded')""",
                    (
                        self._customer,
                        request.outbox_id,
                        request.context.operation_id,
                        request.context.request_id,
                        request.context.actor_id,
                        request.scope.namespace,
                        current,
                        request.target_generation_id,
                        target[0],
                    ),
                )
                return result
        except asyncio.CancelledError:
            raise
        except (KnowledgePublicationConflict, KnowledgeDatabaseIdentityError):
            raise
        except (SerializationFailure, UniqueViolation):
            raise KnowledgePublicationConflict("concurrent knowledge rollback conflict") from None
        except Exception:
            raise KnowledgeStorageUnavailable("knowledge rollback failed") from None
