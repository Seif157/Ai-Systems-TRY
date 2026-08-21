# Architecture Decisions

## ADR-001 — Database isolation

Each customer receives a separate PostgreSQL database. No shared customer rows are permitted. Therefore:

- HR tables do not require `tenant_id`.
- Each database uses a customer-specific database role and secret.
- Cross-customer connection reuse is forbidden.
- Database names, credentials, backups, object-storage prefixes, caches, queues, search indexes, and vector collections must be customer-scoped.
- Automated tests must attempt and fail cross-customer access.
- Restores must never target another customer's environment.

If the product later moves to a shared database, this specification must be revised before onboarding the first shared tenant. Adding only a `tenant_id` column will not be sufficient; unique constraints, foreign keys, indexes, RLS, caches, files, and AI metadata must also be tenant-scoped.

## ADR-002 — Legal entities inside one customer

A customer database may contain multiple legal entities, countries, branches, and currencies. `legal_entities` is the organization root. Branches, calendars, policies, payroll periods, and accounting postings must link to the appropriate legal entity.

## ADR-003 — Module licensing

The application is one ERP product with independently licensed capabilities. `erp_module_installations` records which modules are installed and enabled in this customer database.

Enforcement is required at four layers:

1. Frontend navigation and feature flags.
2. Laravel route/application-service authorization.
3. AI capability and tool registration.
4. Database role or schema permissions where modules are separately deployed.

Hidden navigation is not authorization. Disabled module APIs and AI tools must return a deterministic entitlement error before reading data.

## ADR-004 — Domain boundaries

| Capability | Owns |
|---|---|
| HR Core | Employee identity, assignments, contracts, organization, documents, employment operations |
| Leave | Leave types, policies, ledger, balances, requests, work calendars |
| Time & Attendance | Shifts, assignments, raw punches, daily records, summaries, overtime |
| Compensation | Compensation packages, components, payment methods, effective history |
| Payroll & Payslip | Pay periods, adjustments, loans, immutable payslip snapshots and accounting handoff |
| Recruitment | Candidates, requisitions, pipelines, interviews, offers, hiring conversion |
| Performance | Cycles, goals, KPIs, appraisals, feedback, calibration, improvement plans |
| Talent | Career paths, promotion, succession, nominations |
| Learning | Courses, programs, sessions, enrollments, skills, certifications |
| Employee Services | Service-request types, requests, templates, generated letters |

Cross-domain writes must use application services or domain events. A module must not update another module's tables directly.

## ADR-005 — External platform contracts

The HR database requires these platform-owned records:

- `users(user_id bigint)` for authentication actors.
- `approval_requests(request_id uuid)` for approval workflow instances.
- A role/permission service defining employee, manager, HR specialist, payroll, recruiter, learning, performance, auditor, and administrator scopes.

Every declared reference to these contracts must be a real foreign key when the tables share the database. If they are external services, store immutable external identifiers and enforce referential validation through an outbox/inbox integration contract.

## ADR-006 — No hard deletion of HR history

- Employees, contracts, attendance, leave transactions, salary history, payslips, appraisals, offers, approvals, audit records, and access logs are never physically deleted through normal application flows.
- Reference data uses `is_active` for availability, not deletion.
- Privacy erasure uses approved anonymization or tokenization while retaining legally required financial and audit records.
- Cascade deletion is allowed only for true owned children whose deletion does not remove legal, financial, security, or workflow evidence.

## ADR-007 — Payroll history without a payroll-run aggregate

The recorded product decision not to introduce a payroll-run aggregate is retained. Historical reproducibility is instead provided by:

- A locked `pay_period`.
- An immutable payslip header.
- Immutable payslip line items with component codes, quantities, rates, amounts, source references, and calculation metadata.
- A document checksum and calculation-version identifier.
- Reversal/correction documents rather than updates to published payslips.

This design supports the AI question “Why did my net pay change?” without requiring a run table.

## ADR-008 — AI is an application client

The AI service does not own HR data and does not receive unrestricted database credentials. It calls allowlisted, permission-aware Laravel queries and commands. Retrieval-augmented generation is used only for approved knowledge documents.

