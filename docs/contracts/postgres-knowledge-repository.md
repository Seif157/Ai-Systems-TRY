# PostgreSQL knowledge repository contract

The Psycopg 3 adapter implements atomic Step 12 publication in a separate database for each
customer. Static trusted routing selects a privilege-specific `AsyncConnectionPool`; the adapter
never builds a DSN or database name from a customer ID. Every transaction begins, installs the
customer through parameterized transaction-local `set_config`, applies local timeouts, and verifies
the singleton database identity before touching customer content. RLS default-denies absent or
incorrect settings and is defense in depth behind physical database routing.

Publication and rollback use SERIALIZABLE transactions without automatic retries. They lock the
active pointer, enforce compare-and-swap and idempotency, persist complete immutable content,
verify stored counts, switch status/pointer, persist the operation result, and add exactly one
outbox row. Any driver/constraint/serialization failure rolls back and becomes a generic adapter
error; cancellation propagates. Historical documents/chunks cannot be updated or deleted, and no
garbage collection exists.

`document_version` is bounded text constrained to exact canonical `MAJOR.MINOR.PATCH` syntax.
Publication and retrieval preserve it byte-for-byte: `1.2.3`, `1.9.0`, and `12.34.567` remain
distinct. PostgreSQL string ordering is never used for supersession; ingestion owns semantic
version comparison.

Snapshot and lexical retrieval use read-only REPEATABLE READ transactions. One active generation
ID is acquired and reused through the complete query. Fixed, schema-qualified SQL applies customer,
namespace, source ownership, module, permission, purpose, legal-entity, effective-date, and
classification predicates before ranking. `plainto_tsquery('simple', parameter)` prevents model
access to PostgreSQL query syntax. A GIN-indexed generated `tsvector` includes only title, section,
and content. Rank uses the monotonic `rank / (1 + rank)` transform and orders descending with chunk
ID ascending as the stable tie-breaker. Arabic/English matching has no stemming assumptions;
morphology, synonyms, typo tolerance, embeddings, and vector ranking are deferred.

The existing HR handler still validates every returned record. Database errors and audits exclude
SQL, query text, content, paths, DSNs, hosts, users, database names, driver details, and trusted
authorization collections. Psycopg parameter logging must remain disabled.
