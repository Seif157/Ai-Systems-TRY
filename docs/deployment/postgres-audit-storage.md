# Deploying PostgreSQL audit storage

Provision one central control audit database and one separate audit database per customer.
Configure routes at startup; never derive database names or DSNs from requests. Use distinct
migration-owner and runtime-writer credentials. Run the packaged, checksum-pinned migrations
through the administrative boundary, provision the immutable database identity, grant the fixed
writer template, and only then open runtime pools. Startup verifies PostgreSQL 15–18, database
name/kind/identity, customer binding, contract metadata, relational signatures, and role safety.

The ordered `1.0.0` migration allowlists are:

- Control: `0001_control_audit.sql`, SHA-256
  `5647c7a1dca311a393946282a2824f532bc9cb303a571f2c1065f23b169a98d4`.
- Customer: `0001_customer_audit.sql`, SHA-256
  `e00021111de6783cf0d4238ae7f4fb74ba44520dfa5eb83a38a8f32d8f778f71`.

Checksum or relational-contract drift blocks migration/startup. Migration owners and runtime
writers use separate credentials; audit pools are never shared with ERP or knowledge storage.

For synthetic testing, start `docker-compose.audit-test.yml`, set
`ERP_AI_TEST_AUDIT_ADMIN_DSN=postgresql://postgres:synthetic_audit_admin@127.0.0.1:55433/postgres`
and `ERP_AI_REQUIRE_AUDIT_POSTGRES_TESTS=1`, then run
`uv run python -m pytest -m postgres tests/integration/test_postgres_audit_storage.py --no-cov`.
Do not use these credentials outside the disposable test stack.

CI runs this required, non-skipping suite separately on digest-pinned PostgreSQL 15, 16, 17,
and 18 images. The local Compose image can be selected only by the server-controlled
`ERP_AI_AUDIT_POSTGRES_IMAGE` environment variable; it is never public or model-controlled.

Backups, retention schedules, legal holds, deletion governance, audit readers, SIEM delivery,
monitoring, and disaster-recovery objectives remain deployment decisions for a later step.
