"""Pure validation, fingerprinting, versioning, and preparation service."""

import hashlib
import json
from typing import Any

from erp_ai.capabilities import DataClassification
from erp_ai.knowledge import KnowledgeSourceType
from erp_ai.knowledge.ingestion.chunking import chunk_sections
from erp_ai.knowledge.ingestion.models import (
    ExistingDocumentManifest,
    IngestionLimits,
    KnowledgeDocumentDraft,
    PreparationDisposition,
    PreparedDocumentManifest,
    PreparedKnowledgeBundle,
    PreparedKnowledgeChunk,
)
from erp_ai.knowledge.ingestion.normalization import utf8_size


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _opaque_id(prefix: str, fingerprint: str, ordinal: int) -> str:
    digest = _sha256({"fingerprint": fingerprint, "ordinal": ordinal, "kind": prefix})[:32]
    return f"{prefix}_{digest}"


def _semver(value: str) -> tuple[int, int, int]:
    major, minor, patch = value.split(".")
    return int(major), int(minor), int(patch)


def _iso(value: Any) -> str | None:
    return None if value is None else value.isoformat()


def _validate_governance(draft: KnowledgeDocumentDraft) -> None:
    if draft.namespace != "hr":
        raise ValueError("only the HR knowledge namespace is currently approved")
    if draft.source_type is KnowledgeSourceType.PRODUCT_DOCUMENTATION:
        if draft.customer_environment_id is not None:
            raise ValueError("global product documentation cannot have customer scope")
    elif draft.customer_environment_id is None:
        raise ValueError("customer policy requires customer scope")
    if draft.data_classification is DataClassification.HIGHLY_RESTRICTED:
        raise ValueError("classification exceeds HR knowledge retrieval support")
    modules = set(draft.required_modules_all)
    if "leave" in modules and not {"hr_core", "leave"}.issubset(modules):
        raise ValueError("Leave knowledge requires hr_core and leave")


def _disposition(
    draft: KnowledgeDocumentDraft,
    fingerprint: str,
    existing: ExistingDocumentManifest | None,
) -> tuple[PreparationDisposition, str | None]:
    if existing is None:
        return PreparationDisposition.NEW_DOCUMENT, None
    if existing.document_id != draft.document_id:
        raise ValueError("existing manifest document mismatch")
    new_version = _semver(draft.document_version)
    old_version = _semver(existing.document_version)
    if new_version == old_version:
        if existing.document_fingerprint != fingerprint:
            raise ValueError("same document version has changed content or governance")
        return PreparationDisposition.IDEMPOTENT, None
    if new_version < old_version:
        raise ValueError("older document version is forbidden")
    return PreparationDisposition.SUPERSEDING_VERSION, existing.document_version


def prepare_knowledge_document(
    draft: KnowledgeDocumentDraft,
    *,
    existing: ExistingDocumentManifest | None = None,
    limits: IngestionLimits | None = None,
) -> PreparedKnowledgeBundle:
    """Prepare chunks without loading, writing, embedding, indexing, or external mutation."""

    if not isinstance(draft, KnowledgeDocumentDraft):
        raise TypeError("draft must be a validated KnowledgeDocumentDraft")
    policy = limits or IngestionLimits()
    _validate_governance(draft)
    if len(draft.sections) > policy.maximum_sections:
        raise ValueError("section limit exceeded")
    block_count = sum(len(section.text_blocks) for section in draft.sections)
    if block_count > policy.maximum_blocks:
        raise ValueError("block limit exceeded")
    if any(
        utf8_size(block) > policy.maximum_block_bytes
        for section in draft.sections
        for block in section.text_blocks
    ):
        raise ValueError("normalized block byte limit exceeded")

    content_payload = {
        "title": draft.title,
        "sections": [
            {
                "section_key": section.section_key,
                "heading": section.heading,
                "blocks": list(section.text_blocks),
            }
            for section in draft.sections
        ],
    }
    total_bytes = utf8_size(draft.title) + sum(
        utf8_size(section.heading) + sum(utf8_size(block) for block in section.text_blocks)
        for section in draft.sections
    )
    if total_bytes > policy.maximum_document_bytes:
        raise ValueError("document byte limit exceeded")
    governance_payload = {
        "document_id": str(draft.document_id),
        "document_version": draft.document_version,
        "namespace": draft.namespace,
        "source_type": draft.source_type.value,
        "customer_environment_id": draft.customer_environment_id,
        "language": draft.language,
        "required_modules_all": list(draft.required_modules_all),
        "required_permissions_all": list(draft.required_permissions_all),
        "allowed_purposes": list(draft.allowed_purposes),
        "legal_entity_ids": list(draft.legal_entity_ids),
        "data_classification": draft.data_classification.value,
        "effective_from": _iso(draft.effective_from),
        "effective_to": _iso(draft.effective_to),
        "approval_reference": draft.approval_reference,
        "approved_at": _iso(draft.approved_at),
        "source_provenance": (
            draft.source_provenance.model_dump(mode="json")
            if draft.source_provenance is not None
            else None
        ),
    }
    content_hash = _sha256(content_payload)
    governance_hash = _sha256(governance_payload)
    fingerprint = _sha256({"content": content_hash, "governance": governance_hash})
    disposition, supersedes = _disposition(draft, fingerprint, existing)

    raw_chunks = chunk_sections(draft.sections, policy)
    if len(raw_chunks) > policy.maximum_chunks:
        raise ValueError("chunk limit exceeded")
    chunks = tuple(
        PreparedKnowledgeChunk(
            chunk_id=_opaque_id("chk", fingerprint, ordinal),
            citation_id=_opaque_id("cite", fingerprint, ordinal),
            document_id=draft.document_id,
            document_version=draft.document_version,
            chunk_ordinal=ordinal,
            namespace=draft.namespace,
            section_key=raw.section_key,
            heading=raw.heading,
            source_type=draft.source_type,
            customer_environment_id=draft.customer_environment_id,
            required_modules_all=draft.required_modules_all,
            required_permissions_all=draft.required_permissions_all,
            allowed_purposes=draft.allowed_purposes,
            legal_entity_ids=draft.legal_entity_ids,
            data_classification=draft.data_classification,
            language=draft.language,
            title=draft.title,
            effective_from=draft.effective_from,
            effective_to=draft.effective_to,
            content=raw.content,
        )
        for ordinal, raw in enumerate(raw_chunks)
    )
    manifest = PreparedDocumentManifest(
        document_id=draft.document_id,
        document_version=draft.document_version,
        namespace=draft.namespace,
        source_type=draft.source_type,
        customer_environment_id=draft.customer_environment_id,
        source_provenance=draft.source_provenance,
        normalized_content_sha256=content_hash,
        governance_sha256=governance_hash,
        document_fingerprint=fingerprint,
        supersedes_version=supersedes,
    )
    return PreparedKnowledgeBundle(
        manifest=manifest,
        chunks=chunks,
        disposition=disposition,
        total_normalized_utf8_bytes=total_bytes,
        total_chunk_count=len(chunks),
    )
