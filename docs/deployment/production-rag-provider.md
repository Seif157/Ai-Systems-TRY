# Deploying the production RAG provider

Provision each customer knowledge database independently with PostgreSQL 15–18 and exactly
pgvector 0.8.6. Apply the packaged migrations through the explicit administrative
boundary, provision the immutable customer identity, publish a complete generation and
embedding set, then grant a dedicated runtime role only the narrowly required reads.

For an existing database, the deterministic upgrade operation is: apply every missing
packaged migration in order, re-run customer identity provisioning, and re-run runtime-role
grant provisioning with the same allowlisted administrative route. These operations are
idempotent; never run them from service startup. Migration 0004 forces RLS on database
identity, and the grant operation replaces broad migration-table access with column-level
reads of only `migration_name` and `sha256`.

Supply an immutable route catalog from trusted server configuration. Every route requires
an exact database name and identity, a secret reader DSN, exact reader role, contract
version/digest, embedding model/revision/dimension, pool bounds, and timeouts. Never place
migration or publisher credentials in runtime configuration, `.env.example`, or the runtime
bundle. Never derive any route value from a request.

Startup is fail-closed and must complete contract verification for every configured route.
Monitor generic availability and latency without recording queries, vectors, chunks,
citations, DSNs, identities, or provider exceptions. Shutdown closes reader pools in reverse
order. There are no retries or fallback routes.

Before production, approve the embedding provider's privacy and data-handling terms and
complete customer-document quality evaluation. Define backup, retention, legal-hold,
deletion, source-governance, publication, re-embedding, key rotation, capacity, and incident
procedures. Synthetic integration success is not production approval.

The pinned CI compatibility matrix exercises PostgreSQL 15, 16, 17, and 18 with exact
digest-pinned pgvector 0.8.6 images. A release must still certify its production operating
system, TLS, backup/restore, capacity, and extension packaging independently.
