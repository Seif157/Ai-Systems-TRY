"""Defensive validation and deterministic full-generation publication planning."""

import hashlib
import json
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import ValidationError

from erp_ai.capabilities import DataClassification
from erp_ai.knowledge import KnowledgeSourceType
from erp_ai.knowledge.indexing.models import (
    GenerationStatus,
    IndexPublicationLimits,
    KnowledgeGenerationManifest,
    KnowledgeIndexScope,
    KnowledgeIndexSnapshot,
    KnowledgePublicationAuditOutboxEvent,
    KnowledgePublicationContext,
    KnowledgePublicationPlan,
    KnowledgePublicationResult,
    KnowledgeRollbackRequest,
    KnowledgeRollbackResult,
)
from erp_ai.knowledge.indexing.repository import KnowledgeIndexRepository
from erp_ai.knowledge.ingestion.models import PreparedKnowledgeBundle

PUBLICATION_CONTRACT_VERSION: Literal[1] = 1


class KnowledgePublicationError(ValueError):
    """Safe publication validation failure without document details."""


class KnowledgePublicationConflict(KnowledgePublicationError):
    """Safe optimistic-concurrency or idempotency conflict."""


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _opaque_chunk_id(prefix: str, fingerprint: str, ordinal: int) -> str:
    digest = _digest({"fingerprint": fingerprint, "ordinal": ordinal, "kind": prefix})[:32]
    return f"{prefix}_{digest}"


def _revalidate(bundle: PreparedKnowledgeBundle) -> PreparedKnowledgeBundle:
    try:
        return PreparedKnowledgeBundle.model_validate(bundle.model_dump(round_trip=True))
    except (AttributeError, ValidationError, TypeError, ValueError) as error:
        raise KnowledgePublicationError("prepared bundle is invalid") from error


def _validate_chunk_metadata(bundle: PreparedKnowledgeBundle) -> None:
    manifest = bundle.manifest
    expected_ordinals = tuple(range(len(bundle.chunks)))
    if tuple(chunk.chunk_ordinal for chunk in bundle.chunks) != expected_ordinals:
        raise KnowledgePublicationError("prepared bundle ordering is invalid")
    if bundle.total_chunk_count != len(bundle.chunks) or not bundle.chunks:
        raise KnowledgePublicationError("prepared bundle chunk totals are invalid")
    expected_fingerprint = _digest(
        {"content": manifest.normalized_content_sha256, "governance": manifest.governance_sha256}
    )
    if manifest.document_fingerprint != expected_fingerprint:
        raise KnowledgePublicationError("prepared document fingerprint is invalid")
    first = bundle.chunks[0]
    invariant = (
        first.required_modules_all,
        first.required_permissions_all,
        first.allowed_purposes,
        first.legal_entity_ids,
        first.data_classification,
        first.language,
        first.title,
        first.effective_from,
        first.effective_to,
    )
    for chunk in bundle.chunks:
        if (
            chunk.document_id != manifest.document_id
            or chunk.document_version != manifest.document_version
            or chunk.namespace != manifest.namespace
            or chunk.source_type is not manifest.source_type
            or chunk.customer_environment_id != manifest.customer_environment_id
        ):
            raise KnowledgePublicationError("prepared chunk metadata is inconsistent")
        if (
            chunk.required_modules_all,
            chunk.required_permissions_all,
            chunk.allowed_purposes,
            chunk.legal_entity_ids,
            chunk.data_classification,
            chunk.language,
            chunk.title,
            chunk.effective_from,
            chunk.effective_to,
        ) != invariant:
            raise KnowledgePublicationError("prepared chunk governance is inconsistent")
        if chunk.chunk_id != _opaque_chunk_id(
            "chk", manifest.document_fingerprint, chunk.chunk_ordinal
        ):
            raise KnowledgePublicationError("prepared chunk fingerprint is invalid")
        if chunk.citation_id != _opaque_chunk_id(
            "cite", manifest.document_fingerprint, chunk.chunk_ordinal
        ):
            raise KnowledgePublicationError("prepared citation fingerprint is invalid")


def _source_provenance_fingerprint(bundle: PreparedKnowledgeBundle) -> str:
    provenance = bundle.manifest.source_provenance
    return _digest(None if provenance is None else provenance.model_dump(mode="json"))


def _generation_digest(
    scope: KnowledgeIndexScope, bundles: tuple[PreparedKnowledgeBundle, ...]
) -> str:
    hasher = hashlib.sha256()
    hasher.update(
        _canonical({"contract": PUBLICATION_CONTRACT_VERSION, "scope": scope.model_dump()})
    )
    total_chunks = 0
    total_bytes = 0
    for bundle in bundles:
        manifest = bundle.manifest
        hasher.update(
            _canonical(
                {
                    "document_id": str(manifest.document_id),
                    "version": manifest.document_version,
                    "document_fingerprint": manifest.document_fingerprint,
                    "governance_fingerprint": manifest.governance_sha256,
                    "source_provenance_fingerprint": _source_provenance_fingerprint(bundle),
                }
            )
        )
        for chunk in bundle.chunks:
            hasher.update(
                _canonical(
                    {
                        "chunk_id": chunk.chunk_id,
                        "content_sha256": hashlib.sha256(chunk.content.encode()).hexdigest(),
                    }
                )
            )
            total_chunks += 1
        total_bytes += bundle.total_normalized_utf8_bytes
    hasher.update(
        _canonical(
            {
                "document_count": len(bundles),
                "chunk_count": total_chunks,
                "total_normalized_bytes": total_bytes,
            }
        )
    )
    return hasher.hexdigest()


class KnowledgeIndexPublisher:
    __slots__ = ("_clock", "_id_factory", "_repository")

    def __init__(
        self,
        repository: KnowledgeIndexRepository,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory

    def _validated_context(
        self, context: KnowledgePublicationContext
    ) -> KnowledgePublicationContext:
        try:
            return KnowledgePublicationContext.model_validate(context.model_dump(round_trip=True))
        except (AttributeError, ValidationError, TypeError, ValueError) as error:
            raise KnowledgePublicationError("trusted publication context is invalid") from error

    def build_plan(
        self,
        context: KnowledgePublicationContext,
        bundles: Iterable[PreparedKnowledgeBundle],
        *,
        limits: IndexPublicationLimits | None = None,
    ) -> KnowledgePublicationPlan:
        trusted = self._validated_context(context)
        scope = KnowledgeIndexScope(
            namespace=trusted.namespace,
            customer_environment_id=trusted.customer_environment_id,
        )
        policy = limits or IndexPublicationLimits()
        supplied_list: list[PreparedKnowledgeBundle] = []
        for bundle in bundles:
            if len(supplied_list) >= policy.maximum_bundles_per_call:
                raise KnowledgePublicationError("publication bundle count is invalid")
            supplied_list.append(bundle)
        supplied = tuple(supplied_list)
        if not supplied:
            raise KnowledgePublicationError("publication bundle count is invalid")
        validated: list[PreparedKnowledgeBundle] = []
        document_versions: dict[UUID, str] = {}
        chunk_ids: set[str] = set()
        citation_ids: set[str] = set()
        total_chunks = 0
        total_bytes = 0
        now = self._clock()
        for original in supplied:
            bundle = _revalidate(original)
            manifest = bundle.manifest
            previous_version = document_versions.get(manifest.document_id)
            if previous_version is not None:
                if previous_version != manifest.document_version:
                    raise KnowledgePublicationError("conflicting document versions are forbidden")
                raise KnowledgePublicationError("duplicate document IDs are forbidden")
            for chunk in bundle.chunks:
                if chunk.chunk_id in chunk_ids:
                    raise KnowledgePublicationError("duplicate prepared chunk IDs are forbidden")
                if chunk.citation_id in citation_ids:
                    raise KnowledgePublicationError("duplicate prepared citation IDs are forbidden")
            _validate_chunk_metadata(bundle)
            if manifest.namespace != scope.namespace:
                raise KnowledgePublicationError("document namespace is outside publication scope")
            if manifest.source_type is KnowledgeSourceType.PRODUCT_DOCUMENTATION:
                if manifest.customer_environment_id is not None:
                    raise KnowledgePublicationError("global document has customer scope")
            elif manifest.customer_environment_id != scope.customer_environment_id:
                raise KnowledgePublicationError("customer policy is outside publication scope")
            modules = set(bundle.chunks[0].required_modules_all)
            if not modules.issubset(trusted.installed_modules):
                raise KnowledgePublicationError("document requires an unavailable module")
            if any(
                chunk.effective_to is not None and chunk.effective_to <= now
                for chunk in bundle.chunks
            ):
                raise KnowledgePublicationError("expired documents cannot be published")
            if any(
                chunk.data_classification is DataClassification.HIGHLY_RESTRICTED
                for chunk in bundle.chunks
            ):
                raise KnowledgePublicationError("document classification is unsupported")
            document_versions[manifest.document_id] = manifest.document_version
            for chunk in bundle.chunks:
                chunk_ids.add(chunk.chunk_id)
                citation_ids.add(chunk.citation_id)
            total_chunks += len(bundle.chunks)
            total_bytes += bundle.total_normalized_utf8_bytes
            if (
                len(validated) + 1 > policy.maximum_documents
                or total_chunks > policy.maximum_chunks
                or total_bytes > policy.maximum_normalized_bytes
            ):
                raise KnowledgePublicationError("publication limits exceeded")
            validated.append(bundle)
        ordered = tuple(
            sorted(
                validated,
                key=lambda item: (str(item.manifest.document_id), item.manifest.document_version),
            )
        )
        generation_digest = _generation_digest(scope, ordered)
        generation_id = self._id_factory()
        operation_digest = _digest({"scope": scope.model_dump(), "generation": generation_digest})
        generation_manifest = KnowledgeGenerationManifest(
            generation_id=generation_id,
            scope=scope,
            generation_digest=generation_digest,
            publication_contract_version=PUBLICATION_CONTRACT_VERSION,
            document_count=len(ordered),
            chunk_count=total_chunks,
            total_normalized_bytes=total_bytes,
            status=GenerationStatus.CANDIDATE,
        )
        event = KnowledgePublicationAuditOutboxEvent(
            outbox_id=self._id_factory(),
            operation_id=trusted.operation_id,
            request_id=trusted.request_id,
            customer_environment_id=trusted.customer_environment_id,
            actor_id=trusted.actor_id,
            namespace=trusted.namespace,
            action="knowledge.publish",
            previous_generation_id=None,
            activated_generation_id=generation_id,
            generation_digest=generation_digest,
            outcome="succeeded",
        )
        return KnowledgePublicationPlan(
            context=trusted,
            manifest=generation_manifest,
            bundles=ordered,
            operation_digest=operation_digest,
            outbox_event=event,
        )

    async def publish(
        self,
        context: KnowledgePublicationContext,
        bundles: Iterable[PreparedKnowledgeBundle],
        *,
        expected_active_generation_id: UUID | None,
        limits: IndexPublicationLimits | None = None,
    ) -> KnowledgePublicationResult:
        plan = self.build_plan(context, bundles, limits=limits)
        existing = await self._repository.get_operation_result(plan.context.operation_id)
        if existing is not None:
            if (
                not isinstance(existing, KnowledgePublicationResult)
                or existing.operation_digest != plan.operation_digest
            ):
                raise KnowledgePublicationConflict(
                    "operation ID conflicts with completed operation"
                )
            return existing
        return await self._repository.commit_generation(plan, expected_active_generation_id)

    async def get_active_snapshot(
        self, scope: KnowledgeIndexScope
    ) -> KnowledgeIndexSnapshot | None:
        return await self._repository.get_active_snapshot(scope)

    async def rollback(
        self,
        context: KnowledgePublicationContext,
        *,
        target_generation_id: UUID,
        expected_active_generation_id: UUID,
    ) -> KnowledgeRollbackResult:
        trusted = self._validated_context(context)
        scope = KnowledgeIndexScope(
            namespace=trusted.namespace,
            customer_environment_id=trusted.customer_environment_id,
        )
        operation_digest = _digest(
            {"scope": scope.model_dump(), "rollback_target": str(target_generation_id)}
        )
        existing = await self._repository.get_operation_result(trusted.operation_id)
        if existing is not None:
            if (
                not isinstance(existing, KnowledgeRollbackResult)
                or existing.operation_digest != operation_digest
            ):
                raise KnowledgePublicationConflict(
                    "operation ID conflicts with completed operation"
                )
            return existing
        request = KnowledgeRollbackRequest(
            context=trusted,
            scope=scope,
            target_generation_id=target_generation_id,
            operation_digest=operation_digest,
            outbox_id=self._id_factory(),
        )
        return await self._repository.commit_rollback(request, expected_active_generation_id)
