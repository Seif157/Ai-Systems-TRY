# Trusted request context contract

`TrustedRequestContext` is immutable, server-owned security context. A trusted application
adapter implements `TrustedContextProvider`; `resolve_trusted_context` validates and freezes the
claims returned by that provider. Unknown or missing fields fail validation.

## Fields

| Field | Purpose |
|---|---|
| `context_version` | Contract version; currently only integer `1` is accepted |
| `request_id` | Correlation identifier for this request |
| `customer_environment_id` | Server-resolved customer environment |
| `user_id` | Authenticated ERP actor |
| `employee_id` | Optional trusted user-to-employee link |
| `roles` | Normalized role codes used by authorization policy |
| `permission_codes` | Canonical lowercase effective permission codes; dotted segments are allowed |
| `legal_entity_ids` | Legal entities within the resolved data scope |
| `enabled_modules` | Licensed and enabled ERP modules resolved upstream |
| `locale` | Authoritative actor/customer locale used by trusted policy logic |
| `timezone` | Valid IANA timezone used for authoritative business-time interpretation |
| `purpose` | Authorized request purpose |
| `issued_at` | Timezone-aware time at which the authorization context was issued |
| `authorization_snapshot_id` | Opaque identifier for the upstream authorization snapshot |

Collections are immutable tuples and sorted deterministically. Role, purpose, and module codes
retain their lowercase snake-case namespace. Permission codes use strict lowercase dotted
segments and reject whitespace or uppercase input. Duplicate values are rejected. The timezone
must resolve through `zoneinfo.ZoneInfo`.

## Trusted and public fields

Public clients and model output can provide conversational input and an optional
`preferred_response_language`. They cannot provide or override any trusted context field.
`PublicChatRequest` rejects customer, actor, employee, role, permission, legal-entity, module,
locale, timezone, purpose, or other unknown fields.

Authoritative `locale` belongs to trusted context. `preferred_response_language` is only a
presentation preference: it must never change country, legal entity, timezone, permissions,
entitlements, policy filtering, or any authorization decision.

## Safe audit projection

Application code must log `to_audit_record(context)`, not the complete context and not the result
of `context.model_dump()`. `ContextAuditRecord` contains identifiers approved for structured audit
plus an employee-linked flag and collection counts. It excludes employee ID and raw roles,
permissions, legal entities, and module codes. Sensitive context fields use `repr=False` as an
additional safeguard, but this does not make arbitrary logging safe.

## Versioning and freshness

Only `context_version=1` is supported. A future incompatible contract requires an explicit new
version and consumer handling; versions must not be silently coerced.

`issued_at` and `authorization_snapshot_id` are evidence, not freshness enforcement. They do not
prevent stale authorization by themselves. A future trusted resolver must verify snapshot status,
revocation, and acceptable age against the authoritative authorization service before use.

## Current provider limitation

The Protocol establishes a typed adapter boundary only. Python structural typing cannot prove
that an implementation is authenticated or trustworthy. Deployment wiring must supply an approved
provider; the current contract performs no authentication, network lookup, or stale-context check.
