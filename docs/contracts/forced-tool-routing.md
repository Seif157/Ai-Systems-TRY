# Forced-tool routing contract

Step 21 defines an immutable, server-owned `AgentRoutingPolicy`. It is supplied separately from
`PublicChatRequest`; typed models cannot prove that the future resolver supplying it is trusted.
The production ERP/UI integration must select it explicitly. Keyword routing, model-based intent
classification, and public route selection are prohibited.

## Routes

`general_only` exposes no model tools and accepts only a general answer with no evidence or
citations. Any tool call fails closed.

`exact_read_then_final` names one exact tool and version. Before the first model call, the
orchestrator verifies that exact descriptor against the catalog already filtered by trusted
context, entitlements, roles, permissions, purpose, employee linkage, read-only policy, and
installed handlers. The route grants no authorization. The exposed catalog contains only that
tool, and the first response must call it exactly. A direct answer, mismatch, malformed call, or
unavailable route fails before gateway execution.

The gateway independently reauthorizes and executes once. Failure terminates without another
model turn. Success creates one `final_only` turn with the paired result and no exposed tools. Any
additional call fails locally. The final answer must select that successful call: knowledge tools
require `knowledge` grounding and valid returned citations; structured ERP tools require
`erp_data` grounding and no citations. Mixed and multi-tool routes are unsupported.

## Provider-neutral turn policy

Every `ModelTurnRequest` carries exactly one immutable selection:

- `no_tools`: empty catalog and no interactions;
- `required_exact_tool`: one matching exposed tool and no interaction;
- `final_only`: no exposed catalog and exactly one successful interaction.

The routing, selection, and complete turn models are strict, frozen, reject unknown fields and
coercion, and revalidate existing instances. This defensive validation also rejects inconsistent
objects created through Pydantic's unchecked `model_construct()` API. Tool versions retain the
canonical `MAJOR.MINOR.PATCH` contract.

OpenRouter maps `required_exact_tool` to named-function `tool_choice` and maps `no_tools` and
`final_only` to `tool_choice="none"`. Local validation remains authoritative: the adapter accepts
at most one exact call and rejects every call in final-only mode. `parallel_tool_calls` remains
omitted, and provider continuation state is discarded and never replayed.

## Boundaries

Routing policy, selected tools, transcripts, arguments, results, evidence identifiers, and
provider state are absent from public and audit schemas. Agent auditing remains exactly once per
terminal outcome; tool auditing occurs only when the gateway is invoked. Protocol compatibility
does not establish trusted route selection, authorization, grounding quality, provider privacy, or
production model approval.

For an exact route, final grounding must name exactly the one successful call. A structured ERP
tool requires `erp_data` and no citations. A knowledge tool requires `knowledge` and at least one
citation originating in that call. General and mixed bases are rejected.
