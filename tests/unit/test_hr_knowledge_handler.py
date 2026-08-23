import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import BaseModel

from erp_ai.capabilities.hr_knowledge import SearchHrKnowledgeHandler, SearchHrKnowledgeInput
from erp_ai.context import TrustedRequestContext
from erp_ai.knowledge import KnowledgeMatch, KnowledgeRetrievalRequest

NOW = datetime(2026, 8, 23, 10, 0, tzinfo=ZoneInfo("Africa/Cairo"))


class WrongInput(BaseModel):
    pass


class FakeProvider:
    def __init__(self, matches: tuple[KnowledgeMatch, ...] = ()) -> None:
        self.matches = matches
        self.requests: list[KnowledgeRetrievalRequest] = []
        self.raises = False

    async def retrieve(self, request: KnowledgeRetrievalRequest) -> tuple[KnowledgeMatch, ...]:
        self.requests.append(request)
        if self.raises:
            raise RuntimeError("private retrieval failure")
        return self.matches


def context(**overrides: object) -> TrustedRequestContext:
    values: dict[str, object] = {
        "context_version": 1,
        "request_id": "correlation_1",
        "customer_environment_id": "customer_a",
        "user_id": "user_a",
        "employee_id": None,
        "roles": ("employee",),
        "permission_codes": ("hr.knowledge.read", "leave.policy.read"),
        "legal_entity_ids": ("entity_1",),
        "enabled_modules": ("hr_core",),
        "locale": "ar-EG",
        "timezone": "Africa/Cairo",
        "purpose": "employee_self_service",
        "issued_at": NOW,
        "authorization_snapshot_id": "snapshot_1",
    }
    values.update(overrides)
    return TrustedRequestContext.model_validate(values)


def match(**overrides: object) -> KnowledgeMatch:
    values: dict[str, object] = {
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
        "title": "Handbook",
        "section": "Leave",
        "document_version": 2,
        "effective_from": NOW - timedelta(days=1),
        "effective_to": NOW + timedelta(days=1),
        "content": "Use the employee portal.",
        "relevance_score": 0.9,
    }
    values.update(overrides)
    return KnowledgeMatch.model_validate(values)


def run(provider: FakeProvider, *, ctx: TrustedRequestContext | None = None) -> object:
    return asyncio.run(
        SearchHrKnowledgeHandler(provider).execute(
            ctx or context(), SearchHrKnowledgeInput(query="سياسة الإجازات")
        )
    )


def test_handler_sends_complete_trusted_scope_and_returns_safe_projection() -> None:
    provider = FakeProvider((match(),))
    output = run(provider)
    request = provider.requests[0]
    assert request.namespace == "hr"
    assert request.maximum_results == 5
    assert request.customer_environment_id == "customer_a"
    assert request.enabled_modules == ("hr_core",)
    assert request.permission_codes == ("hr.knowledge.read", "leave.policy.read")
    assert request.roles == ("employee",)
    assert request.authorized_legal_entity_ids == ("entity_1",)
    assert request.purpose == "employee_self_service"
    assert request.locale == "ar-EG"
    assert request.effective_at == NOW
    assert output.excerpts[0].content_trust == "untrusted_knowledge_excerpt"  # type: ignore[attr-defined]


def test_empty_results_succeed() -> None:
    assert run(FakeProvider()).excerpts == ()  # type: ignore[attr-defined]


def test_customer_policy_requires_exact_customer() -> None:
    run(FakeProvider((match(source_type="customer_policy", customer_environment_id="customer_a"),)))
    with pytest.raises(RuntimeError):
        run(
            FakeProvider(
                (match(source_type="customer_policy", customer_environment_id="customer_b"),)
            )
        )


def test_global_product_document_cannot_have_customer() -> None:
    with pytest.raises(RuntimeError):
        run(FakeProvider((match(customer_environment_id="customer_a"),)))


@pytest.mark.parametrize(
    "override",
    [
        {"namespace": "payroll"},
        {"required_modules_all": ("leave",)},
        {"required_permissions_all": ("missing.permission",)},
        {"allowed_purposes": ("manager_service",)},
        {"legal_entity_ids": ("entity_2",)},
        {"effective_from": NOW + timedelta(seconds=1)},
        {"effective_to": NOW - timedelta(seconds=1)},
        {"data_classification": "highly_restricted"},
    ],
)
def test_unauthorized_or_invalid_scope_fails_closed(override: dict[str, object]) -> None:
    with pytest.raises(RuntimeError):
        run(FakeProvider((match(**override),)))


def test_leave_document_requires_enabled_leave_module() -> None:
    leave_match = match(required_modules_all=("hr_core", "leave"))
    with pytest.raises(RuntimeError):
        run(FakeProvider((leave_match,)))
    run(FakeProvider((leave_match,)), ctx=context(enabled_modules=("hr_core", "leave")))


def test_count_combined_size_and_duplicates_fail() -> None:
    six = tuple(match(chunk_id=f"chunk_{i}", citation_id=f"cite_{i}") for i in range(6))
    with pytest.raises(RuntimeError):
        run(FakeProvider(six))
    large = tuple(
        match(chunk_id=f"chunk_{i}", citation_id=f"cite_{i}", content="x" * 3001) for i in range(4)
    )
    with pytest.raises(RuntimeError):
        run(FakeProvider(large))
    with pytest.raises(RuntimeError):
        run(FakeProvider((match(), match(document_id="document_2"))))
    with pytest.raises(RuntimeError):
        run(FakeProvider((match(), match(chunk_id="chunk_2"))))


def test_order_is_validated_and_preserved_with_equal_score_tie_breaker() -> None:
    first = match(chunk_id="chunk_a", citation_id="cite_a", relevance_score=0.9)
    second = match(chunk_id="chunk_b", citation_id="cite_b", relevance_score=0.9)
    output = run(FakeProvider((first, second)))
    assert tuple(item.citation_id for item in output.excerpts) == ("cite_a", "cite_b")  # type: ignore[attr-defined]
    with pytest.raises(RuntimeError):
        run(FakeProvider((second, first)))
    with pytest.raises(RuntimeError):
        run(
            FakeProvider(
                (first, match(chunk_id="chunk_c", citation_id="cite_c", relevance_score=1.0))
            )
        )


def test_provider_exception_propagates_to_gateway_boundary() -> None:
    provider = FakeProvider()
    provider.raises = True
    with pytest.raises(RuntimeError, match="private retrieval failure"):
        run(provider)


def test_handler_rejects_wrong_provider_input_and_collection_types() -> None:
    with pytest.raises(TypeError):
        SearchHrKnowledgeHandler(object())  # type: ignore[arg-type]
    provider = FakeProvider()
    with pytest.raises(TypeError):
        asyncio.run(SearchHrKnowledgeHandler(provider).execute(context(), WrongInput()))

    class MutableProvider:
        async def retrieve(self, request: KnowledgeRetrievalRequest) -> tuple[KnowledgeMatch, ...]:
            return []  # type: ignore[return-value]

    with pytest.raises(RuntimeError):
        asyncio.run(
            SearchHrKnowledgeHandler(MutableProvider()).execute(
                context(), SearchHrKnowledgeInput(query="policy")
            )
        )

    class InvalidItemProvider:
        async def retrieve(self, request: KnowledgeRetrievalRequest) -> tuple[KnowledgeMatch, ...]:
            return (object(),)  # type: ignore[return-value]

    with pytest.raises(RuntimeError):
        asyncio.run(
            SearchHrKnowledgeHandler(InvalidItemProvider()).execute(
                context(), SearchHrKnowledgeInput(query="policy")
            )
        )
