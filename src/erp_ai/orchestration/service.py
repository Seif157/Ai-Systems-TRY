"""Bounded stateless orchestration through the authoritative read-tool gateway."""

import json
from dataclasses import dataclass, field

from erp_ai.api import PublicChatRequest
from erp_ai.capabilities import CapabilityRegistry, DataClassification, evaluate_capability_access
from erp_ai.capabilities.hr_knowledge import SearchHrKnowledgeOutput
from erp_ai.context import TrustedRequestContext
from erp_ai.orchestration.audit import (
    AgentAuditSink,
    create_agent_audit_event,
)
from erp_ai.orchestration.models import (
    AgentErrorCode,
    AgentLimits,
    AnswerBasis,
    ModelFinalAnswer,
    ModelToolCall,
    ModelToolDefinition,
    ModelToolInteraction,
    ModelToolSelection,
    ModelTurnRequest,
    PublicChatFailure,
    PublicChatResult,
    PublicChatSuccess,
    PublicCitation,
    ToolResultMessage,
    ToolSelectionMode,
    _json_values_equivalent,
    to_mutable_json,
)
from erp_ai.orchestration.policy import AGENT_POLICY_INSTRUCTIONS
from erp_ai.orchestration.provider import AgentModelProvider
from erp_ai.orchestration.routing import AgentRouteMode, AgentRoutingPolicy
from erp_ai.tools import PublicToolFailure, PublicToolSuccess, ReadToolGateway, ToolErrorCode
from erp_ai.tools.models import ToolInvocation

_SAFE_MESSAGES = {
    AgentErrorCode.AGENT_UNAVAILABLE: "The assistant is temporarily unavailable.",
    AgentErrorCode.AGENT_LIMIT_REACHED: "The assistant could not complete within safe limits.",
    AgentErrorCode.AGENT_CATALOG_LIMIT: "The authorized tool catalog exceeds safe limits.",
    AgentErrorCode.INVALID_MODEL_RESPONSE: "The assistant returned an invalid response.",
    AgentErrorCode.AUDIT_UNAVAILABLE: "The assistant response could not be safely recorded.",
}


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _json_depth_and_nodes(value: object, depth: int = 1) -> tuple[int, int]:
    if isinstance(value, dict):
        child_metrics = tuple(_json_depth_and_nodes(item, depth + 1) for item in value.values())
    elif isinstance(value, list):
        child_metrics = tuple(_json_depth_and_nodes(item, depth + 1) for item in value)
    else:
        return depth, 1
    return (
        max((child_depth for child_depth, _ in child_metrics), default=depth),
        1 + sum(nodes for _, nodes in child_metrics),
    )


@dataclass(frozen=True, slots=True)
class _SuccessfulEvidenceCall:
    call_id: str
    tool_name: str
    version: str
    is_knowledge: bool
    citation_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True, init=False)
class AgentOrchestrator:
    """Run one isolated chat request with fixed limits and mandatory final audit."""

    registry: CapabilityRegistry = field(repr=False)
    tool_gateway: ReadToolGateway = field(repr=False)
    model_provider: AgentModelProvider = field(repr=False)
    audit_sink: AgentAuditSink = field(repr=False)
    limits: AgentLimits

    def __init__(
        self,
        registry: CapabilityRegistry,
        tool_gateway: ReadToolGateway,
        model_provider: AgentModelProvider,
        audit_sink: AgentAuditSink,
        limits: AgentLimits | None = None,
    ) -> None:
        if tool_gateway.registry is not registry:
            raise ValueError("orchestrator and gateway must share the capability registry")
        if not isinstance(model_provider, AgentModelProvider):
            raise TypeError("model_provider must implement AgentModelProvider")
        if not isinstance(audit_sink, AgentAuditSink):
            raise TypeError("audit_sink must implement AgentAuditSink")
        object.__setattr__(self, "registry", registry)
        object.__setattr__(self, "tool_gateway", tool_gateway)
        object.__setattr__(self, "model_provider", model_provider)
        object.__setattr__(self, "audit_sink", audit_sink)
        object.__setattr__(self, "limits", limits or AgentLimits())

    async def execute(
        self,
        context: TrustedRequestContext,
        request: PublicChatRequest,
        routing: AgentRoutingPolicy,
    ) -> PublicChatResult:
        """Execute one explicitly routed run and audit its single terminal outcome."""

        try:
            routing = AgentRoutingPolicy.model_validate(routing, strict=True)
        except Exception:
            return await self._finish_failure(
                context, AgentErrorCode.INVALID_MODEL_RESPONSE, "invalid_route"
            )

        if len(request.message) > self.limits.maximum_user_message_characters:
            return await self._finish_failure(
                context,
                AgentErrorCode.AGENT_LIMIT_REACHED,
                "user_message_limit_reached",
            )
        response_language = request.preferred_response_language or context.locale
        authorized_tools = self._authorized_catalog(context)
        authorized_catalog_payload = [tool.model_dump(mode="json") for tool in authorized_tools]
        if (
            len(authorized_tools) > self.limits.maximum_model_tools
            or len(_canonical_json_bytes(authorized_catalog_payload))
            > self.limits.maximum_tool_catalog_bytes
        ):
            return await self._finish_failure(
                context,
                AgentErrorCode.AGENT_CATALOG_LIMIT,
                "tool_catalog_limit_reached",
            )
        if routing.mode is AgentRouteMode.GENERAL_ONLY:
            tools: tuple[ModelToolDefinition, ...] = ()
            maximum_data_classification = DataClassification.RESTRICTED
        else:
            tools = tuple(
                tool
                for tool in authorized_tools
                if tool.tool_name == routing.tool_name and tool.version == routing.version
            )
            if len(tools) != 1:
                return await self._finish_failure(
                    context, AgentErrorCode.INVALID_MODEL_RESPONSE, "route_not_authorized"
                )
            matching_descriptors = tuple(
                tool
                for manifest in self.registry.manifests
                for tool in manifest.tools
                if tool.tool_name == routing.tool_name and tool.version == routing.version
            )
            if len(matching_descriptors) != 1:  # pragma: no cover - registry invariant
                return await self._finish_failure(
                    context, AgentErrorCode.INVALID_MODEL_RESPONSE, "route_not_authorized"
                )
            classification_order = {
                DataClassification.PUBLIC: 0,
                DataClassification.INTERNAL: 1,
                DataClassification.RESTRICTED: 2,
                DataClassification.HIGHLY_RESTRICTED: 3,
            }
            maximum_data_classification = max(
                (DataClassification.RESTRICTED, matching_descriptors[0].data_classification),
                key=classification_order.__getitem__,
            )
            if self.limits.maximum_tool_calls < 1 or self.limits.maximum_model_turns < 2:
                return await self._finish_failure(
                    context, AgentErrorCode.AGENT_LIMIT_REACHED, "route_resource_limit_reached"
                )
        interactions: list[ModelToolInteraction] = []
        citations: dict[str, PublicCitation] = {}
        successful_calls: dict[str, _SuccessfulEvidenceCall] = {}

        maximum_turns = 1 if routing.mode is AgentRouteMode.GENERAL_ONLY else 2
        for turn_number in range(1, maximum_turns + 1):
            transcript = tuple(interactions)
            transcript_failure = self._transcript_failure(transcript)
            if transcript_failure is not None:
                return await self._finish_failure(context, *transcript_failure)
            turn_tools: tuple[ModelToolDefinition, ...]
            if routing.mode is AgentRouteMode.GENERAL_ONLY:
                selection = ModelToolSelection(mode=ToolSelectionMode.NO_TOOLS)
                turn_tools = ()
            elif turn_number == 1:
                selection = ModelToolSelection(
                    mode=ToolSelectionMode.REQUIRED_EXACT_TOOL,
                    tool_name=routing.tool_name,
                    version=routing.version,
                )
                turn_tools = tools
            else:
                selection = ModelToolSelection(mode=ToolSelectionMode.FINAL_ONLY)
                turn_tools = ()
            turn = ModelTurnRequest(
                policy_instructions=AGENT_POLICY_INSTRUCTIONS,
                user_message=request.message,
                response_language=response_language,
                tools=turn_tools,
                tool_selection=selection,
                interactions=transcript,
                turn_number=turn_number,
                routing_customer_environment_id=context.customer_environment_id,
                maximum_data_classification=maximum_data_classification,
                purpose=context.purpose,
            )
            try:
                model_response: object = await self.model_provider.complete_turn(turn)
            except Exception:
                return await self._finish_failure(
                    context, AgentErrorCode.AGENT_UNAVAILABLE, "model_provider_failed"
                )

            if isinstance(model_response, ModelFinalAnswer):
                if routing.mode is AgentRouteMode.EXACT_READ_THEN_FINAL and turn_number == 1:
                    return await self._finish_failure(
                        context,
                        AgentErrorCode.INVALID_MODEL_RESPONSE,
                        "required_tool_call_missing",
                    )
                if len(model_response.answer) > self.limits.maximum_final_answer_characters:
                    return await self._finish_failure(
                        context,
                        AgentErrorCode.AGENT_LIMIT_REACHED,
                        "final_answer_limit_reached",
                    )
                public_citations = self._validate_grounding(
                    model_response, successful_calls, citations
                )
                if routing.mode is AgentRouteMode.GENERAL_ONLY and (
                    model_response.answer_basis is not AnswerBasis.GENERAL
                    or model_response.evidence_call_ids
                    or model_response.citation_ids
                ):
                    public_citations = None
                if routing.mode is AgentRouteMode.EXACT_READ_THEN_FINAL and not (
                    self._matches_exact_route_grounding(model_response, successful_calls)
                ):
                    public_citations = None
                if public_citations is None:
                    return await self._finish_failure(
                        context,
                        AgentErrorCode.INVALID_MODEL_RESPONSE,
                        "citation_validation_failed",
                    )
                success = PublicChatSuccess(
                    answer=model_response.answer,
                    response_language=response_language,
                    citations=public_citations,
                )
                return await self._finish(context, success, "success", "completed")

            if not isinstance(model_response, ModelToolCall):
                return await self._finish_failure(
                    context,
                    AgentErrorCode.INVALID_MODEL_RESPONSE,
                    "invalid_model_response",
                )
            if routing.mode is AgentRouteMode.GENERAL_ONLY or turn_number != 1:
                return await self._finish_failure(
                    context,
                    AgentErrorCode.INVALID_MODEL_RESPONSE,
                    "tool_call_not_allowed",
                )
            try:
                validated_call = ModelToolCall.from_arguments_json(
                    call_id=model_response.call_id,
                    tool_name=model_response.tool_name,
                    version=model_response.version,
                    arguments_json=model_response.arguments_json,
                )
                if not _json_values_equivalent(
                    to_mutable_json(validated_call.arguments),
                    to_mutable_json(model_response.arguments),
                ):
                    raise ValueError("raw and parsed arguments diverge")
                model_response = validated_call
            except Exception:
                return await self._finish_failure(
                    context,
                    AgentErrorCode.INVALID_MODEL_RESPONSE,
                    "invalid_model_tool_call",
                )
            if (
                model_response.tool_name != routing.tool_name
                or model_response.version != routing.version
            ):
                return await self._finish_failure(
                    context,
                    AgentErrorCode.INVALID_MODEL_RESPONSE,
                    "routed_tool_mismatch",
                )
            mutable_arguments = to_mutable_json(model_response.arguments)
            argument_bytes = model_response.arguments_json.encode("utf-8")
            argument_depth, argument_nodes = _json_depth_and_nodes(mutable_arguments)
            if (
                len(argument_bytes) > self.limits.maximum_tool_argument_bytes
                or argument_depth > self.limits.maximum_argument_depth
                or argument_nodes > self.limits.maximum_argument_nodes
            ):
                return await self._finish_failure(
                    context,
                    AgentErrorCode.AGENT_LIMIT_REACHED,
                    "tool_argument_limit_reached",
                )

            invocation = ToolInvocation(
                tool_name=model_response.tool_name,
                version=model_response.version,
                arguments=model_response.arguments,
            )
            result = await self.tool_gateway.execute(context, invocation)
            if (
                isinstance(result, PublicToolFailure)
                and result.safe_error_code is ToolErrorCode.AUDIT_UNAVAILABLE
            ):
                return await self._finish_failure(
                    context,
                    AgentErrorCode.AUDIT_UNAVAILABLE,
                    "tool_audit_unavailable",
                )
            if isinstance(result, PublicToolFailure):
                return await self._finish_failure(
                    context,
                    AgentErrorCode.AGENT_UNAVAILABLE,
                    "routed_tool_failed",
                )

            message = ToolResultMessage(
                call_id=model_response.call_id,
                tool_name=model_response.tool_name,
                result=result,
            )
            interaction = ModelToolInteraction(assistant_call=model_response, tool_result=message)
            candidate_transcript = (*transcript, interaction)
            candidate_failure = self._transcript_failure(candidate_transcript)
            if candidate_failure is not None:
                return await self._finish_failure(context, *candidate_failure)
            call_citations = self._observe_citations(result, citations)
            if call_citations is None:
                return await self._finish_failure(
                    context,
                    AgentErrorCode.INVALID_MODEL_RESPONSE,
                    "citation_metadata_conflict",
                )
            successful_calls[model_response.call_id] = _SuccessfulEvidenceCall(
                call_id=model_response.call_id,
                tool_name=model_response.tool_name,
                version=model_response.version,
                is_knowledge=model_response.tool_name == "search_hr_knowledge",
                citation_ids=call_citations,
            )
            interactions.append(interaction)

        return await self._finish_failure(  # pragma: no cover - both bounded turns terminate above
            context, AgentErrorCode.INVALID_MODEL_RESPONSE, "route_not_completed"
        )

    def _authorized_catalog(
        self, context: TrustedRequestContext
    ) -> tuple[ModelToolDefinition, ...]:
        decision = evaluate_capability_access(self.registry, context, read_only_mode=True)
        installed = {tool.tool_name for tool in self.tool_gateway.available_tools(context)}
        definitions: list[ModelToolDefinition] = []
        for capability in decision.model_capabilities:
            for tool in capability.tools:
                if tool.tool_name not in installed:
                    continue
                schema = self.tool_gateway.public_input_schema(tool.tool_name)
                definitions.append(
                    ModelToolDefinition(
                        tool_name=tool.tool_name,
                        version=tool.version,
                        input_schema=schema,
                    )
                )
        return tuple(sorted(definitions, key=lambda item: item.tool_name))

    def _transcript_failure(
        self, interactions: tuple[ModelToolInteraction, ...]
    ) -> tuple[AgentErrorCode, str] | None:
        """Revalidate all transcript objects and independently recompute every budget."""

        if len(interactions) > self.limits.maximum_tool_calls:
            return AgentErrorCode.AGENT_LIMIT_REACHED, "tool_call_limit_reached"
        call_ids: set[str] = set()
        result_bytes = 0
        try:
            for interaction in interactions:
                validated = ModelToolInteraction.model_validate(
                    {
                        "assistant_call": interaction.assistant_call,
                        "tool_result": interaction.tool_result,
                    },
                    strict=True,
                )
                call = validated.assistant_call
                if call.call_id in call_ids:
                    return AgentErrorCode.INVALID_MODEL_RESPONSE, "duplicate_call_id"
                call_ids.add(call.call_id)
                arguments = to_mutable_json(call.arguments)
                argument_depth, argument_nodes = _json_depth_and_nodes(arguments)
                if (
                    len(call.arguments_json.encode("utf-8"))
                    > self.limits.maximum_tool_argument_bytes
                    or argument_depth > self.limits.maximum_argument_depth
                    or argument_nodes > self.limits.maximum_argument_nodes
                ):
                    return AgentErrorCode.AGENT_LIMIT_REACHED, "tool_argument_limit_reached"
                result_bytes += len(
                    _canonical_json_bytes(validated.tool_result.model_dump(mode="json"))
                )
        except Exception:
            return AgentErrorCode.INVALID_MODEL_RESPONSE, "invalid_interaction_transcript"
        if result_bytes > self.limits.maximum_tool_result_bytes:
            return AgentErrorCode.AGENT_LIMIT_REACHED, "tool_result_size_limit_reached"
        return None

    @staticmethod
    def _matches_exact_route_grounding(
        answer: ModelFinalAnswer,
        successful_calls: dict[str, _SuccessfulEvidenceCall],
    ) -> bool:
        if len(successful_calls) != 1:
            return False
        selected = next(iter(successful_calls.values()))
        if answer.evidence_call_ids != (selected.call_id,):
            return False
        expected_basis = AnswerBasis.KNOWLEDGE if selected.is_knowledge else AnswerBasis.ERP_DATA
        return answer.answer_basis is expected_basis

    @staticmethod
    def _observe_citations(
        result: PublicToolSuccess, observed: dict[str, PublicCitation]
    ) -> tuple[str, ...] | None:
        if result.tool_name != "search_hr_knowledge" or not isinstance(
            result.result, SearchHrKnowledgeOutput
        ):
            return ()
        call_citations: list[str] = []
        for excerpt in result.result.excerpts:
            citation = PublicCitation(
                citation_id=excerpt.citation_id,
                title=excerpt.title,
                section=excerpt.section,
                language=excerpt.language,
                source_type=excerpt.source_type,
                document_version=excerpt.document_version,
            )
            existing = observed.get(citation.citation_id)
            if existing is not None and existing != citation:
                return None
            observed[citation.citation_id] = citation
            call_citations.append(citation.citation_id)
        return tuple(call_citations)

    @staticmethod
    def _validate_grounding(
        answer: ModelFinalAnswer,
        successful_calls: dict[str, _SuccessfulEvidenceCall],
        observed: dict[str, PublicCitation],
    ) -> tuple[PublicCitation, ...] | None:
        if (
            not isinstance(answer.answer_basis, AnswerBasis)
            or len(answer.evidence_call_ids) > 4
            or len(set(answer.evidence_call_ids)) != len(answer.evidence_call_ids)
            or len(answer.citation_ids) > 20
            or len(set(answer.citation_ids)) != len(answer.citation_ids)
        ):
            return None
        evidence = tuple(successful_calls.get(call_id) for call_id in answer.evidence_call_ids)
        if any(item is None for item in evidence):
            return None
        selected_calls = tuple(item for item in evidence if item is not None)
        knowledge_calls = tuple(item for item in selected_calls if item.is_knowledge)
        erp_calls = tuple(item for item in selected_calls if not item.is_knowledge)
        selected_citation_ids = {
            citation_id for item in knowledge_calls for citation_id in item.citation_ids
        }

        if answer.answer_basis is AnswerBasis.GENERAL:
            if answer.evidence_call_ids or answer.citation_ids or successful_calls:
                return None
        elif answer.answer_basis is AnswerBasis.KNOWLEDGE:
            if not knowledge_calls or erp_calls or not answer.citation_ids:
                return None
        elif answer.answer_basis is AnswerBasis.ERP_DATA:
            if not erp_calls or knowledge_calls or answer.citation_ids:
                return None
        else:
            return None

        if any(citation_id not in selected_citation_ids for citation_id in answer.citation_ids):
            return None
        return tuple(observed[citation_id] for citation_id in answer.citation_ids)

    async def _finish_failure(
        self,
        context: TrustedRequestContext,
        code: AgentErrorCode,
        internal_reason: str,
    ) -> PublicChatResult:
        failure = PublicChatFailure(
            safe_error_code=code,
            safe_message=_SAFE_MESSAGES[code],
        )
        return await self._finish(context, failure, "failure", internal_reason)

    async def _finish(
        self,
        context: TrustedRequestContext,
        result: PublicChatResult,
        outcome: str,
        internal_reason: str,
    ) -> PublicChatResult:
        event = create_agent_audit_event(
            context,
            outcome="success" if outcome == "success" else "failure",
            internal_reason=internal_reason,
        )
        try:
            await self.audit_sink.record(event)
        except Exception:
            return PublicChatFailure(
                safe_error_code=AgentErrorCode.AUDIT_UNAVAILABLE,
                safe_message=_SAFE_MESSAGES[AgentErrorCode.AUDIT_UNAVAILABLE],
            )
        return result
