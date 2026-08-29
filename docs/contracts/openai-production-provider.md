# Direct OpenAI production provider contract

Contract version: `1.0.0`. Canonical SHA-256:
`04560be15e5927e68a35fad77fd8b25c9598bde693971944bac4562a4a0fa51d`.
The insertion-ordered descriptor in `erp_ai.infrastructure.openai.contracts` freezes the origin,
endpoints, headers, request modes, output projections, privacy, isolation, credential order,
prohibitions, embedding dimension policy, and lifecycle invariants. Its canonical form is compact
finite UTF-8 JSON without sorted-key rewriting or a trailing newline and has no generated
Pydantic-schema dependency.

The production adapter uses only the official fixed `https://api.openai.com` origin and
`POST /v1/responses` plus `POST /v1/embeddings`. It uses HTTPX with TLS verification,
TLS 1.2 or later, `trust_env=False`, identity encoding, no redirects, retries, fallback,
cookies, streaming, background work, or configurable origin. OpenRouter remains a separate
synthetic-test-only adapter.

Each trusted customer environment maps to one exact organization/project, credential
reference, privacy-attestation reference, dated chat snapshot, embedding identity/revision/
dimension, purposes, classifications, and bounded request policy. There is no default route;
projects cannot be shared by two configured customers. Customer and actor identifiers never
enter request bodies, metadata, or safety identifiers. A mandatory async deployment-owned
credential provider resolves a repr-hidden bearer secret once per outbound request, after
routing and privacy authorization.

Responses requests explicitly set `store=false`, `stream=false`, `background=false`, and
`parallel_tool_calls=false`. They use no Conversations, previous response ID, Assistants,
Threads, Files, Batch, hosted retrieval, web search, code execution, computer use, MCP,
remote tools, multimodal inputs, provider metadata, trace identity, or prompt-cache key.
General and final turns supply no tools and explicitly prohibit tools. A routed first turn
supplies one strict function schema and forces that exact function name; zero, multiple,
wrong, malformed, coerced, or extra-argument calls fail closed. Tool authorization remains
owned by `ReadToolGateway`.

The reasoning-output policy is `reject`. The configured reasoning effort does not authorize a
reasoning output item: reasoning summaries and encrypted reasoning are not requested, and every
unexpected item fails closed. Provider response IDs and `previous_response_id` are never retained
or replayed. Function-call IDs are bounded, control-character-free internal transcript bindings;
they remain absent from public and audit models.

Inputs are explicit projections of policy text, validated user text, the one selected schema,
and—on the final turn—the exact assistant call plus matching public tool result. Retrieved
knowledge remains untrusted data. Trusted context, authorization collections, database and
resolver identifiers, audit data, credentials, provider configuration, unrelated tools,
arbitrary model dumps, and internal document metadata are excluded.

Responses require the exact configured model, completed foreground status, one expected
output item, and strict duplicate-key-free UTF-8 JSON. Refusals, incomplete responses,
unknown items, ambiguous tool/text output, invalid arguments, oversized bodies, provider
errors, and model mismatch become one constant safe failure. Provider IDs, usage, headers,
errors, and continuation state are discarded. Cancellation propagates unchanged.

Embedding calls contain one validated input, exact model, dimension, and `float` encoding.
The response must identify the exact model and contain one index-0 finite non-boolean,
non-zero vector of the exact dimension. The deployment-owned revision binds offline ingestion
and online queries; the API response does not prove that internal revision. Independent drift
and retrieval-quality certification is mandatory.

Construction performs no I/O or credential resolution. One bundle owns a shared client,
customer router, model provider, customer-bound embedding adapters, and concurrency-safe
lifecycle compatible with the provider lease in Step 26. `erp_ai.runtime` does not import or
construct OpenAI.

Immediately before each credential resolution, the router captures trusted time once and
revalidates the route and attestation, including exact expiry and the configured maximum lifetime.
Credential results must be exact `SecretStr` instances containing one bounded, non-empty token
without whitespace or control characters. The response body is iterated internally only to enforce
the byte ceiling; OpenAI API response streaming remains disabled.

## Audit ownership

The provider emits no audit event. Completed attempts retain the established execution-order
ownership: pre-application HTTP rejection is one transport event only; trusted-resolution failure
is one application event; an orchestrator-level privacy, routing, or model outcome is one
application plus one agent event; and once a selected tool reaches the gateway there is additionally
exactly one tool event, including gateway denial, tool success, final-model failure, and embedding
failure during knowledge retrieval. Application-audit delivery remains fail closed and attempts
once. Credentials, prompts, outputs, arguments, knowledge, vectors, model/project/call identifiers,
usage, headers, and provider exceptions are never added to those events.
