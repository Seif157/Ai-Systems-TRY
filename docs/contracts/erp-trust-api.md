# ERP trust API contract

This trust API resolves identity and snapshot freshness before routing. It is separate from the
capability-specific Laravel read API, which independently revalidates snapshot and business scope.
Both use server-owned fixed origins and externally provisioned mTLS contexts.

Step 26 constructs one closed ERP trust client and shares it between trusted resolution and
authorization-snapshot verification. The externally provisioned TLS context remains deployment
owned. Readiness proves startup completed, not that the ERP endpoint remains reachable.

The AI uses one normalized fixed HTTPS origin over an externally provisioned mTLS `SSLContext`.
Certificate verification, hostname checking, and TLS 1.2 or newer are validated. Python cannot
reliably prove that a client certificate/private key was loaded into an existing `SSLContext`, so
production composition and deployment startup checks retain that responsibility. Redirects,
proxy/netrc trust, cookies, compression, retries, fallback origins, dynamic paths, and
request-derived routing are forbidden. Final request scheme, host, port, empty query, and exact
fixed path are checked before sending. DNS and network routing remain deployment controls; this is
not claimed as complete application-layer SSRF prevention. Responses are bounded as raw bytes while
streaming and parsed as strict UTF-8 JSON. Duplicate Content-Type, non-identity encoding, and
Set-Cookie fail closed; cookie state is cleared before another request. Logs must exclude
Authorization, assertions, references, request/response bodies, TLS material, and HTTP exceptions.

`POST /internal/ai/v1/resolve` accepts exactly integer `contract_version=1`, the AI-generated
`request_id`, and the 43-character `resolver_reference`. A 200 response contains exactly the same
version/request ID plus `trusted_request_context` and `trusted_route_intent`. ERP stores current
context and an approved UI/workflow intent behind a high-entropy, expiring reference and atomically
consumes it before success. It must never infer intent from message text. Unknown, expired, revoked,
or consumed references are one generic denial. If consumption succeeds but the response is lost,
there is no retry: ERP must mint a new reference and assertion.

`POST /internal/ai/v1/authorization-snapshots/verify` accepts exactly version, request ID, customer
environment ID, user ID, and authorization snapshot ID from the resolved trusted context. Its strict
200 response echoes those bindings and returns only `current`, `stale`, `revoked`, or `mismatched`.
The call remains separate and mandatory. Non-200, malformed, mismatched, TLS/network, or timeout
outcomes are generic unavailability. Each operation is attempted once and cancellation propagates.
Open and close are explicit, concurrency-serialized lifecycle operations; each client owns isolated
connection, cookie, and lifecycle state.

Resolution or snapshot failure creates one application audit and no agent/tool audit. General
success creates one application and one agent audit; an exact ERP/knowledge success additionally
creates one tool audit. Existing audit schemas remain unchanged and never contain trust payloads.
