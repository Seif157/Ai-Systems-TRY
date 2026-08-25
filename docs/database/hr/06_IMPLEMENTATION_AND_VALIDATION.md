# Implementation and Validation Plan

This package is documentation. Developers must translate it into new Laravel migrations; previously applied migrations must never be edited in place.

## Stage 0 — Confirm reality

1. Compare all Laravel migrations with the live PostgreSQL catalogs.
2. Confirm applied migration versions.
3. Export constraint, FK, index, trigger, generated-column, extension, and privilege inventories.
4. Create and restore a tested backup.
5. Run on a production-sized non-production clone.

## Stage 1 — Preflight data reports

Run and retain reports for:

- Orphaned employee, user, approval, manager, grade, position, program, cohort, stage, and document references.
- Duplicate leave balances.
- Multiple current salary/contract/payment-method rows.
- Overlapping contracts, salaries, shifts, policies, and calendars.
- Cross-program cohorts and cross-requisition stages.
- Invalid period strings and country/currency codes.
- Negative amounts/counts, percentages outside 0–100, and filled counts above capacity.
- Statuses inconsistent with decision timestamps or actors.
- Files that are missing, public, unscanned, or have invalid checksums.
- Derived totals that do not reconcile with source rows.

Every repair requires an approved, repeatable data migration. Never silently discard invalid HR history.

## Stage 2 — Foundation

1. Create legal entities and map all branches.
2. Create module installations and register enabled HR capabilities.
3. Create secure files, audit events, workflow history, pay periods, work calendars, user/employee links, and command executions.
4. Establish user and approval external-contract FKs/integration validation.
5. Configure encryption and key management before migrating plaintext sensitive values.

## Stage 3 — Identity and referential integrity

1. Standardize actor columns on bigint user IDs.
2. Add missing employee and non-employee FKs after orphan cleanup.
3. Add composite ownership constraints.
4. Replace unsafe cascade deletes according to the retention matrix.
5. Add case-insensitive/scoped unique constraints.

Use `NOT VALID` then `VALIDATE CONSTRAINT` where PostgreSQL supports it and where online migration risk justifies the pattern.

## Stage 4 — Temporal and numeric integrity

1. Add valid-range checks.
2. Add one-current/one-primary constraints.
3. Add effective-period exclusion constraints after overlap repair.
4. Introduce pay periods and replace period strings.
5. Add finalization locks and reversal workflows.

## Stage 5 — Domain correctness

Recommended order:

1. HR Core and organization.
2. Leave ledger, policies, calendars, balances, and requests.
3. Raw attendance punches, shifts, and summaries.
4. Compensation components, secure payment methods, and payslip snapshots.
5. Employee services.
6. Recruitment.
7. Learning.
8. Performance and Talent.

## Stage 6 — Files and privacy

1. Move paths/URLs into secure file objects.
2. Verify every object checksum and malware-scan state.
3. Encrypt Restricted columns and backfill keyed hashes.
4. Replace plaintext application logging.
5. Enforce retention, legal hold, anonymization, and access auditing.

## Stage 7 — Index verification

- Drop only exact or demonstrably redundant indexes.
- Retain full history indexes even when partial current indexes exist.
- Use production-like queries and `EXPLAIN (ANALYZE,BUFFERS)`.
- Measure write cost and read latency before and after each index change.

## Stage 8 — AI integration

1. Implement allowlisted read tools for HR Core + Leave.
2. Build approved policy RAG with strict metadata.
3. Add authorization, trace redaction, audit, and idempotency.
4. Run synthetic and adversarial evaluation suites.
5. Add a write tool only after read-only release criteria pass.

## Database acceptance tests

The ERP database owner, not this AI repository, migrates and certifies the structured-read columns,
constraints, roles, and `ai_read` views defined in `05A_STRUCTURED_AI_READ_CONTRACT.md`. Deployment
must run the documented privileged certification before enabling a customer route. Runtime AI
credentials are deliberately unable to perform privileged base-table inspection.

At minimum, automated tests must prove:

- All documented FKs exist and reject invalid references.
- Cross-owner references fail.
- Invalid status, date, amount, rating, and count combinations fail.
- Current/effective-period collisions fail.
- Historical and audit rows cannot be deleted or edited by application roles.
- Leave ledger remains idempotent and balances reconcile.
- Published payslip lines reconcile with header totals and are immutable.
- Work calendar resolution chooses the correct legal entity/branch/date.
- Secure files cannot be read without authorization and a clean scan.
- Finalized records require reversal/amendment rather than updates.

## Application acceptance tests

- Every write uses a transaction and optimistic concurrency.
- Every workflow transition creates history and audit evidence.
- Authorization is tested by employee, manager, HR, payroll, recruiter, learning, performance, auditor, and administrator roles.
- Disabled modules return entitlement errors from UI, API, and AI.
- Background jobs use customer-specific database connections and storage/index scopes.

## Release gates

- Zero orphan records after migration.
- Zero unapproved overlaps or duplicate current records.
- Zero plaintext Highly Restricted values in logs or AI traces.
- Successful backup/restore and rollback rehearsal.
- Approved performance baseline.
- Signed security, HR, finance, and product acceptance for their domains.
- Zero AI authorization/cross-customer leaks in the evaluation suite.
