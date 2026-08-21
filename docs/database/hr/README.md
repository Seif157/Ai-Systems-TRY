# HR Database Schema V2.0 — Production-Ready Design Specification

**Status:** Canonical implementation specification  
**Deployment model:** One PostgreSQL database per customer  
**Source:** Rebuilt from the supplied 85-table HR documentation and verified issue report  
**Deliverable type:** Schema documentation, not executable migrations

## Purpose

This package defines the target HR database design for implementation by the ERP backend team and safe consumption by the ERP AI service. It keeps the original 23 HR subdomains and 85 documented tables, corrects the verified defects, and adds the missing governance, security, history, entitlement, and AI-access requirements.

Because each customer receives an isolated database, tenant columns are intentionally not repeated on every HR table. Customer isolation must instead be guaranteed by provisioning, credentials, networking, backups, storage prefixes, vector indexes, and deployment automation. A database must never contain records from two customers.

## Canonical precedence

When documents differ, apply them in this order:

1. `02_GLOBAL_SCHEMA_STANDARDS.md`
2. `03_FOUNDATION_AND_CONTROL_TABLES.md`
3. `04_CANONICAL_MODULE_CORRECTIONS.md`
4. `04A_NEW_DOMAIN_TABLE_DEFINITIONS.md`
5. Files in `modules/`

The files under `modules/` preserve the complete table inventory and column reference. The canonical documents above override types, foreign keys, uniqueness, lifecycle behavior, security classification, and constraints where specified.

## Package contents

| File | Purpose |
|---|---|
| `01_ARCHITECTURE_DECISIONS.md` | Deployment, module licensing, boundaries, ownership, and service integration |
| `02_GLOBAL_SCHEMA_STANDARDS.md` | Mandatory rules applied to every HR table |
| `03_FOUNDATION_AND_CONTROL_TABLES.md` | New shared tables required by the corrected design |
| `04_CANONICAL_MODULE_CORRECTIONS.md` | Final corrections for all HR subdomains |
| `04A_NEW_DOMAIN_TABLE_DEFINITIONS.md` | Complete definitions of newly required domain tables |
| `05_AI_ACCESS_AND_RAG_CONTRACT.md` | Safe database tools, RAG separation, permissions, and AI auditing |
| `06_IMPLEMENTATION_AND_VALIDATION.md` | Migration order, preflight checks, acceptance tests, and release gates |
| `07_ISSUE_TRACEABILITY.md` | Mapping from every verified and newly discovered issue to its resolution |
| `modules/` | Complete original 23-subdomain/85-table structural reference with corrected fixed-length types |

## Major improvements in V2

- Database-per-customer isolation is explicit and testable.
- Module installation and licensing are represented independently from UI visibility.
- User identity and employee identity are mapped consistently.
- All actor identifiers use `bigint` user IDs; employee references use UUIDs.
- Sensitive files use secure object records instead of ungoverned paths.
- Audit and workflow histories are append-only.
- Effective-dated records cannot overlap where overlap is invalid.
- Leave balances have one authoritative ledger and unique cached balances.
- Leave policies are versioned, jurisdiction-aware, and effective-dated.
- Calendars support legal entity, branch, country, and timezone differences.
- Attendance supports raw punches, split shifts, and daily summaries.
- Payslips contain immutable, reproducible line snapshots without requiring a payroll-run aggregate.
- Cross-record ownership is enforced, not merely implied by independent foreign keys.
- AI receives allowlisted tools and views rather than unrestricted SQL access.
- RAG contains policies and manuals, never employee transactional data or unfiltered PII.

## Implementation readiness gates

This design is ready to implement when all of the following are true:

- The real Laravel migrations have been mapped to this specification.
- Existing data has passed orphan, overlap, duplicate, and invalid-value preflight reports.
- Every mandatory constraint has an automated database integration test.
- Encryption keys, secure object storage, and backup restoration have been tested.
- HR roles and user-to-employee mappings are defined.
- Module licensing is enforced in the UI, API, AI capability registry, and database credentials.
- The AI security and evaluation suites in `05_AI_ACCESS_AND_RAG_CONTRACT.md` pass with zero authorization leaks.
