# Global Schema Standards

These rules are mandatory for every HR table unless a stricter module rule is documented.

## 1. Identifiers

- Domain primary keys: `uuid NOT NULL DEFAULT gen_random_uuid()`.
- Authenticated platform actors: `bigint` columns named `*_by_user_id`, with FK to `users.user_id` when local.
- Employees: UUID columns named `*_employee_id` or `employee_id`, with FK to `employees.employee_id`.
- Do not use free-text names as actor identifiers.
- External integration IDs must be explicitly named `external_*_id` and include provider/source metadata.

## 2. Required audit columns

Mutable business tables require:

| Column | Type | Rule |
|---|---|---|
| `created_at` | timestamptz | NOT NULL DEFAULT now() |
| `created_by_user_id` | bigint | NOT NULL unless system-generated |
| `updated_at` | timestamptz | NOT NULL DEFAULT now() |
| `updated_by_user_id` | bigint | Nullable only until first update |
| `row_version` | bigint | NOT NULL DEFAULT 1; optimistic concurrency |

Transaction and history tables must additionally record a correlation or request ID. Append-only tables reject UPDATE and DELETE for application roles.

## 3. Lifecycle

- `is_active` means available for future selection; it is not a deletion marker.
- Workflow records use explicit statuses and `workflow_status_history`.
- Legal/financial history is immutable after finalization.
- If soft deletion is legally allowed, use `archived_at`, `archived_by_user_id`, and `archive_reason`.
- Unique business keys must state whether archived/inactive records reserve their value.

## 4. Foreign keys

- Every ID-shaped column must have an FK or a documented external-contract reason.
- Employee deletion behavior defaults to `RESTRICT`.
- Reference data defaults to `RESTRICT`.
- `CASCADE` is permitted only for owned, non-audit children, such as a draft course module deleted with its draft course.
- `SET NULL` is permitted only when the historical row remains meaningful without the referenced record.
- Cross-record ownership must use composite unique keys plus composite FKs or validated constraint triggers.

## 5. Fixed types and codes

| Concept | Type |
|---|---|
| Currency | `char(3)` ISO 4217 |
| Country | `char(2)` ISO 3166-1 alpha-2 |
| Locale | `varchar(10)` BCP 47 |
| Hex color | `char(7)` with `^#[0-9A-Fa-f]{6}$` check |
| Monthly period code | `char(7)` formatted `YYYY-MM`; use `pay_period_id` for transactions |
| Money | `numeric(15,2)` plus currency or inherited pay-period currency |
| Percentage | `numeric(5,2)` with `0 <= value <= 100` |
| Phone | normalized E.164 text where possible |
| Email | normalized lowercase; unique using `lower(email)` or `citext` |

Country and currency codes are never stored in unbounded `char` columns.

## 6. Dates, periods, and timezones

- All event instants use `timestamptz`.
- Each branch/legal entity has an IANA timezone.
- Local work dates are derived using the applicable branch timezone, not the database server timezone.
- Effective periods require `end >= start` and non-overlap when only one record may apply.
- Monthly transactions use `pay_period_id`, not arbitrary text.
- Finalized periods are locked; corrections use reversal/amendment records.

## 7. Numeric invariants

- Amounts, counts, durations, and balances have explicit valid ranges.
- `filled_count <= headcount` and `enrolled_count <= capacity`.
- `approved_minutes <= requested_minutes`.
- Loan remaining amount is between zero and principal.
- Installments are positive.
- Ratings respect the cycle scale.
- Weighted collections are validated to total 100 where required.

## 8. Derived values and caches

- Generated columns are preferred for same-row arithmetic.
- Multi-row summaries must name an authoritative source and a refresh/reconciliation mechanism.
- A cache table records `calculated_at`, `source_watermark`, and `calculation_version`.
- AI responses must expose freshness for cached figures.

## 9. Uniqueness and case handling

- Codes are unique in their natural owner scope, such as legal entity, branch, program, requisition, or pay period.
- Employee numbers are unique per legal entity.
- Emails use case-insensitive uniqueness where uniqueness is a requirement.
- Partial unique indexes are used for one-current or one-primary rules.
- A partial index cannot replace a full history-query index.

## 10. Indexing

- Every FK used in joins or deletion checks is indexed.
- Composite indexes follow actual equality/range/order query patterns.
- Do not drop a full index merely because a partial index has the same leading column.
- Before dropping, inspect `pg_stat_user_indexes` and representative `EXPLAIN (ANALYZE, BUFFERS)` output.
- Duplicate index removal is a measured performance change, not a risk-free cleanup.

## 11. JSONB and polymorphic references

- Every JSONB field has a versioned JSON Schema, owning module, maximum size, and PII classification.
- Critical relationships are normalized rather than hidden in JSON.
- Polymorphic references such as `(item_type,item_id)` require a constraint trigger or an application contract with automated integrity reconciliation.
- Never use JSONB to bypass required foreign keys.

## 12. Security classification

Every column is classified as Public, Internal, Confidential, Restricted, or Highly Restricted.

Highly Restricted includes:

- National IDs and passports.
- Bank accounts and IBANs.
- Salary and payslips.
- Medical documents and blood type.
- Religion and protected demographic information.
- Performance, succession, disciplinary, and termination information.

Highly Restricted data requires encryption, masking, purpose-based authorization, access logging, secure backups, and redaction from application/AI traces.

## 13. Secure documents

- Raw storage paths and public URLs are prohibited for HR documents.
- Tables reference `hr_secure_files.file_id`.
- Downloads use short-lived signed access after authorization.
- Uploads require content-type validation, size limits, malware scanning, checksums, encryption, and retention policy.

## 14. State transitions

- A CHECK constraint validates allowed status values.
- A domain state machine validates allowed transitions.
- Every transition is appended to `workflow_status_history`.
- Finalized, posted, generated, published, approved, or acknowledged records cannot be silently edited.

