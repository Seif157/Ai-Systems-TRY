# Repository instructions

## Scope

This repository contains the separately deployable ERP AI service. ERP business rules,
authorization, and transactional data remain behind typed ERP application APIs.

## Safety invariants

- Never give a model SQL access or database credentials.
- Treat identity, customer, employee, role, legal-entity, and entitlement values as trusted
  server-side context. Never accept them from public request bodies or model output.
- Register only licensed, enabled, and authorized module capabilities.
- Keep release-one tools read-only. Do not add commands without an approved design covering
  preview, confirmation, authorization, idempotency, and auditing.
- Use RAG only for approved policies, manuals, procedures, and FAQs—not transactional ERP rows.
- Do not log secrets, credentials, tokens, or restricted ERP values.

## Development

- Use Python 3.12 or newer within the range declared in `pyproject.toml`.
- Run `uv sync --locked --dev --python 3.12`, `uv run pytest`, `uv run ruff check .`,
  `uv run ruff format --check .`, and `uv run mypy src` before handing off changes.
- Keep public contracts strict: reject unknown fields and add negative authorization tests.
- Do not add empty capability directories; create a capability only with its implementation.
- PostgreSQL integration tests are opt-in locally: start `docker-compose.postgres-test.yml`, set
  `ERP_AI_TEST_ADMIN_DSN` to that synthetic service, set `ERP_AI_REQUIRE_POSTGRES_TESTS=1`, and run
  `uv run pytest -m postgres --no-cov` for the targeted database suite. Required mode must never
  skip; the full suite remains the coverage gate.
- Never derive a knowledge DSN/database name from customer input or log connection details. Run
  packaged migrations only through the explicit administrative boundary, never service startup.
