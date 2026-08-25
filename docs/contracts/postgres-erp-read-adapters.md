# PostgreSQL structured ERP read adapters

The Step 19 adapters implement only the existing `get_my_employee_profile`,
`get_my_leave_balances`, `list_my_leave_requests`, and `get_my_leave_request` provider protocols.
They do not add public tools or change public result schemas.

## Routing and lifecycle

Trusted startup configuration maps each `customer_environment_id` to one exact read-only DSN and
expected database name. Routes are immutable, database names are never derived from customer input,
and ERP pools are separate from knowledge pools. Startup and shutdown are explicit; unknown routes,
connection failures, and schema drift fail generically. PostgreSQL 15 through 18 is supported.

DSNs and cursor keys use repr-safe secret fields and must come from a production secret manager.
There is no default route, default cursor key, dynamic onboarding, retry, or public configuration.

## Reader and contract verification

Business SQL targets only the five `ai_read` views specified in
`docs/database/hr/05A_STRUCTURED_AI_READ_CONTRACT.md`. Startup checks configured database identity,
contract SemVer/digest, exact ordered view signatures, safe view ownership, reader role attributes,
approved view SELECT grants, and absence of direct base-table grants. The ERP owner separately runs
the privileged deployment certification for base columns, nullability, composite ownership FKs,
immutability, view definitions, and grants.

Every provider operation uses a read-only repeatable-read transaction plus bounded statement, lock,
and idle-in-transaction timeouts. SQL identifiers are static and values are parameters. There are no
writes, DDL, stored procedures, temporary tables, `SELECT *`, dynamic schemas, or session-global
customer state. Cancellation propagates and operations are not retried.

## Provider behavior

Profile queries filter trusted employee and direct legal-entity scope in SQL and return only the
view's canonical display fields. The adapter does not concatenate names, use legacy `updated_at`, or
retrieve unrelated personal data.

Balances filter ownership in SQL and return stored Decimal values—including negative
`available_days`—without arithmetic. Listing applies status/date filters in SQL and uses
`submitted_at DESC, request_id ASC` keyset ordering with `limit + 1`. Detail and safe history load in
one transaction; history orders by `changed_at ASC, history_id ASC`. No notes, comments,
attachments, actors, audit metadata, or unrelated employees are selected.

## Cursor contract and limitations

The list cursor is compact base64url JSON plus HMAC-SHA256. It is versioned, has a short fixed TTL,
supports an active signing key and previous verification-only keys, and is limited to 512
characters. It binds keyed customer, employee, and authorization-snapshot identities plus legal
scope, filters, page size, snapshot ceiling, and the last `(submitted_at, request_id)` position. Raw
trusted identifiers and authorization collections are absent. Signature comparison is constant
time. Malformed, expired, tampered, unknown-key, or rebound cursors fail generically and are never
logged or audited.

The first page captures a database-clock ceiling. Later pages exclude normally submitted newer
rows. This is not a persistent PostgreSQL MVCC snapshot: concurrent changes or backdated inserts can
still cause skips. Persistent snapshots, retry, timeout recovery, and circuit breakers remain
deferred.

## Privacy and operations

Driver details, SQL, parameters, rows, DSNs, database names, employee/request IDs, cursors, and
provider exceptions must not enter logs or public errors. Provider records remain strict and PII is
excluded from repr-oriented configuration. The existing tool gateway remains the exactly-once audit
boundary; providers add no audit stream.

The synthetic environment is `docker-compose.erp-postgres-test.yml`. It creates no production
migration and uses only fictional rows. Start it explicitly, point `ERP_AI_TEST_ADMIN_DSN` at the
synthetic administrator, set `ERP_AI_REQUIRE_POSTGRES_TESTS=1`, and run the PostgreSQL-marked suite.
