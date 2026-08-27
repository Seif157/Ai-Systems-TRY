# Trusted route resolution

Free-form text cannot select an authoritative ERP tool. The public request contains only the user
message and presentation preferences. A trusted ERP server or UI workflow must authenticate the
request and mint an opaque `TrustedRequestReference`; its resolver handle is server-internal and
must never enter models, public results, audits, logs, or errors.

The mandatory `TrustedRequestResolver` resolves that reference to a `TrustedRequestContext` and a
versioned `TrustedRouteIntent`. The Protocol expresses shape, not trust: a production resolver must
authenticate the upstream ERP request, enforce tenant isolation, and prevent clients from minting
or selecting intent codes.

The intent binds request, customer environment, user, and authorization snapshot exactly. Its
issued and expiry timestamps are timezone-aware. Future-issued, expired, non-positive, excessive,
unknown-version, malformed, or mismatched intents fail before routing. A separately injected
authorization-snapshot verifier must then confirm that the bound snapshot is current. Stale,
revoked, mismatched, or unavailable snapshots fail closed; there is no no-op verifier.
When a verifier returns request, customer, user, and snapshot bindings, all four are required and
must match the resolved context exactly.

The deterministic immutable route catalog maps an allowlisted intent code to `general_only` or one
exact read tool/version. It never reads message text and uses no keyword, regex, embedding, model
classifier, or fallback. Catalog validation proves only registration, read-only status, version,
and installed handler availability. The resolved route is not authorization; Step 21 and the
gateway still filter and reauthorize against trusted context.

## Internal HTTP ingress

Step 24 accepts only the public chat body and an opaque ERP assertion. Step 25 verifies an exact
Ed25519 compact-JWS profile locally, then resolves its one-time random reference through the fixed
mTLS ERP trust API. Authentication produces the
opaque resolver reference only; it cannot mint tenant, user, entitlement, route, tool, or snapshot
authority. The trusted resolver still supplies context and approved workflow intent, route intent
is not authorization, and authorization-snapshot verification remains mandatory.
