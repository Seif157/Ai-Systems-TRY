<!-- Module: AccountingSalary | Domain: HR | Split from DATABASE_SCHEMA.md -->

> **Canonical V2 note:** Apply [global standards](../02_GLOBAL_SCHEMA_STANDARDS.md) and this subdomain's final rules in [canonical module corrections](../04_CANONICAL_MODULE_CORRECTIONS.md). Those rules override this generated base definition.

## AccountingSalary

### `accounting_salary`

| Column | Type | Null | Default |
|---|---|---|---|
| acc_salary_id 🔑 | uuid | no | `gen_random_uuid()` |
| cost_centre_id | uuid | no |  |
| dept_id | uuid | yes |  |
| branch_id | uuid | yes |  |
| pay_period | char(7) | no |  |
| fiscal_year | smallint | no |  |
| fiscal_month | smallint | no |  |
| currency_code | char(3) | no |  |
| gross_salary_budget | numeric(15,2) | no | `0` |
| gross_salary_actual | numeric(15,2) | no | `0` |
| net_salary_actual | numeric(15,2) | no | `0` |
| allowances_total | numeric(15,2) | no | `0` |
| deductions_total | numeric(15,2) | no | `0` |
| employer_contrib | numeric(15,2) | no | `0` |
| posting_status | varchar(20) | no | `draft` |
| gl_account_code | varchar(50) | yes |  |
| journal_ref | varchar(50) | yes |  |
| posted_date | date | yes |  |
| posted_by | varchar(200) | yes |  |
| created_by | bigint | yes |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |

- **Primary key:** acc_salary_id
- **Foreign keys:** `branch_id` → `organization_branches.branch_id` (on delete RESTRICT); `cost_centre_id` → `cost_centers.cost_centre_id` (on delete RESTRICT); `dept_id` → `branch_departments.dept_id` (on delete RESTRICT)
- **Unique:** (cost_centre_id, pay_period)
- **Indexes:** fiscal_year, fiscal_month; pay_period, cost_centre_id; posting_status; cost_centre_id, pay_period
- **Checks:** (((fiscal_month >= 1) AND (fiscal_month <= 12))); (((posting_status)::text = ANY ((ARRAY['draft'::character varying, 'pending'::character varying, 'posted'::character varying, 'reversed'::character varying])::text[])))

---
