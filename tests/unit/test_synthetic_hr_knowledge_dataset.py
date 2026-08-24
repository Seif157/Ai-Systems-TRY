import re

import pytest
from pydantic import ValidationError

from tests.support.synthetic_hr_knowledge import (
    FIXTURE_ROOT,
    AggregateZeroRecallDiagnostics,
    FixturePublicationDisposition,
    SyntheticEvaluationProvenance,
    SyntheticReferenceCase,
    ZeroRecallReason,
    load_manifest,
    partition_fingerprint,
    prepare_corpus,
    publication_plan,
    reference_cases,
    resolve_labels,
    validate_benchmark_integrity,
)


def test_manifest_corpus_and_partitions_are_deterministic() -> None:
    first = load_manifest()
    second = load_manifest()
    assert first == second and first.synthetic_test_only
    assert len(first.documents) == 16
    assert len(set(first.fictional_customer_uuids.values())) == 2
    assert (
        first.corpus_fingerprint
        == "e7434434e62f3037821cc7ad4f214dbaf03a764d23aabc932e3c4a1ba75debe7"
    )
    assert partition_fingerprint("calibration") == partition_fingerprint("calibration")
    assert partition_fingerprint("calibration") != partition_fingerprint("holdout")
    assert first.case_fingerprint == (
        "ef17652cafc1b620c352734c825fbe7cbf5cfb1dcd31bcbdca91dbd66d8770ff"
    )
    assert first.combined_dataset_fingerprint == (
        "93b18a8395791b835d2f220821e0317104713ca63a67a8742fcfa70c95e220bc"
    )


def test_corpus_loads_through_real_adapter_and_ingestion_contracts() -> None:
    bundles = prepare_corpus()
    assert len(bundles) == 11
    assert all(bundle.total_chunk_count >= 1 for bundle in bundles)
    raw = " ".join(path.read_text(encoding="utf-8") for path in FIXTURE_ROOT.rglob("*.md"))
    assert "SYNTHETIC TEST MATERIAL" in raw
    assert "مادة اختبار اصطناعية" in raw
    assert all(bundle.manifest.namespace == "hr" for bundle in bundles)


def test_every_fixture_has_one_allowlisted_publication_decision() -> None:
    manifest = load_manifest()
    plan = publication_plan(manifest)
    assert len(plan.decisions) == len(manifest.documents) == 16
    assert {item.disposition for item in plan.decisions} == set(FixturePublicationDisposition)
    counts = {
        disposition: sum(item.disposition is disposition for item in plan.decisions)
        for disposition in FixturePublicationDisposition
    }
    assert counts == {
        FixturePublicationDisposition.INCLUDED: 11,
        FixturePublicationDisposition.FUTURE_NOT_EFFECTIVE: 1,
        FixturePublicationDisposition.EXPIRED: 2,
        FixturePublicationDisposition.SUPERSEDED: 1,
        FixturePublicationDisposition.WITHDRAWN: 1,
    }
    published_ids = {bundle.manifest.document_id for bundle in prepare_corpus()}
    expected = {
        item.document_id
        for item in plan.decisions
        if item.disposition is FixturePublicationDisposition.INCLUDED
    }
    assert published_ids == expected


def test_reference_dataset_has_96_machine_authored_cases_and_family_isolation() -> None:
    cases = reference_cases()
    assert len(cases) == 96 and len({case.case_id for case in cases}) == 96
    assert {case.language_slice for case in cases} == {"arabic", "english", "mixed"}
    assert all(case.label_status == "machine_authored_synthetic_reference" for case in cases)
    by_family: dict[str, set[str]] = {}
    for case in cases:
        by_family.setdefault(case.family, set()).add(case.partition)
    assert all(len(partitions) == 1 for partitions in by_family.values())
    assert any(case.expected_empty for case in cases)
    assert any("DROP TABLE" in case.query for case in cases)
    assert any("ignore prior" in case.query for case in cases)


def test_labels_resolve_to_exact_document_sections_without_cross_customer_leaks() -> None:
    manifest = load_manifest()
    bundles = {bundle.manifest.document_id: bundle for bundle in prepare_corpus()}
    customers = {item.id: item.customer for item in manifest.documents}
    for case in reference_cases():
        for label in case.labels:
            bundle = bundles[label.document_id]
            assert any(chunk.section_key == label.section_key for chunk in bundle.chunks)
            owner = customers[label.document_id]
            if owner is not None and label.relevance_grade > 0:
                assert owner == case.customer_key
        resolved = resolve_labels(case)
        assert bool(resolved) is (not case.expected_empty)
    gate = validate_benchmark_integrity()
    assert gate["positive_labels"] == 33
    assert gate["exact_keyword_positive"] == 11
    assert gate["forbidden_labels"] == 16


def test_reference_contract_rejects_duplicate_and_expected_empty_relevance() -> None:
    case = reference_cases()[0]
    with pytest.raises(ValidationError, match="duplicate"):
        SyntheticReferenceCase.model_validate(
            {**case.model_dump(), "labels": (case.labels[0], case.labels[0])}
        )
    with pytest.raises(ValidationError, match="expected-empty"):
        SyntheticReferenceCase.model_validate({**case.model_dump(), "expected_empty": True})


def test_fixture_contains_no_common_pii_or_secret_shapes() -> None:
    raw = "\n".join(path.read_text(encoding="utf-8") for path in FIXTURE_ROOT.rglob("*.md"))
    assert not re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", raw)
    assert not re.search(r"(?:password|api[_ -]?key|secret)\s*[:=]", raw, re.IGNORECASE)
    assert not re.search(r"\b(?:\+?\d[\d -]{8,}\d)\b", raw)
    assert "docs/database/hr" not in raw


def test_complete_evaluation_provenance_is_fingerprint_sensitive_and_test_only() -> None:
    manifest = load_manifest()
    values = {
        "dataset_id": manifest.dataset_id,
        "dataset_version": manifest.dataset_version,
        "corpus_fingerprint": manifest.corpus_fingerprint,
        "calibration_partition_fingerprint": partition_fingerprint("calibration"),
        "holdout_partition_fingerprint": partition_fingerprint("holdout"),
        "active_generation_digest": "a" * 64,
        "embedding_profile_sha256": "b" * 64,
        "embedding_resource_policy_sha256": "c" * 64,
        "embedding_runtime_identity_sha256": "d" * 64,
        "semantic_threshold": 0.5,
        "threshold_approval_status": "unapproved_test_only",
        "hybrid_policy_sha256": "e" * 64,
        "candidate_id": "hybrid",
    }
    first = SyntheticEvaluationProvenance.model_validate(values)
    changed = SyntheticEvaluationProvenance.model_validate(
        {**values, "embedding_runtime_identity_sha256": "f" * 64}
    )
    assert first.evaluation_fingerprint != changed.evaluation_fingerprint
    with pytest.raises(ValidationError):
        SyntheticEvaluationProvenance.model_validate(
            {**values, "threshold_approval_status": "approved"}
        )


def test_zero_recall_diagnostics_are_aggregate_complete_and_strict() -> None:
    counts = {reason: 0 for reason in ZeroRecallReason}
    diagnostics = AggregateZeroRecallDiagnostics(counts=counts)
    assert set(diagnostics.counts) == set(ZeroRecallReason)
    with pytest.raises(ValidationError):
        AggregateZeroRecallDiagnostics(counts={ZeroRecallReason.PROVIDER_FAILURE: 0})
