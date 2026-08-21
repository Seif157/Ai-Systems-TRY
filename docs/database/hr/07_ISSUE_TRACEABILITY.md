# Issue Traceability

## Verified report issues

| # | Issue | V2 resolution |
|---:|---|---|
| 1 | Calendar cannot support multiple countries | Replaced with legal-entity/branch-aware `work_calendars` and unique calendar days |
| 2 | Bare `char` columns | Confirmed documentation artifact; module docs now show explicit lengths and global standards prevent recurrence |
| 3 | Multiple current salary/contract rows | Existing partial unique rules retained; V2 adds temporal overlap exclusion and preserves full history indexes |
| 4 | Effective periods overlap | Exclusion constraints for salary, contract, shifts, policies, and calendars |
| 5 | Approval references unconstrained | Standardized approval contract and mandatory FK/external validation |
| 6 | Missing employee FKs | Mandatory FK rule plus module-specific employee and reviewer fixes |
| 7 | Headcount drift | Filled<=budget checks, generated vacant count, and reconciliation metadata |
| 8 | Sensitive-data protection absent | Encryption, hashes, masking, secure files, audit, retention, and AI redaction |
| 9 | Calculated totals drift | Generated same-row totals; ledger/snapshot authority; cache freshness/reconciliation |
| 10 | Payroll-run foundation absent | Product decision retained; pay periods and immutable payslip line snapshots provide reproducibility |
| 11 | Numeric validation insufficient | Global numeric invariants plus domain-specific checks |
| 12 | Actor identifiers inconsistent | Standard bigint user actor convention and user/employee link |
| 13 | Cascade deletion erases history | No-hard-delete ADR and per-domain RESTRICT/retention rules |
| 14 | No tenant boundary | Resolved by database-per-customer deployment ADR and customer-isolated surrounding infrastructure |
| 15 | Cross-record ownership not enforced | Composite ownership constraints and systematic owner validation |
| 16 | Period strings weakly validated | Canonical `pay_periods`; remaining codes are fixed `char(7)` with checks |
| 17 | Finalized periods not locked | Pay-period locks, immutable finalized records, reversal/amendment workflows |
| 18 | Duplicate indexes | Measurement-based removal; incorrect assumption that full indexes are covered by partial indexes is explicitly rejected |

## Additional gaps resolved in V2

| Gap | Resolution |
|---|---|
| Schema migrations may differ from live DB | Mandatory catalog-to-migration comparison before implementation |
| Module licensing absent | `erp_module_installations` and four-layer entitlement enforcement |
| User-to-employee identity ambiguous | `user_employee_links` |
| Leave balance duplicates | Unique balance key and authoritative append-only leave ledger |
| Leave policy history/jurisdiction absent | Versioned, effective-dated, legal-entity/country-aware policies |
| Leave entitlement duplicated in grades/policies | Leave policy declared authoritative; grade fields deprecated |
| Workflow history missing | Append-only `workflow_status_history` |
| Recruitment stage history missing | `rec_application_stage_history` and ownership validation |
| Attendance cannot support split shifts/raw events | Raw punches plus shift-level daily summaries |
| Branch timezone not explicit | Legal entity/branch/shift/calendar timezone requirements |
| Files stored as paths/URLs | `hr_secure_files` with signed access, scanning, encryption, checksum, retention |
| JSONB/polymorphic integrity unspecified | Versioned JSON Schemas and constraint/application reconciliation |
| Case-sensitive email uniqueness | Scoped lowercase/citext rules |
| Soft deletion semantics unclear | Activation, archival, anonymization, and immutable-history rules separated |
| AI could access raw schema/data | Allowlisted tools, no unrestricted SQL, RAG/data separation |
| AI actions could duplicate or bypass approval | Confirmation, idempotency, command execution, approval, audit |
| RAG could leak customer/role data | Strict customer/module/legal-entity/role/effective-date metadata filters |

