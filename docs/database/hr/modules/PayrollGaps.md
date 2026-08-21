<!-- Module: PayrollGaps | Domain: HR | Split from DATABASE_SCHEMA.md -->

> **Canonical V2 note:** Apply [global standards](../02_GLOBAL_SCHEMA_STANDARDS.md) and this subdomain's final rules in [canonical module corrections](../04_CANONICAL_MODULE_CORRECTIONS.md). Those rules override this generated base definition.

## PayrollGaps

### `pg_bonuses`

| Column | Type | Null | Default |
|---|---|---|---|
| bonus_id 🔑 | uuid | no | `gen_random_uuid()` |
| employee_id | uuid | no |  |
| type | varchar(20) | no |  |
| amount | numeric(12,2) | no |  |
| period | varchar(7) | no |  |
| status | varchar(20) | no | `pending_approval` |
| approval_id | uuid | yes |  |
| note | varchar(255) | yes |  |
| created_by | bigint | no |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |

- **Primary key:** bonus_id
- **Indexes:** employee_id; period; status
- **Checks:** (((status)::text = ANY ((ARRAY['pending_approval'::character varying, 'approved'::character varying, 'injected'::character varying, 'rejected'::character varying])::text[]))); (((type)::text = ANY ((ARRAY['performance'::character varying, 'spot'::character varying, 'eid'::character varying, 'other'::character varying])::text[])))

### `pg_expense_claims`

| Column | Type | Null | Default |
|---|---|---|---|
| claim_id 🔑 | uuid | no | `gen_random_uuid()` |
| claim_no | varchar(30) | no |  |
| employee_id | uuid | no |  |
| category | varchar(30) | no |  |
| amount | numeric(12,2) | no |  |
| currency_code | char(3) | no | `EGP` |
| incurred_on | date | no |  |
| receipt_path | varchar(255) | yes |  |
| status | varchar(20) | no | `pending_approval` |
| approval_id | uuid | yes |  |
| payout_method | varchar(15) | no | `payroll` |
| created_by | bigint | no |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |

- **Primary key:** claim_id
- **Unique:** (claim_no)
- **Indexes:** employee_id; status; claim_no
- **Checks:** (((category)::text = ANY ((ARRAY['travel'::character varying, 'meals'::character varying, 'medical'::character varying, 'transport'::character varying, 'other'::character varying])::text[]))); (((payout_method)::text = ANY ((ARRAY['payroll'::character varying, 'petty_cash'::character varying])::text[]))); (((status)::text = ANY ((ARRAY['pending_approval'::character varying, 'approved'::character varying, 'rejected'::character varying, 'paid'::character varying])::text[])))

### `pg_loan_schedules`

| Column | Type | Null | Default |
|---|---|---|---|
| schedule_id 🔑 | uuid | no | `gen_random_uuid()` |
| loan_id | uuid | no |  |
| period | varchar(7) | no |  |
| amount | numeric(12,2) | no |  |
| status | varchar(15) | no | `scheduled` |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |

- **Primary key:** schedule_id
- **Foreign keys:** `loan_id` → `pg_loans.loan_id` (on delete RESTRICT)
- **Indexes:** loan_id; period; status
- **Checks:** (((status)::text = ANY ((ARRAY['scheduled'::character varying, 'deducted'::character varying, 'skipped'::character varying])::text[])))

### `pg_loans`

| Column | Type | Null | Default |
|---|---|---|---|
| loan_id 🔑 | uuid | no | `gen_random_uuid()` |
| loan_no | varchar(30) | no |  |
| employee_id | uuid | no |  |
| type | varchar(15) | no |  |
| principal_amount | numeric(12,2) | no |  |
| installments_count | integer | no |  |
| installment_amount | numeric(12,2) | no |  |
| remaining_amount | numeric(12,2) | no |  |
| reason | varchar(255) | yes |  |
| status | varchar(20) | no | `pending_approval` |
| approval_id | uuid | yes |  |
| start_period | varchar(7) | no |  |
| created_by | bigint | no |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |

- **Primary key:** loan_id
- **Unique:** (loan_no)
- **Indexes:** employee_id; status; loan_no
- **Checks:** (((status)::text = ANY ((ARRAY['pending_approval'::character varying, 'approved'::character varying, 'active'::character varying, 'settled'::character varying, 'rejected'::character varying, 'cancelled'::character varying])::text[]))); (((type)::text = ANY ((ARRAY['loan'::character varying, 'advance'::character varying])::text[])))

### `pg_payroll_injections`

| Column | Type | Null | Default |
|---|---|---|---|
| injection_id 🔑 | uuid | no | `gen_random_uuid()` |
| source_type | varchar(20) | no |  |
| source_id | uuid | no |  |
| employee_id | uuid | no |  |
| period | varchar(7) | no |  |
| direction | varchar(10) | no |  |
| amount | numeric(12,2) | no |  |
| status | varchar(15) | no | `pending` |
| synced_at | timestamptz | yes |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |

- **Primary key:** injection_id
- **Unique:** (source_type, source_id, period)
- **Indexes:** employee_id; period; status; source_type, source_id, period
- **Checks:** (((direction)::text = ANY ((ARRAY['deduction'::character varying, 'addition'::character varying])::text[]))); (((source_type)::text = ANY ((ARRAY['loan'::character varying, 'expense'::character varying, 'bonus'::character varying])::text[]))); (((status)::text = ANY ((ARRAY['pending'::character varying, 'included'::character varying, 'sent'::character varying])::text[])))

---
