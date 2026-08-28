"""Exact pgvector cosine retrieval over one authorized active generation."""

import asyncio
import hashlib
import json
import math
from decimal import Decimal
from typing import Any, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, computed_field

from erp_ai.capabilities import DataClassification
from erp_ai.infrastructure.postgres.errors import (
    KnowledgeDatabaseIdentityError,
    KnowledgeStorageUnavailable,
)
from erp_ai.infrastructure.postgres.routing import KnowledgeDatabaseAccess, KnowledgeDatabaseRouter
from erp_ai.knowledge import KnowledgeMatch, KnowledgeRetrievalRequest, KnowledgeSourceType
from erp_ai.knowledge.embeddings import (
    EmbeddingBatchRequest,
    EmbeddingInput,
    EmbeddingInputKind,
    EmbeddingProfile,
    EmbeddingProvider,
)

SEMANTIC_NAMESPACE = "hr"
SEMANTIC_MAXIMUM_RESULTS = 5
SEMANTIC_MAXIMUM_TOTAL_CONTENT_CHARACTERS = 12_000
SEMANTIC_QUERY_PARAMETER_ORDER = (
    "customer_environment_id",
    "namespace",
    "active_generation_id",
    "embedding_profile_sha256",
    "query_vector",
    "embedding_profile_sha256",
    "customer_environment_id",
    "active_generation_id",
    "namespace",
    "customer_environment_id",
    "enabled_modules",
    "permission_codes",
    "purpose",
    "authorized_legal_entity_ids",
    "effective_at",
    "effective_at",
    "allowed_data_classifications",
    "minimum_relevance_score",
    "maximum_results",
)


class SemanticTransactionVerifier(Protocol):
    async def verify(
        self, connection: Any, request: KnowledgeRetrievalRequest, profile: EmbeddingProfile
    ) -> None: ...


class SemanticRetrievalPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    namespace: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    embedding_profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", repr=False)
    minimum_relevance_score: float = Field(strict=True, ge=0, le=1, repr=False)
    policy_version: str = Field(pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def policy_sha256(self) -> str:
        return hashlib.sha256(
            json.dumps(
                {
                    "embedding_profile_sha256": self.embedding_profile_sha256,
                    "minimum_relevance_score": self.minimum_relevance_score,
                    "namespace": self.namespace,
                    "policy_version": self.policy_version,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()


_SEMANTIC_QUERY = """
WITH ready_set AS (
    SELECT s.customer_environment_id,s.namespace,s.generation_id,s.profile_sha256
    FROM erp_ai_knowledge.embedding_sets s
    JOIN erp_ai_knowledge.generations g USING
      (customer_environment_id,namespace,generation_id)
    WHERE s.customer_environment_id=%s AND s.namespace=%s AND s.generation_id=%s
      AND s.profile_sha256=%s AND s.status='ready'
      AND g.status='active' AND s.generation_digest=g.generation_digest
      AND s.embedding_count=g.chunk_count
      AND s.embedding_count=(
          SELECT count(*) FROM erp_ai_knowledge.chunk_embeddings complete
          WHERE complete.customer_environment_id=s.customer_environment_id
            AND complete.namespace=s.namespace AND complete.generation_id=s.generation_id
            AND complete.profile_sha256=s.profile_sha256)
), eligible AS (
    SELECT c.*, e.embedding OPERATOR(public.<=>) %s::public.vector AS cosine_distance
    FROM erp_ai_knowledge.chunks c
    JOIN ready_set s
     ON s.customer_environment_id=c.customer_environment_id
     AND s.namespace=c.namespace AND s.generation_id=c.generation_id
     AND s.profile_sha256=%s
    JOIN erp_ai_knowledge.chunk_embeddings e
      ON e.customer_environment_id=c.customer_environment_id
     AND e.namespace=c.namespace AND e.generation_id=c.generation_id
     AND e.profile_sha256=s.profile_sha256 AND e.chunk_id=c.chunk_id
    WHERE c.customer_environment_id=%s AND c.generation_id=%s AND c.namespace=%s
      AND (c.source_type='product_documentation'
           OR (c.source_type='customer_policy' AND c.document_customer_environment_id=%s))
      AND c.required_modules_all <@ %s::text[]
      AND c.required_permissions_all <@ %s::text[]
      AND %s = ANY(c.allowed_purposes)
      AND c.legal_entity_ids <@ %s::text[]
      AND c.effective_from <= %s
      AND (c.effective_to IS NULL OR c.effective_to > %s)
      AND c.data_classification = ANY(%s::text[])
      AND CASE c.data_classification
          WHEN 'public' THEN 0 WHEN 'internal' THEN 1 WHEN 'restricted' THEN 2 ELSE 3 END <= 2
), scored AS (
    SELECT eligible.*,
           greatest(0::double precision,least(1::double precision,1-cosine_distance/2))
             AS relevance_score
    FROM eligible
)
SELECT chunk_id,document_id,citation_id,namespace,source_type,
       document_customer_environment_id,required_modules_all,required_permissions_all,
       allowed_purposes,legal_entity_ids,data_classification,language,title,section,
       document_version,effective_from,effective_to,content,
       relevance_score,cosine_distance
FROM scored
WHERE cosine_distance >= 0 AND cosine_distance <= 2
  AND cosine_distance NOT IN ('NaN'::double precision,
                              'Infinity'::double precision,
                              '-Infinity'::double precision)
  AND relevance_score >= %s
ORDER BY cosine_distance ASC,chunk_id ASC
LIMIT %s
"""


def _vector_literal(values: tuple[float, ...]) -> str:
    return "[" + ",".join(format(value, ".9g") for value in values) + "]"


def _distance_to_score(distance: object) -> float:
    if isinstance(distance, bool) or not isinstance(distance, (int, float, Decimal)):
        raise KnowledgeStorageUnavailable("semantic knowledge retrieval is unavailable")
    converted = float(distance)
    if not math.isfinite(converted) or not 0 <= converted <= 2:
        raise KnowledgeStorageUnavailable("semantic knowledge retrieval is unavailable")
    return 1 - converted / 2


class PostgresSemanticKnowledgeRetrievalProvider:  # pragma: no cover - integration boundary
    __slots__ = (
        "_customer",
        "_policy",
        "_profile",
        "_provider",
        "_router",
        "_timeouts",
        "_transaction_verifier",
    )

    def __init__(
        self,
        router: KnowledgeDatabaseRouter,
        customer_environment_id: str,
        profile: EmbeddingProfile,
        provider: EmbeddingProvider,
        policy: SemanticRetrievalPolicy,
        transaction_timeouts: tuple[int, int, int] | None = None,
        transaction_verifier: SemanticTransactionVerifier | None = None,
    ) -> None:
        if (
            policy.namespace != SEMANTIC_NAMESPACE
            or policy.embedding_profile_sha256 != profile.profile_sha256
        ):
            raise ValueError("semantic retrieval policy is incompatible")
        self._router = router
        self._customer = customer_environment_id
        self._profile = profile
        self._provider = provider
        self._policy = policy
        self._timeouts = transaction_timeouts
        self._transaction_verifier = transaction_verifier

    async def retrieve(self, request: KnowledgeRetrievalRequest) -> tuple[KnowledgeMatch, ...]:
        try:
            request = KnowledgeRetrievalRequest.model_validate(
                request.model_dump(mode="python"), strict=True
            )
        except Exception:
            raise KnowledgeStorageUnavailable(
                "semantic knowledge retrieval is unavailable"
            ) from None
        if request.customer_environment_id != self._customer:
            raise KnowledgeDatabaseIdentityError("knowledge database identity mismatch")
        try:
            query_input = EmbeddingInput(
                input_id="semantic_query",
                text=request.query,
                content_sha256=hashlib.sha256(request.query.encode()).hexdigest(),
                data_classification=DataClassification.INTERNAL,
                input_kind=EmbeddingInputKind.QUERY,
            )
            result = await self._provider.embed(
                EmbeddingBatchRequest(profile=self._profile, inputs=(query_input,))
            )
            result = type(result).model_validate(
                result.model_dump(mode="python", exclude_computed_fields=True), strict=True
            )
            if result.profile_sha256 != self._profile.profile_sha256 or len(result.vectors) != 1:
                raise KnowledgeStorageUnavailable("semantic query embedding is unavailable")
            vector = result.vectors[0]
            if (
                vector.input_id != query_input.input_id
                or len(vector.values) != self._profile.dimensions
            ):
                raise KnowledgeStorageUnavailable("semantic query embedding is unavailable")
            pool = self._router.pool(self._customer, KnowledgeDatabaseAccess.READER)
            async with pool.connection() as connection, connection.transaction():
                await connection.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
                await connection.execute("SELECT set_config('search_path', 'pg_catalog', true)")
                if self._timeouts is not None:
                    for setting, value in zip(
                        (
                            "statement_timeout",
                            "lock_timeout",
                            "idle_in_transaction_session_timeout",
                        ),
                        self._timeouts,
                        strict=True,
                    ):
                        await connection.execute(
                            "SELECT set_config(%s, %s, true)", (setting, str(value))
                        )
                await connection.execute(
                    "SELECT set_config('erp_ai.customer_environment_id', %s, true)",
                    (self._customer,),
                )
                if self._transaction_verifier is not None:
                    await self._transaction_verifier.verify(connection, request, self._profile)
                identity = await (
                    await connection.execute(
                        """SELECT customer_environment_id FROM erp_ai_knowledge.database_identity
                        WHERE singleton=true"""
                    )
                ).fetchone()
                if identity != (self._customer,):
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
                rows = await (
                    await connection.execute(
                        _SEMANTIC_QUERY,
                        (
                            self._customer,
                            request.namespace,
                            active[0],
                            self._profile.profile_sha256,
                            _vector_literal(vector.values),
                            self._profile.profile_sha256,
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
                            [item.value for item in self._profile.allowed_data_classifications],
                            self._policy.minimum_relevance_score,
                            request.maximum_results,
                        ),
                    )
                ).fetchall()
                return self._validated_matches(rows)
        except asyncio.CancelledError:
            raise
        except KnowledgeDatabaseIdentityError:
            raise
        except KnowledgeStorageUnavailable:
            raise
        except Exception:
            raise KnowledgeStorageUnavailable(
                "semantic knowledge retrieval is unavailable"
            ) from None

    @staticmethod
    def _match(row: tuple[Any, ...]) -> KnowledgeMatch:
        score = _distance_to_score(row[19])
        stored_score = float(Decimal(str(row[18])))
        if not math.isfinite(stored_score) or not math.isclose(
            stored_score, score, rel_tol=0, abs_tol=1e-12
        ):
            raise KnowledgeStorageUnavailable("semantic knowledge retrieval is unavailable")
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
            relevance_score=score,
        )

    @classmethod
    def _validated_matches(cls, rows: list[tuple[Any, ...]]) -> tuple[KnowledgeMatch, ...]:
        matches = tuple(cls._match(row) for row in rows)
        if len(matches) > SEMANTIC_MAXIMUM_RESULTS:
            raise KnowledgeStorageUnavailable("semantic knowledge retrieval is unavailable")
        if len({item.chunk_id for item in matches}) != len(matches):
            raise KnowledgeStorageUnavailable("semantic knowledge retrieval is unavailable")
        if len({item.citation_id for item in matches}) != len(matches):
            raise KnowledgeStorageUnavailable("semantic knowledge retrieval is unavailable")
        ordered = tuple(sorted(matches, key=lambda item: (-item.relevance_score, item.chunk_id)))
        if matches != ordered:
            raise KnowledgeStorageUnavailable("semantic knowledge retrieval is unavailable")
        if sum(len(item.content) for item in matches) > SEMANTIC_MAXIMUM_TOTAL_CONTENT_CHARACTERS:
            raise KnowledgeStorageUnavailable("semantic knowledge retrieval is unavailable")
        return matches
