# PostgreSQL knowledge storage deployment

Each customer environment receives a separate AI knowledge PostgreSQL database. There is no
central active-generation database and no DSN/database-name derivation from customer input. A
trusted startup configuration maps canonical customer IDs to explicit reader, publisher, and
migration DSNs. The database's singleton identity must match both the requested customer and the
selected route before any runtime access.

Local tests default to PostgreSQL 17 with `pgvector/pgvector:0.8.6-pg17-bookworm`, pinned to
`sha256:cf134a767f474095eeba57e0117be8e568e011a63f33fbf252f14c9b760f8e6f`. CI exercises exact
digest-pinned pgvector 0.8.6 images across PostgreSQL majors 15 through 18; the production read
contract requires pgvector exactly 0.8.6. The exact production PostgreSQL version within that
range, container base, libpq linkage, and package strategy remain deployment choices.
Windows development/CI uses `psycopg-binary`; a production image may use `psycopg[c]` linked to a
managed system libpq.

## Local test service

```text
docker compose -f docker-compose.postgres-test.yml up -d --wait
$env:ERP_AI_TEST_ADMIN_DSN='postgresql://postgres:synthetic_test_password@localhost:55432/postgres'
$env:ERP_AI_REQUIRE_POSTGRES_TESTS='1'
uv run pytest -m postgres --no-cov
docker compose -f docker-compose.postgres-test.yml down
```

The Compose service uses only synthetic credentials, a non-default host port, and tmpfs storage.
Integration tests recreate two fixed synthetic databases. Never point the test DSN at production or
a database containing customer data.
The dedicated Linux CI job runs the complete suite with PostgreSQL required, preserving repository
coverage enforcement while guaranteeing that PostgreSQL-marked tests cannot skip. Required mode
fails closed when the admin DSN is missing, the service is unreachable, pgvector is absent, role
provisioning is incorrect, or migration/setup fails. Developers may omit both environment variables
to run the normal suite with explicitly reported PostgreSQL skips.

## Provisioning sequence

Administrative tooling explicitly opens the migration pool after the event loop starts, calls
`run_migrations()`, calls `provision_database_identity()` exactly for the trusted route customer,
and applies `grant_runtime_roles()`. Migrations never run at application startup. They use packaged
numbered SQL, SHA-256 drift detection, an advisory transaction lock, and version checks.

Use three non-superuser roles:

- Migration owner: owns schema/tables, installs extensions, provisions identity, and grants roles.
- Publisher: reads identity/current state; inserts immutable generations/content/operations/outbox;
  updates only generation status and the active pointer.
- Reader: selects identity, active snapshot, and retrieval data only.

Runtime roles must not own tables or have `BYPASSRLS`; schema identifiers are fixed and qualified,
`search_path` is fixed to `pg_catalog`, public schema creation is revoked, and the reader has no
write, migration, rollback, activation, or outbox access. Role identifiers are trusted deployment
configuration and are quoted with Psycopg identifier composition.

DSNs are secrets: provide them through an approved secret manager, never public/model/tool input,
logs, exception messages, source control, or telemetry. Pools have explicit open/close lifecycle,
no automatic retry, and transaction-local tenant/timeout state.

Migration 0003 adds exact vector storage without an approximate index. Production embedding
profile selection, provider credentials, backfill scheduling, retention, and any future
HNSW/IVFFlat design require separate review.
