"""Deterministic lexical/semantic fusion over one PostgreSQL snapshot."""

import asyncio
import hashlib
import json
from fractions import Fraction
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from erp_ai.capabilities import DataClassification
from erp_ai.infrastructure.postgres.errors import (
    KnowledgeDatabaseIdentityError,
    KnowledgeStorageUnavailable,
)
from erp_ai.infrastructure.postgres.knowledge_retrieval import _LEXICAL_QUERY
from erp_ai.infrastructure.postgres.routing import KnowledgeDatabaseAccess, KnowledgeDatabaseRouter
from erp_ai.infrastructure.postgres.semantic_retrieval import (
    _SEMANTIC_QUERY,
    PostgresSemanticKnowledgeRetrievalProvider,
    _vector_literal,
)
from erp_ai.knowledge import KnowledgeMatch, KnowledgeRetrievalRequest
from erp_ai.knowledge.embeddings import (
    EmbeddingBatchRequest,
    EmbeddingInput,
    EmbeddingInputKind,
    EmbeddingProfile,
    EmbeddingProvider,
)


class HybridRetrievalPolicy(BaseModel):
    """Immutable server-owned hybrid retrieval and provenance policy."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    policy_version: str = Field(pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
    namespace: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    lexical_candidate_limit: int = Field(default=20, strict=True, ge=1, le=100)
    semantic_candidate_limit: int = Field(default=20, strict=True, ge=1, le=100)
    final_result_limit: int = Field(default=5, strict=True, ge=1, le=5)
    lexical_weight: int = Field(default=1, strict=True, ge=1, le=100)
    semantic_weight: int = Field(default=1, strict=True, ge=1, le=100)
    rrf_rank_constant: int = Field(default=60, strict=True, ge=1, le=1000)
    embedding_profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", repr=False)
    semantic_threshold: float = Field(strict=True, ge=0, le=1, repr=False)
    threshold_approval_status: Literal["unapproved_test_only"]
    generation_digest: str = Field(pattern=r"^[0-9a-f]{64}$", repr=False)
    embedding_resource_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", repr=False)
    embedding_runtime_identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", repr=False)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def policy_sha256(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.model_dump(exclude={"policy_sha256"}), sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()


def _same_chunk(left: KnowledgeMatch, right: KnowledgeMatch) -> bool:
    return left.model_dump(exclude={"relevance_score"}) == right.model_dump(
        exclude={"relevance_score"}
    )


def reciprocal_rank_fusion(
    lexical: tuple[KnowledgeMatch, ...],
    semantic: tuple[KnowledgeMatch, ...],
    policy: HybridRetrievalPolicy,
    requested_limit: int,
) -> tuple[KnowledgeMatch, ...]:
    """Fuse already ranked unique candidate lists using exact rational arithmetic."""
    if (
        len(lexical) > policy.lexical_candidate_limit
        or len(semantic) > policy.semantic_candidate_limit
    ):
        raise ValueError("candidate limit exceeded")
    if len({item.chunk_id for item in lexical}) != len(lexical) or len(
        {item.chunk_id for item in semantic}
    ) != len(semantic):
        raise ValueError("duplicate hybrid candidate")
    by_id: dict[str, KnowledgeMatch] = {}
    scores: dict[str, Fraction] = {}
    for items, weight in ((lexical, policy.lexical_weight), (semantic, policy.semantic_weight)):
        for rank, item in enumerate(items, start=1):
            previous = by_id.get(item.chunk_id)
            if previous is not None and not _same_chunk(previous, item):
                raise ValueError("hybrid candidate metadata mismatch")
            by_id[item.chunk_id] = item
            scores[item.chunk_id] = scores.get(item.chunk_id, Fraction()) + Fraction(
                weight, policy.rrf_rank_constant + rank
            )
    limit = min(requested_limit, policy.final_result_limit)
    ordered = sorted(by_id, key=lambda chunk_id: (-scores[chunk_id], chunk_id))[:limit]
    return tuple(by_id[chunk_id] for chunk_id in ordered)


class PostgresHybridKnowledgeRetrievalProvider:  # pragma: no cover - integration boundary
    __slots__ = ("_customer", "_policy", "_profile", "_provider", "_router")

    def __init__(
        self,
        router: KnowledgeDatabaseRouter,
        customer_environment_id: str,
        profile: EmbeddingProfile,
        provider: EmbeddingProvider,
        policy: HybridRetrievalPolicy,
    ) -> None:
        if policy.namespace != "hr" or policy.embedding_profile_sha256 != profile.profile_sha256:
            raise ValueError("hybrid retrieval policy is incompatible")
        self._router, self._customer = router, customer_environment_id
        self._profile, self._provider, self._policy = profile, provider, policy

    async def retrieve(self, request: KnowledgeRetrievalRequest) -> tuple[KnowledgeMatch, ...]:
        if request.customer_environment_id != self._customer:
            raise KnowledgeDatabaseIdentityError("knowledge database identity mismatch")
        try:
            query_input = EmbeddingInput(
                input_id="hybrid_query",
                text=request.query,
                content_sha256=hashlib.sha256(request.query.encode()).hexdigest(),
                data_classification=DataClassification.INTERNAL,
                input_kind=EmbeddingInputKind.QUERY,
            )
            embedded = await self._provider.embed(
                EmbeddingBatchRequest(profile=self._profile, inputs=(query_input,))
            )
            if (
                embedded.profile_sha256 != self._profile.profile_sha256
                or len(embedded.vectors) != 1
            ):
                raise KnowledgeStorageUnavailable("hybrid knowledge retrieval is unavailable")
            vector = embedded.vectors[0]
            if (
                vector.input_id != query_input.input_id
                or len(vector.values) != self._profile.dimensions
            ):
                raise KnowledgeStorageUnavailable("hybrid knowledge retrieval is unavailable")
            pool = self._router.pool(self._customer, KnowledgeDatabaseAccess.READER)
            async with pool.connection() as connection, connection.transaction():
                await connection.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
                await connection.execute(
                    "SELECT set_config('erp_ai.customer_environment_id', %s, true)",
                    (self._customer,),
                )
                identity = await (
                    await connection.execute(
                        """SELECT customer_environment_id
                        FROM erp_ai_knowledge.database_identity WHERE singleton=true"""
                    )
                ).fetchone()
                if identity != (self._customer,):
                    raise KnowledgeDatabaseIdentityError("knowledge database identity mismatch")
                active = await (
                    await connection.execute(
                        """SELECT generation_id,generation_digest
                        FROM erp_ai_knowledge.active_generations
                        WHERE customer_environment_id=%s AND namespace=%s""",
                        (self._customer, request.namespace),
                    )
                ).fetchone()
                if active is None:
                    return ()
                generation_id, generation_digest = active
                if generation_digest != self._policy.generation_digest:
                    raise KnowledgeStorageUnavailable("hybrid knowledge retrieval is unavailable")
                ready = await (
                    await connection.execute(
                        """SELECT s.embedding_set_sha256
                        FROM erp_ai_knowledge.embedding_sets s
                        JOIN erp_ai_knowledge.generations g USING
                          (customer_environment_id,namespace,generation_id)
                        WHERE s.customer_environment_id=%s AND s.namespace=%s
                          AND s.generation_id=%s AND s.generation_digest=%s
                          AND s.profile_sha256=%s AND s.status='ready'
                          AND s.embedding_count=g.chunk_count
                          AND s.embedding_count=(SELECT count(*)
                            FROM erp_ai_knowledge.chunk_embeddings e
                            WHERE e.customer_environment_id=s.customer_environment_id
                              AND e.namespace=s.namespace
                              AND e.generation_id=s.generation_id
                              AND e.profile_sha256=s.profile_sha256)""",
                        (
                            self._customer,
                            request.namespace,
                            generation_id,
                            generation_digest,
                            self._profile.profile_sha256,
                        ),
                    )
                ).fetchone()
                if ready is None:
                    raise KnowledgeStorageUnavailable("hybrid knowledge retrieval is unavailable")
                common = (
                    self._customer,
                    generation_id,
                    request.namespace,
                    self._customer,
                    list(request.enabled_modules),
                    list(request.permission_codes),
                    request.purpose,
                    list(request.authorized_legal_entity_ids),
                    request.effective_at,
                    request.effective_at,
                )
                lexical_rows = await (
                    await connection.execute(
                        _LEXICAL_QUERY,
                        (request.query, *common, self._policy.lexical_candidate_limit),
                    )
                ).fetchall()
                semantic_rows = await (
                    await connection.execute(
                        _SEMANTIC_QUERY,
                        (
                            self._customer,
                            request.namespace,
                            generation_id,
                            self._profile.profile_sha256,
                            _vector_literal(vector.values),
                            self._profile.profile_sha256,
                            *common,
                            [item.value for item in self._profile.allowed_data_classifications],
                            self._policy.semantic_threshold,
                            self._policy.semantic_candidate_limit,
                        ),
                    )
                ).fetchall()
                lexical = tuple(
                    PostgresSemanticKnowledgeRetrievalProvider._match(row) for row in lexical_rows
                )
                semantic = tuple(
                    PostgresSemanticKnowledgeRetrievalProvider._match(row) for row in semantic_rows
                )
                result = reciprocal_rank_fusion(
                    lexical, semantic, self._policy, request.maximum_results
                )
                if any(not self._authorized(request, item) for item in result):
                    raise KnowledgeStorageUnavailable("hybrid knowledge retrieval is unavailable")
                return result
        except asyncio.CancelledError:
            raise
        except KnowledgeDatabaseIdentityError:
            raise
        except KnowledgeStorageUnavailable:
            raise
        except Exception:
            raise KnowledgeStorageUnavailable("hybrid knowledge retrieval is unavailable") from None

    @staticmethod
    def _authorized(request: KnowledgeRetrievalRequest, item: KnowledgeMatch) -> bool:
        ranks = {
            DataClassification.PUBLIC: 0,
            DataClassification.INTERNAL: 1,
            DataClassification.RESTRICTED: 2,
            DataClassification.HIGHLY_RESTRICTED: 3,
        }
        return (
            item.namespace == request.namespace
            and set(item.required_modules_all).issubset(request.enabled_modules)
            and set(item.required_permissions_all).issubset(request.permission_codes)
            and request.purpose in item.allowed_purposes
            and set(item.legal_entity_ids).issubset(request.authorized_legal_entity_ids)
            and item.customer_environment_id in (None, request.customer_environment_id)
            and item.effective_from <= request.effective_at
            and (item.effective_to is None or request.effective_at < item.effective_to)
            and ranks[item.data_classification] <= ranks[DataClassification.RESTRICTED]
        )
