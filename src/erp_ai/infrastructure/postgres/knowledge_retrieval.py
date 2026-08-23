"""Exact parameterized PostgreSQL lexical retrieval bound to one active snapshot."""

import asyncio
from decimal import Decimal
from typing import Any, cast

from erp_ai.infrastructure.postgres.errors import (
    KnowledgeDatabaseIdentityError,
    KnowledgeStorageUnavailable,
)
from erp_ai.infrastructure.postgres.routing import (
    KnowledgeDatabaseAccess,
    KnowledgeDatabaseRouter,
)
from erp_ai.knowledge import KnowledgeMatch, KnowledgeRetrievalRequest, KnowledgeSourceType

_LEXICAL_QUERY = """
WITH query AS (SELECT plainto_tsquery('simple', %s) AS value),
ranked AS (
    SELECT c.*,
           ts_rank_cd(c.search_vector, query.value)::numeric AS raw_rank
    FROM erp_ai_knowledge.chunks AS c
    CROSS JOIN query
    WHERE c.customer_environment_id=%s
      AND c.generation_id=%s
      AND c.namespace=%s
      AND (c.source_type='product_documentation'
           OR (c.source_type='customer_policy' AND c.document_customer_environment_id=%s))
      AND c.required_modules_all <@ %s::text[]
      AND c.required_permissions_all <@ %s::text[]
      AND %s = ANY(c.allowed_purposes)
      AND c.legal_entity_ids <@ %s::text[]
      AND c.effective_from <= %s
      AND (c.effective_to IS NULL OR c.effective_to > %s)
      AND CASE c.data_classification
          WHEN 'public' THEN 0 WHEN 'internal' THEN 1 WHEN 'restricted' THEN 2 ELSE 3 END <= 2
      AND c.search_vector @@ query.value
)
SELECT chunk_id,document_id,citation_id,namespace,source_type,
       document_customer_environment_id,required_modules_all,required_permissions_all,
       allowed_purposes,legal_entity_ids,data_classification,language,title,section,
       document_version,effective_from,effective_to,content,
       raw_rank / (1 + raw_rank) AS normalized_rank
FROM ranked
ORDER BY normalized_rank DESC, chunk_id ASC
LIMIT %s
"""


class PostgresLexicalKnowledgeRetrievalProvider:  # pragma: no cover - integration boundary
    __slots__ = ("_customer", "_router")

    def __init__(self, router: KnowledgeDatabaseRouter, customer_environment_id: str) -> None:
        self._router = router
        self._customer = customer_environment_id

    async def retrieve(self, request: KnowledgeRetrievalRequest) -> tuple[KnowledgeMatch, ...]:
        if request.customer_environment_id != self._customer:
            raise KnowledgeDatabaseIdentityError("knowledge database identity mismatch")
        pool = self._router.pool(self._customer, KnowledgeDatabaseAccess.READER)
        try:
            async with pool.connection() as connection, connection.transaction():
                await connection.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
                await connection.execute(
                    "SELECT set_config('erp_ai.customer_environment_id', %s, true)",
                    (self._customer,),
                )
                await connection.execute(
                    "SELECT set_config('statement_timeout', %s, true)", ("5000ms",)
                )
                await connection.execute("SELECT set_config('lock_timeout', %s, true)", ("2000ms",))
                await connection.execute(
                    "SELECT set_config('idle_in_transaction_session_timeout', %s, true)",
                    ("10000ms",),
                )
                identity = await (
                    await connection.execute(
                        """SELECT customer_environment_id FROM
                            erp_ai_knowledge.database_identity WHERE singleton=true"""
                    )
                ).fetchone()
                if identity is None or identity[0] != self._customer:
                    raise KnowledgeDatabaseIdentityError("knowledge database identity mismatch")
                active = await (
                    await connection.execute(
                        """SELECT generation_id FROM erp_ai_knowledge.active_generations
                            WHERE customer_environment_id=%s AND namespace=%s""",
                        (self._customer, request.namespace),
                    )
                ).fetchone()
                if active is None:
                    return ()
                cursor = await connection.execute(
                    _LEXICAL_QUERY,
                    (
                        request.query,
                        self._customer,
                        active[0],
                        request.namespace,
                        self._customer,
                        list(request.enabled_modules),
                        list(request.permission_codes),
                        request.purpose,
                        list(request.authorized_legal_entity_ids),
                        request.effective_at,
                        request.effective_at,
                        request.maximum_results,
                    ),
                )
                rows = await cursor.fetchall()
                return tuple(self._match(row) for row in rows)
        except asyncio.CancelledError:
            raise
        except KnowledgeDatabaseIdentityError:
            raise
        except Exception:
            raise KnowledgeStorageUnavailable("knowledge retrieval is unavailable") from None

    @staticmethod
    def _match(row: tuple[Any, ...]) -> KnowledgeMatch:
        rank = Decimal(str(row[18]))
        return KnowledgeMatch(
            chunk_id=str(row[0]),
            document_id=str(row[1]),
            citation_id=str(row[2]),
            namespace=cast(str, row[3]),
            source_type=KnowledgeSourceType(row[4]),
            customer_environment_id=cast(str | None, row[5]),
            required_modules_all=tuple(cast(list[str], row[6])),
            required_permissions_all=tuple(cast(list[str], row[7])),
            allowed_purposes=tuple(cast(list[str], row[8])),
            legal_entity_ids=tuple(cast(list[str], row[9])),
            data_classification=cast(Any, row[10]),
            language=cast(str, row[11]),
            title=cast(str, row[12]),
            section=cast(str, row[13]),
            document_version=cast(str, row[14]),
            effective_from=cast(Any, row[15]),
            effective_to=cast(Any, row[16]),
            content=cast(str, row[17]),
            relevance_score=float(rank),
        )
