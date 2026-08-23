"""Post-validating handler for authorized HR knowledge retrieval."""

from dataclasses import dataclass

from pydantic import BaseModel

from erp_ai.capabilities import DataClassification
from erp_ai.capabilities.hr_knowledge.models import (
    KnowledgeExcerpt,
    SearchHrKnowledgeInput,
    SearchHrKnowledgeOutput,
)
from erp_ai.context import TrustedRequestContext
from erp_ai.knowledge import (
    KnowledgeMatch,
    KnowledgeRetrievalProvider,
    KnowledgeRetrievalRequest,
    KnowledgeSourceType,
)

_HR_NAMESPACE = "hr"
_MAX_RESULTS = 5
_MAX_COMBINED_CONTENT = 12_000
_CLASSIFICATION_RANK = {
    DataClassification.PUBLIC: 0,
    DataClassification.INTERNAL: 1,
    DataClassification.RESTRICTED: 2,
    DataClassification.HIGHLY_RESTRICTED: 3,
}


class _KnowledgeUnavailableError(RuntimeError):
    """Internal retrieval failure collapsed to a generic gateway error."""


@dataclass(frozen=True, slots=True)
class SearchHrKnowledgeHandler:
    """Retrieve pre-filtered HR knowledge and independently verify every match."""

    provider: KnowledgeRetrievalProvider

    tool_name = "search_hr_knowledge"
    version = "1.0.0"
    input_model = SearchHrKnowledgeInput
    output_model = SearchHrKnowledgeOutput

    def __post_init__(self) -> None:
        if not isinstance(self.provider, KnowledgeRetrievalProvider):
            raise TypeError("provider must implement KnowledgeRetrievalProvider")

    async def execute(self, context: TrustedRequestContext, arguments: BaseModel) -> object:
        if not isinstance(arguments, SearchHrKnowledgeInput):
            raise TypeError("unexpected HR knowledge input model")

        request = KnowledgeRetrievalRequest(
            namespace=_HR_NAMESPACE,
            query=arguments.query,
            maximum_results=_MAX_RESULTS,
            customer_environment_id=context.customer_environment_id,
            enabled_modules=context.enabled_modules,
            permission_codes=context.permission_codes,
            roles=context.roles,
            authorized_legal_entity_ids=context.legal_entity_ids,
            purpose=context.purpose,
            locale=context.locale,
            effective_at=context.issued_at,
        )
        matches = await self.provider.retrieve(request)
        if not isinstance(matches, tuple):
            raise _KnowledgeUnavailableError("provider collection must be immutable")
        self._validate_matches(context, matches)
        return SearchHrKnowledgeOutput(
            excerpts=tuple(
                KnowledgeExcerpt(
                    citation_id=match.citation_id,
                    title=match.title,
                    section=match.section,
                    language=match.language,
                    source_type=match.source_type,
                    document_version=match.document_version,
                    content=match.content,
                )
                for match in matches
            )
        )

    @staticmethod
    def _validate_matches(
        context: TrustedRequestContext, matches: tuple[KnowledgeMatch, ...]
    ) -> None:
        if len(matches) > _MAX_RESULTS:
            raise _KnowledgeUnavailableError("provider result count exceeded")
        if not all(isinstance(match, KnowledgeMatch) for match in matches):
            raise _KnowledgeUnavailableError("provider returned invalid match type")
        if len({match.chunk_id for match in matches}) != len(matches):
            raise _KnowledgeUnavailableError("duplicate chunks")
        if len({match.citation_id for match in matches}) != len(matches):
            raise _KnowledgeUnavailableError("duplicate citations")
        if sum(len(match.content) for match in matches) > _MAX_COMBINED_CONTENT:
            raise _KnowledgeUnavailableError("combined content exceeded")

        enabled = set(context.enabled_modules)
        permissions = set(context.permission_codes)
        legal_entities = set(context.legal_entity_ids)
        for index, match in enumerate(matches):
            if index and (-matches[index - 1].relevance_score, matches[index - 1].chunk_id) > (
                -match.relevance_score,
                match.chunk_id,
            ):
                raise _KnowledgeUnavailableError("provider order invalid")
            if match.namespace != _HR_NAMESPACE:
                raise _KnowledgeUnavailableError("namespace mismatch")
            if not set(match.required_modules_all).issubset(enabled):
                raise _KnowledgeUnavailableError("module scope mismatch")
            if not set(match.required_permissions_all).issubset(permissions):
                raise _KnowledgeUnavailableError("permission scope mismatch")
            if context.purpose not in match.allowed_purposes:
                raise _KnowledgeUnavailableError("purpose scope mismatch")
            if match.source_type is KnowledgeSourceType.PRODUCT_DOCUMENTATION:
                if match.customer_environment_id is not None:
                    raise _KnowledgeUnavailableError("global document has customer scope")
            elif match.customer_environment_id != context.customer_environment_id:
                raise _KnowledgeUnavailableError("customer scope mismatch")
            if not set(match.legal_entity_ids).issubset(legal_entities):
                raise _KnowledgeUnavailableError("legal entity scope mismatch")
            if context.issued_at < match.effective_from or (
                match.effective_to is not None and context.issued_at > match.effective_to
            ):
                raise _KnowledgeUnavailableError("document not effective")
            if (
                _CLASSIFICATION_RANK[match.data_classification]
                > _CLASSIFICATION_RANK[DataClassification.RESTRICTED]
            ):
                raise _KnowledgeUnavailableError("classification unsupported")
