# Agent orchestration contract

Step 26 injects the model provider and its mandatory lifecycle; it does not construct or approve a
provider. Provider approval remains a deployment-owner responsibility. The exact trusted route is
validated before readiness and public message content cannot select it.

`AgentOrchestrator` is a stateless, model-provider-neutral service for one public chat request. It
connects trusted context, entitlement filtering, an authorized public tool catalog, an injected
`AgentModelProvider`, the authoritative `ReadToolGateway`, validated public results, and a mandatory
agent audit sink. There is no production model adapter or network integration.

## Roles and trust boundaries

Every model turn keeps three roles structurally separate:

- Immutable server-owned policy instructions.
- The untrusted public user message.
- Ordered prior assistant tool calls paired with dedicated results marked
  `untrusted_tool_result`.

Retrieved excerpts remain `untrusted_knowledge_excerpt`. Neither tool output nor retrieved content
is concatenated into system policy. A future model adapter must map tool results to its dedicated
tool-result role and preserve this separation.

The model receives presentation language, authorized tool names/versions/public input schemas, and
the immutable provider-neutral interaction transcript. Each interaction preserves the exact raw
argument JSON and immutable parsed arguments alongside its matching public result so an adapter can
reconstruct assistant-call and tool-result messages without replaying execution. It never receives trusted context, authorization collections,
capability denials, governance metadata, handler/provider types, audit records, or internal output
schemas. Preferred response language affects presentation only; authoritative locale, timezone,
effective dates, legal scope, purpose, entitlements, and routing remain unchanged.

## Structural grounding

Every internal final model response declares an `AnswerBasis` and up to four unique successful
evidence call IDs:

- `general` uses no tool evidence or citations and is rejected after any successful ignored call.
- `knowledge` uses only successful knowledge calls and at least one citation from a selected call.
- `erp_data` uses only successful non-knowledge ERP calls and no citations.
- `mixed` uses at least one successful knowledge call, one successful ERP call, and a citation from
  a selected knowledge call.

Failed, unavailable, unknown, or audit-failed calls cannot become evidence. Citation IDs are
limited to twenty and metadata still comes only from validated knowledge results. Evidence IDs,
the answer basis, call IDs, and grounding traces remain absent from public output and agent audit.
This provides structural evidence binding; it does not parse claims or prove that every
natural-language statement is factually faithful to the selected evidence.

## Bounded loop and model input

The current fixed defaults are six model turns, four tool calls, and 64 KiB of accumulated
serialized public tool results. Exactly one tool call is accepted per model turn; parallel calls
and automatic retries are unsupported. Duplicate call IDs, repeated identical invocations,
malformed responses, provider failures, and exceeded limits terminate safely.

Additional immutable limits are 8,000 characters for the user message, 8,000 characters for the
final answer, 16 KiB for serialized tool arguments, nesting depth 10, 512 JSON nodes, 32
model-facing tools, and 128 KiB for the serialized catalog. Containers and scalar leaves count as
nodes. Live-provider argument JSON is preserved exactly; fake providers use deterministic sorted
compact UTF-8 JSON. Duplicate keys, unsafe numbers, non-object JSON, raw/parsed divergence, and
invalid constructed calls fail closed. Argument limits are checked
before gateway invocation, and the complete transcript budgets are independently recomputed before
every provider turn; catalog limits are checked before model invocation. Violations are
never silently truncated and produce no tool audit when no invocation occurred, but they still
produce exactly one agent-audit attempt.

Catalog overflow returns `AGENT_CATALOG_LIMIT`. A future large ERP installation requires a
deterministic authorized capability-routing stage before model invocation; increasing or silently
truncating the catalog is not the current policy.

The authorized catalog is advisory. Every call—including unknown or unauthorized calls—goes
through `ReadToolGateway`, which independently reauthorizes and creates its existing tool audit.
`AUDIT_UNAVAILABLE` from tool auditing terminates the chat immediately.

## Citations

Only citations observed in successful `search_hr_knowledge` public results can be selected. Model
citation metadata is never accepted. Unknown citations and conflicting observed metadata fail
closed; identical repeated selections are deduplicated while preserving first-selected order.
Public citations omit excerpt content and storage metadata. Citation IDs remain display references,
not authorization proof.

## Agent audit and public failures

Every terminal outcome attempts exactly one separate `AgentAuditEvent`. It contains approved
request/customer/user/purpose identifiers, fixed `agent.chat` action, outcome, and a coarse reason.
It excludes messages, answers, languages, catalogs, tool identities used, arguments/results,
retrieval payload, citations, employee ID, authorization collections, and exception details. Audit
failure is not retried; it withholds success and returns `AUDIT_UNAVAILABLE`.

Public failures use only `AGENT_UNAVAILABLE`, `AGENT_LIMIT_REACHED`, `AGENT_CATALOG_LIMIT`,
`INVALID_MODEL_RESPONSE`, or `AUDIT_UNAVAILABLE` with generic messages. Public successes contain
only answer, response language, and validated citations. Orchestration traces and raw tool
envelopes are never public.

The transcript excludes provider-specific reasoning or continuation state. The synthetic-only
North Mini Code adapter proved that a continuation can succeed after discarding provider state,
but this does not add provider state to the contract or approve production model use. See
[`openrouter-agent-model-provider.md`](openrouter-agent-model-provider.md).

Step 21 makes an explicit trusted routing policy mandatory. `general_only` exposes no tools;
`exact_read_then_final` exposes one authorized exact read tool, requires it on the first turn, and
permits only one grounded final turn after successful execution. See
[`forced-tool-routing.md`](forced-tool-routing.md). The route is not authorization and cannot be
selected through `PublicChatRequest`.

The Step 22 outer application boundary resolves and verifies the trusted intent before invoking
this orchestrator. Failures before invocation have their own minimal application audit and produce
no agent or tool audit.

Step 23 routes the unchanged agent event through a startup-configured customer audit pool. It is
never written to the central application-audit database or to ERP/knowledge pools.
