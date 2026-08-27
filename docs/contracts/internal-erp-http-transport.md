# Internal ERP HTTP transport contract

`POST /v1/chat` is an internal ERP-backend-to-AI boundary. Browsers and mobile applications must
never call it directly, and private networking is not authentication. The JSON body is exactly
`PublicChatRequest`: message, non-streaming flag, and optional response-language preference. It
contains no tenant, user, employee, role, permission, module, legal entity, purpose, snapshot,
route, intent, tool, model, provider, resolver, or audit authority. Identity-like HTTP headers and
all query parameters are rejected. `stream=true` is rejected before authentication because this
transport has no streaming response contract; an omitted `stream` and explicit `stream=false`
produce the same validated value and digest.

The ERP supplies exactly one opaque `Authorization: Bearer ...` assertion. A mandatory injected
`TrustedIngressAuthenticator` receives only a server-generated UUID, `POST`, `/v1/chat`, the
canonical body digest, and the repr-hidden assertion. It may return only the existing opaque
`TrustedRequestReference`; the transport defensively revalidates it and requires its request ID to
match. A production authenticator must verify trusted issuer, intended AI-service audience,
signature or equivalent authenticity, issuance and expiry, replay policy, method, route, body
digest, and approved key rotation/revocation. No temporary JWT, HMAC, OAuth, API-key, or mTLS
implementation exists here.

The body digest is SHA-256 over compact, insertion-ordered UTF-8 JSON with no trailing newline:

1. `domain`: `erp-ai:internal-http-chat:v1`
2. `contract_version`: `1`
3. `method`: `POST`
4. `route_path`: `/v1/chat`
5. `request`: `message`, `stream`, then `preferred_response_language`

Serialization uses compact JSON, explicit object insertion order, UTF-8, no key sorting, and no
trailing newline. It applies no Unicode normalization, so visually similar but byte-distinct
validated strings remain distinct. Defaults are included after strict validation. The digest
excludes the bearer assertion, request ID, host, IP, and forwarded headers and is authentication
binding, not authorization. The trusted resolver still resolves context and route intent. Route
intent is not authorization, and
authorization-snapshot verification remains mandatory.

Processing order is fixed: generate the server UUID; validate scheme, host, method, route, query,
and headers; validate bearer syntax; bounded-stream the body; strictly parse and validate JSON;
calculate the digest; authenticate once; bind the opaque reference; invoke the application once;
revalidate the public result; serialize it. There is no retry, fallback, background work,
streaming, route inference, or duplicated tool authorization.

The authenticated route is the exact ASGI method `POST`, decoded path `/v1/chat`, raw path bytes
`/v1/chat`, and an empty raw query string. Normalized, percent-encoded, dot-segment, duplicate-slash,
semicolon, or trailing-slash variants fail before authentication. Ambiguous framing headers and
malformed lengths fail closed, while the body is consumed once directly from bounded ASGI
`http.request` messages. Disconnects and unexpected message types cannot produce partial requests.

Pre-application terminal failures emit exactly one existing `ApplicationAuditEvent`, with stable
server-owned reason codes and no request content or authentication material. Once the trusted
application is invoked, transport auditing stops: the application owns its one application audit,
and orchestration/gateway own agent/tool audits. Mandatory audit failure withholds the intended
transport response.

HTTP mapping is exhaustive: success `200`; invalid request `400`; missing, malformed, or denied
assertion `401`; oversized body `413`; unsupported media/encoding `415`; authentication,
dependency, or audit unavailability `503`; invalid internal/provider-neutral result `500`.
Unknown application failure codes fail closed to `500`. All chat responses carry the
server-generated `X-Request-ID`, `Cache-Control: no-store`, `Pragma: no-cache`,
`X-Content-Type-Options: nosniff`, and `Referrer-Policy: no-referrer`; `401` also returns generic
`WWW-Authenticate: Bearer`.

The request-ID factory is invoked once for each attempted chat exchange and remains responsible for
globally fresh UUIDs. The transport keeps only a lock-protected set of currently in-flight IDs;
every reservation is removed in a `finally` block on all completion, error, audit-failure,
disconnect, and cancellation paths. A concurrent collision fails before authentication. No
completed-ID history is retained. Sequential reuse is rejected by the durable application-audit
logical-slot conflict rather than an unbounded process-local cache. If the factory cannot produce a
valid UUID or produces an in-flight collision, the transport returns a generic infrastructure
failure with `unavailable` only in the correlation header. No valid new `ApplicationAuditEvent` can
be constructed in that exceptional path, so it is not a completed auditable application outcome;
client identifiers are never substituted.
