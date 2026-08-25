# OpenRouter agent model provider contract

`OpenRouterAgentModelProvider` is a generic implementation of the provider-neutral
`AgentModelProvider` Protocol with one certified, immutable profile:

- model: `cohere/north-mini-code:free`
- classification: `synthetic_test_only`
- endpoint: `https://openrouter.ai/api/v1/chat/completions`
- server secret: `ERP_AI_OPENROUTER_API_KEY`
- routing: required-parameter filtering with provider fallback disabled
- transport: non-streaming API requests, no redirect following, no environment proxy trust,
  no retry, and one sequential request at a time

This adapter is not wired into application startup and must never receive real ERP, HR, customer,
employee, payroll, leave, policy, knowledge, or repository content. The free endpoint has not been
approved for production privacy, retention, data residency, or Arabic HR quality. Model selection,
tool policy, and credentials remain server-owned and are absent from public request and audit
schemas.

## Request mapping

The adapter emits one system message containing the ordered server policy, followed by the user
message. Every completed Step 20A interaction is reconstructed as an assistant tool-call message
immediately followed by the matching `role=tool` public result. Call ID, function name, and the
original `arguments_json` string are copied exactly and interactions are never sorted. Trusted
context, identities, roles, permissions, legal entities, enabled modules, internal denial reasons,
and audit records are not part of `ModelTurnRequest` and are never added by the adapter.

The catalog is translated to exactly the authorized provider-neutral tool definitions. Requests
always send `reasoning.exclude=true`, `provider.require_parameters=true`,
`provider.allow_fallbacks=false`, and `stream=false`. `parallel_tool_calls` is deliberately omitted:
the certified endpoint rejects the complete profile when it is present. The adapter independently
accepts no more than one returned call.

The provider-neutral request does not yet express a server-required tool choice. A configured
named-function `tool_choice` is therefore permitted only by this synthetic-test adapter on turn
one. Production routing needs an approved provider-neutral forced-tool policy before this mechanism
can be used outside synthetic certification. No public request can select it.

## Response validation

Responses have bounded status, media type, byte size, JSON shape, choice count, finish reason, and
content size. Exactly one choice with strict integer index `0` is required. The returned model must
exactly equal `cohere/north-mini-code:free`. A tool response
must contain exactly one known function with one bounded call ID and exact bounded JSON arguments;
zero calls fail when the synthetic server policy forces a tool. Multiple, unknown, malformed,
duplicate-key, non-finite, or mismatched calls fail before execution. The orchestrator and gateway
still revalidate the call and authorization before any handler runs.

A final response must contain no tool call and must be a strict `ModelFinalAnswer` JSON object.
There is no parsing repair, retry, model fallback, provider substitution, or exposure of provider
errors. Cancellation propagates; timeouts and all other provider failures become the same safe
internal exception without remote details.

The pinned non-streaming endpoint includes a tool-call `index` value. The adapter requires the
strict integer value `0` (not `false`, `0.0`, or a string), does not place it in the
provider-neutral call, and rejects missing, different, or unknown tool-call fields.

## Continuation-state isolation

OpenRouter returned provider-specific reasoning/continuation fields during the certified first
turn even with reasoning excluded. Their values are not inspected, serialized, logged, persisted,
placed in exceptions, returned through contracts, or replayed. Only standard assistant role,
content, call ID, function name, and exact argument JSON are reconstructed for the next request.
Unknown response fields fail closed rather than silently becoming continuation state.

On 2026-08-25, a bounded live synthetic probe completed both requests successfully against the
exact model. The first response returned exactly one valid named forced call. The continuation
discarded provider state, replayed only the assistant call and matching synthetic result, and
returned a final text answer without another call. This proves protocol compatibility only; it is
not production, privacy, multilingual-quality, or ERP-data approval.

## Tests and deferred production work

Normal tests use `httpx.MockTransport` and cover exact replay, state disposal, provider and model
failures, malformed calls and final JSON, byte limits, timeout, and cancellation. The live test is
skipped unless `ERP_AI_REQUIRE_OPENROUTER_TESTS=1` and `ERP_AI_OPENROUTER_API_KEY` are both supplied.
It uses fixed synthetic content only and performs no retry.

Production adoption still requires an approved model/provider, privacy and retention review,
secret-manager integration, a provider-neutral forced-tool routing policy, operational monitoring,
rate and cost controls, and independent Arabic/English ERP evaluation.
