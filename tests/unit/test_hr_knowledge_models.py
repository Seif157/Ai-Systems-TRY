from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from erp_ai.capabilities.hr_knowledge import SearchHrKnowledgeInput, SearchHrKnowledgeOutput
from erp_ai.knowledge import KnowledgeMatch, KnowledgeRetrievalRequest

NOW = datetime(2026, 8, 23, 10, 0, tzinfo=ZoneInfo("Africa/Cairo"))


def match_data(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "chunk_id": "chunk_1",
        "document_id": "document_1",
        "citation_id": "citation_1",
        "namespace": "hr",
        "source_type": "product_documentation",
        "customer_environment_id": None,
        "required_modules_all": ("hr_core",),
        "required_permissions_all": ("hr.knowledge.read",),
        "allowed_purposes": ("employee_self_service",),
        "legal_entity_ids": (),
        "data_classification": "restricted",
        "language": "en",
        "title": "Employee handbook",
        "section": "Leave",
        "document_version": 1,
        "effective_from": NOW,
        "effective_to": None,
        "content": "Approved policy excerpt.",
        "relevance_score": 0.9,
    }
    data.update(overrides)
    return data


@pytest.mark.parametrize("query", [" leave policy ", "سياسة الإجازات", "English العربية"])
def test_query_supports_trimmed_english_and_arabic(query: str) -> None:
    value = SearchHrKnowledgeInput(query=query)
    assert value.query == query.strip()
    with pytest.raises(ValidationError):
        value.query = "changed"  # type: ignore[misc]


@pytest.mark.parametrize("query", ["", "   ", "bad\x00query", "bad\nquery", "x" * 1001])
def test_query_rejects_blank_control_and_oversized_values(query: str) -> None:
    with pytest.raises(ValidationError):
        SearchHrKnowledgeInput(query=query)


def test_query_rejects_non_string() -> None:
    with pytest.raises(ValidationError):
        SearchHrKnowledgeInput(query=1)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "extra",
    [
        "namespace",
        "customer_environment_id",
        "enabled_modules",
        "permission_codes",
        "roles",
        "purpose",
        "maximum_results",
        "legal_entity_ids",
        "data_classification",
    ],
)
def test_public_input_rejects_filters_and_trusted_context(extra: str) -> None:
    with pytest.raises(ValidationError):
        SearchHrKnowledgeInput.model_validate({"query": "policy", extra: "forged"})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("relevance_score", float("nan")),
        ("relevance_score", float("inf")),
        ("relevance_score", -0.1),
        ("relevance_score", 1.1),
        ("document_version", 0),
        ("effective_from", datetime(2026, 1, 1)),
        ("effective_to", datetime(2026, 1, 1)),
        ("content", "x" * 4001),
        ("content", "   "),
        ("chunk_id", ""),
        ("source_type", "unapproved_upload"),
        ("data_classification", "secret"),
        ("effective_to", NOW.replace(year=2025)),
    ],
)
def test_internal_match_rejects_invalid_provider_values(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        KnowledgeMatch.model_validate(match_data(**{field: value}))


def test_internal_models_are_strict_frozen_and_collections_are_immutable() -> None:
    match = KnowledgeMatch.model_validate(match_data())
    assert isinstance(match.required_modules_all, tuple)
    with pytest.raises(ValidationError):
        match.content = "changed"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        KnowledgeMatch.model_validate({**match_data(), "unknown": True})
    with pytest.raises(ValidationError):
        KnowledgeMatch.model_validate(match_data(required_modules_all=("hr_core", "hr_core")))

    request = KnowledgeRetrievalRequest(
        namespace="hr",
        query="policy",
        maximum_results=5,
        customer_environment_id="customer_a",
        enabled_modules=("hr_core",),
        permission_codes=("hr.knowledge.read",),
        roles=("employee",),
        authorized_legal_entity_ids=("entity_1",),
        purpose="employee_self_service",
        locale="ar-EG",
        effective_at=NOW,
    )
    assert isinstance(request.enabled_modules, tuple)
    with pytest.raises(ValidationError):
        request.query = "changed"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        KnowledgeRetrievalRequest.model_validate(
            {**request.model_dump(), "effective_at": datetime(2026, 8, 23)}
        )
    with pytest.raises(ValidationError):
        KnowledgeRetrievalRequest.model_validate(
            {**request.model_dump(), "enabled_modules": ("hr_core", "hr_core")}
        )


def test_public_output_is_immutable() -> None:
    output = SearchHrKnowledgeOutput(excerpts=())
    with pytest.raises(ValidationError):
        output.excerpts = ()  # type: ignore[misc]
