# PostgreSQL audit storage contract

Production composition retains only `RuntimeAuditDatabaseConfig`: writer DSNs and frozen static
identity expectations. Migration-owner credentials, migration execution, DDL, repair, and schema
changes are excluded. Startup verifies the existing Step 23 contract without changing its SQL,
digests, checksums, RLS, privileges, ownership, or triggers.

The runtime wheel uses pure `psycopg`; production hosts must provide a compatible system `libpq`.
The development-only `psycopg-binary` package is not a production `Requires-Dist` dependency.

Version `1.0.0` uses a split, append-only topology. The central control-plane database stores
only `ApplicationAuditEvent`, because application failures can occur before tenant resolution.
It never receives resolved customer or user identity. Each customer has a separately routed
audit database containing only its agent and tool events. Audit pools are independent of ERP
and knowledge pools.

The application table persists `request_id`, `stage`, `outcome`, `internal_reason`, a
storage-owned event digest, and database-generated `recorded_at`. Agent and tool tables persist
their existing exact model fields plus those two storage fields. Messages, answers, arguments,
results, context collections, evidence, citations, prompts, provider state, exceptions, opaque
handles, vectors, embeddings, and retrieved content are prohibited.

Digests use compact insertion-ordered UTF-8 JSON without a trailing newline. The top-level keys
are `domain` then `event`; event keys use an explicit frozen per-event allowlist rather than
reflection or incidental model order. Domains are
`erp-ai:application-audit:v1`, `erp-ai:agent-audit:v1`, and `erp-ai:tool-audit:v1`.
PostgreSQL timestamps are excluded. Exact redelivery is idempotent. Reusing an application or
agent `request_id`, or a tool `(request_id, tool_name, tool_version, audit_action)` slot with a
different persisted data fails generically without retry. The database compares every persisted
field; digest equality alone never classifies a delivery as an exact duplicate.

Contract descriptors bind version, fully qualified table names, ordered columns, exact
PostgreSQL type strings, identity and metadata signatures. Control digest:
`3db29998e402f7362d8f166302af100fe3d71251d98cd2ab3beecf5639707ac3`.
Customer digest: `5a2fd57e2d64e139115b74a5d7b800ec4c05f881a0fa8d98e69f96b973094c95`.

Runtime writers are non-owners without superuser, BYPASSRLS, CREATE, TEMP, UPDATE, DELETE, or
general SELECT. They receive INSERT only on the exact non-`recorded_at` columns. Owner-controlled
insertion triggers serialize each logical slot, suppress exact duplicates, and reject conflicts;
runtime writers receive no event-table SELECT or direct function execution. Customer tables force
RLS against both a transaction-local trusted customer setting and the immutable database identity.
Immutable triggers are defense in depth. Cancellation propagates; driver failures become generic
storage failures.

## HTTP pre-application failures

Step 24 uses the unchanged application event and central control database for completed failures
that occur before trusted application invocation. Bearer assertions, messages, request digests,
headers, hosts, resolver handles, and framework/provider details are excluded. Once application
execution begins, the transport emits no audit event, preventing double application auditing.
