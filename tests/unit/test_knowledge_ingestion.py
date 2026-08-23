from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from erp_ai.knowledge.ingestion import (
    ExistingDocumentManifest,
    IngestionLimits,
    KnowledgeDocumentDraft,
    KnowledgeSection,
    PreparationDisposition,
    prepare_knowledge_document,
)
from erp_ai.knowledge.ingestion.chunking import _overlap_suffix, chunk_sections

NOW = datetime(2026, 8, 23, 10, 0, tzinfo=ZoneInfo("Africa/Cairo"))


@pytest.mark.parametrize("version", ("1", "1.0", "01.0.0", "1.0.0-alpha", "1.0.0+build", " 1.0.0 "))
def test_draft_rejects_noncanonical_document_versions(version: str) -> None:
    with pytest.raises(ValidationError):
        draft(document_version=version)


DOCUMENT_ID = UUID("11111111-1111-4111-8111-111111111111")


def draft(**overrides: object) -> KnowledgeDocumentDraft:
    values: dict[str, object] = {
        "document_id": DOCUMENT_ID,
        "document_version": "1.0.0",
        "namespace": "hr",
        "source_type": "product_documentation",
        "customer_environment_id": None,
        "title": " Employee Handbook ",
        "language": "en",
        "required_modules_all": ("hr_core",),
        "required_permissions_all": ("hr.knowledge.read",),
        "allowed_purposes": ("employee_self_service",),
        "legal_entity_ids": (),
        "data_classification": "restricted",
        "effective_from": NOW,
        "effective_to": NOW + timedelta(days=365),
        "approval_reference": "approval_1",
        "approved_at": NOW,
        "sections": (
            KnowledgeSection(
                section_key="leave_policy",
                heading=" Leave Policy ",
                text_blocks=("First paragraph.", "Second paragraph."),
            ),
        ),
    }
    values.update(overrides)
    return KnowledgeDocumentDraft.model_validate(values)


def manifest(document: KnowledgeDocumentDraft, fingerprint: str) -> ExistingDocumentManifest:
    return ExistingDocumentManifest(
        document_id=document.document_id,
        document_version=document.document_version,
        document_fingerprint=fingerprint,
    )


def test_global_product_and_customer_policy_prepare_deterministically() -> None:
    product = draft()
    first = prepare_knowledge_document(product)
    second = prepare_knowledge_document(product)
    assert first == second
    assert first.disposition is PreparationDisposition.NEW_DOCUMENT
    assert first.total_chunk_count == len(first.chunks)
    assert tuple(chunk.chunk_ordinal for chunk in first.chunks) == tuple(range(len(first.chunks)))

    policy = draft(
        source_type="customer_policy",
        customer_environment_id="customer_a",
        approval_reference="policy_approval_1",
    )
    prepared = prepare_knowledge_document(policy)
    assert prepared.chunks[0].customer_environment_id == "customer_a"


def test_arabic_english_nfc_and_newlines_are_normalized_without_lowercasing() -> None:
    section = KnowledgeSection(
        section_key="arabic",
        heading="  سياسة الموارد البشرية  ",
        text_blocks=(" Cafe\u0301\r\n\rالنص العربي ",),  # noqa: RUF001
    )
    assert section.heading == "سياسة الموارد البشرية"
    assert section.text_blocks == ("Café\n\nالنص العربي",)  # noqa: RUF001
    prepared = prepare_knowledge_document(draft(sections=(section,), language="ar-EG"))
    assert "Café" in prepared.chunks[0].content
    assert "النص العربي" in prepared.chunks[0].content


def test_content_and_governance_changes_change_expected_fingerprints() -> None:
    original = prepare_knowledge_document(draft())
    content_changed = prepare_knowledge_document(
        draft(
            sections=(
                KnowledgeSection(
                    section_key="leave_policy", heading="Leave", text_blocks=("Changed",)
                ),
            )
        )
    )
    governance_changed = prepare_knowledge_document(draft(document_version="1.0.1"))
    assert (
        original.manifest.normalized_content_sha256
        != content_changed.manifest.normalized_content_sha256
    )
    assert original.manifest.governance_sha256 == content_changed.manifest.governance_sha256
    assert original.manifest.governance_sha256 != governance_changed.manifest.governance_sha256
    assert (
        len(
            {
                original.manifest.document_fingerprint,
                content_changed.manifest.document_fingerprint,
                governance_changed.manifest.document_fingerprint,
            }
        )
        == 3
    )


@pytest.mark.parametrize(
    "bad_draft",
    [
        lambda: draft(namespace="payroll"),
        lambda: draft(customer_environment_id="customer_a"),
        lambda: draft(source_type="customer_policy", customer_environment_id=None),
        lambda: draft(data_classification="highly_restricted"),
        lambda: draft(required_modules_all=("leave",)),
    ],
)
def test_governance_violations_fail_closed(bad_draft: object) -> None:
    with pytest.raises(ValueError):
        prepare_knowledge_document(bad_draft())  # type: ignore[operator]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("required_modules_all", ("hr_core", "hr_core")),
        ("required_permissions_all", ("hr.knowledge.read", "hr.knowledge.read")),
        ("allowed_purposes", ("employee_self_service", "employee_self_service")),
        ("legal_entity_ids", ("entity_1", "entity_1")),
        ("approved_at", datetime(2026, 1, 1)),
        ("effective_from", datetime(2026, 1, 1)),
        ("effective_to", datetime(2026, 1, 1)),
    ],
)
def test_scope_duplicates_and_naive_timestamps_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        draft(**{field: value})


def test_effective_to_must_be_strictly_later() -> None:
    with pytest.raises(ValidationError):
        draft(effective_to=NOW)


@pytest.mark.parametrize(
    "section",
    [
        {"section_key": "blank", "heading": " ", "text_blocks": ("text",)},
        {"section_key": "blank", "heading": "Heading", "text_blocks": (" ",)},
        {"section_key": "blank", "heading": "Heading", "text_blocks": ()},
        {"section_key": "blank", "heading": "Bad\x00Heading", "text_blocks": ("text",)},
        {"section_key": "blank", "heading": "Heading", "text_blocks": ("bad\x01text",)},
    ],
)
def test_blank_and_control_text_is_rejected(section: dict[str, object]) -> None:
    with pytest.raises((ValidationError, ValueError)):
        KnowledgeSection.model_validate(section)
    with pytest.raises(ValidationError):
        draft(title=" ")


def test_duplicate_sections_and_defensive_blank_chunks_are_rejected() -> None:
    duplicate = KnowledgeSection(section_key="same", heading="Same", text_blocks=("text",))
    with pytest.raises(ValidationError):
        draft(sections=(duplicate, duplicate))
    unsafe = KnowledgeSection.model_construct(
        section_key="unsafe", heading="Unsafe", text_blocks=("  ",)
    )
    with pytest.raises(ValueError, match="normalized block"):
        chunk_sections(
            (unsafe,),
            IngestionLimits(maximum_chunk_characters=1, maximum_chunk_bytes=10),
        )
    blank = KnowledgeSection.model_construct(
        section_key="unsafe", heading="Unsafe", text_blocks=(" ",)
    )
    with pytest.raises(ValueError, match="blank prepared"):
        chunk_sections((blank,), IngestionLimits())


def test_paragraph_boundaries_and_section_local_overlap_are_deterministic() -> None:
    sections = (
        KnowledgeSection(
            section_key="one",
            heading="One",
            text_blocks=("alpha beta gamma", "delta epsilon zeta"),
        ),
        KnowledgeSection(section_key="two", heading="Two", text_blocks=("SECOND SECTION",)),
    )
    limits = IngestionLimits(
        maximum_chunk_characters=24, maximum_chunk_bytes=100, overlap_characters=6
    )
    result = prepare_knowledge_document(draft(sections=sections), limits=limits)
    assert result.chunks[0].content == "alpha beta gamma"
    assert "delta" in result.chunks[1].content
    assert all("SECOND SECTION" not in chunk.content for chunk in result.chunks[:-1])
    assert result.chunks[-1].content == "SECOND SECTION"
    assert all(chunk.content.strip() for chunk in result.chunks)
    assert (
        _overlap_suffix(
            "alpha beta gamma",
            IngestionLimits(overlap_characters=10),
        )
        == "gamma"
    )


def test_oversized_blocks_split_on_whitespace_and_indivisible_tokens_fail() -> None:
    limits = IngestionLimits(
        maximum_chunk_characters=10, maximum_chunk_bytes=20, overlap_characters=2
    )
    section = KnowledgeSection(
        section_key="split", heading="Split", text_blocks=("one two three four",)
    )
    result = prepare_knowledge_document(draft(sections=(section,)), limits=limits)
    assert len(result.chunks) >= 2
    bad = KnowledgeSection(section_key="split", heading="Split", text_blocks=("x" * 11,))
    with pytest.raises(ValueError, match="indivisible"):
        prepare_knowledge_document(draft(sections=(bad,)), limits=limits)


@pytest.mark.parametrize(
    "limits",
    [
        IngestionLimits(maximum_sections=1),
        IngestionLimits(maximum_blocks=1),
        IngestionLimits(maximum_document_bytes=1),
        IngestionLimits(maximum_block_bytes=1),
        IngestionLimits(maximum_chunks=1, maximum_chunk_characters=10, overlap_characters=0),
    ],
)
def test_resource_limit_violations_reject_without_dropping_content(limits: IngestionLimits) -> None:
    sections = (
        KnowledgeSection(
            section_key="one", heading="One", text_blocks=("first block", "second block")
        ),
        KnowledgeSection(section_key="two", heading="Two", text_blocks=("third block",)),
    )
    with pytest.raises(ValueError):
        prepare_knowledge_document(draft(sections=sections), limits=limits)


def test_idempotency_conflicts_and_semver_supersession() -> None:
    original_draft = draft()
    original = prepare_knowledge_document(original_draft)
    existing = manifest(original_draft, original.manifest.document_fingerprint)
    same = prepare_knowledge_document(original_draft, existing=existing)
    assert same.disposition is PreparationDisposition.IDEMPOTENT
    assert same.manifest.supersedes_version is None

    with pytest.raises(ValueError, match="same document version"):
        prepare_knowledge_document(
            draft(
                sections=(KnowledgeSection(section_key="new", heading="New", text_blocks=("new",)),)
            ),
            existing=existing,
        )
    with pytest.raises(ValueError, match="older"):
        prepare_knowledge_document(draft(document_version="0.9.0"), existing=existing)

    superseding = prepare_knowledge_document(draft(document_version="2.0.0"), existing=existing)
    assert superseding.disposition is PreparationDisposition.SUPERSEDING_VERSION
    assert superseding.manifest.supersedes_version == "1.0.0"

    other = existing.model_copy(
        update={"document_id": UUID("22222222-2222-4222-8222-222222222222")}
    )
    with pytest.raises(ValueError, match="document mismatch"):
        prepare_knowledge_document(original_draft, existing=other)


def test_prepared_identifiers_are_opaque_and_do_not_leak_inputs() -> None:
    result = prepare_knowledge_document(
        draft(source_type="customer_policy", customer_environment_id="customer-secret")
    )
    for chunk in result.chunks:
        for generated in (chunk.chunk_id, chunk.citation_id):
            assert generated.startswith(("chk_", "cite_"))
            assert "customer-secret" not in generated
            assert "Employee" not in generated
            assert "/" not in generated


def test_service_requires_validated_input_and_models_are_immutable() -> None:
    with pytest.raises(TypeError):
        prepare_knowledge_document(object())  # type: ignore[arg-type]
    result = prepare_knowledge_document(draft())
    assert isinstance(result.chunks, tuple)
    assert isinstance(result.chunks[0].required_modules_all, tuple)
    with pytest.raises(ValidationError):
        result.total_chunk_count = 99  # type: ignore[misc]
