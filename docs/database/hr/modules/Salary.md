<!-- Module: Salary | Domain: HR | Split from DATABASE_SCHEMA.md -->

> **Canonical V2 note:** Apply [global standards](../02_GLOBAL_SCHEMA_STANDARDS.md) and this subdomain's final rules in [canonical module corrections](../04_CANONICAL_MODULE_CORRECTIONS.md). Those rules override this generated base definition.

## Salary

### `salary`

| Column | Type | Null | Default |
|---|---|---|---|
| salary_id 🔑 | uuid | no | `gen_random_uuid()` |
| employee_id | uuid | no |  |
| job_grade_id | uuid | yes |  |
| cost_centre_id | uuid | yes |  |
| basic_salary | numeric(15,2) | no | `0` |
| housing_allowance | numeric(15,2) | no | `0` |
| transport_allowance | numeric(15,2) | no | `0` |
| food_allowance | numeric(15,2) | no | `0` |
| mobile_allowance | numeric(15,2) | no | `0` |
| other_allowance | numeric(15,2) | no | `0` |
| gross_salary | numeric(15,2) | no |  |
| income_tax_pct | numeric(5,2) | no | `0` |
| social_insurance_pct | numeric(5,2) | no | `0` |
| other_deduction | numeric(15,2) | no | `0` |
| net_salary | numeric(15,2) | no | `0` |
| currency_code | varchar(3) | no | `EGP` |
| pay_frequency | varchar(20) | no | `monthly` |
| pay_method | varchar(20) | no | `bank_transfer` |
| bank_name | varchar(100) | yes |  |
| bank_account | varchar(50) | yes |  |
| bank_iban | varchar(50) | yes |  |
| effective_date | date | no |  |
| end_date | date | yes |  |
| change_reason | varchar(30) | yes |  |
| change_type | varchar(20) | yes |  |
| approval_status | varchar(20) | no | `pending_approval` |
| approved_by | varchar(255) | yes |  |
| approved_date | date | yes |  |
| is_current | boolean | no | `false` |
| created_by | bigint | yes |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |

- **Primary key:** salary_id
- **Foreign keys:** `cost_centre_id` → `cost_centers.cost_centre_id` (on delete SET NULL); `employee_id` → `employees.employee_id` (on delete RESTRICT); `job_grade_id` → `job_grades.job_grade_id` (on delete SET NULL)
- **Indexes:** cost_centre_id; effective_date; employee_id; employee_id, is_current; employee_id
- **Checks:** (((approval_status)::text = ANY ((ARRAY['pending_approval'::character varying, 'approved'::character varying, 'rejected'::character varying])::text[]))); ((basic_salary >= (0)::numeric)); (((change_reason IS NULL) OR ((change_reason)::text = ANY ((ARRAY['hire'::character varying, 'promotion'::character varying, 'annual_review'::character varying, 'correction'::character varying, 'restructure'::character varying, 'market_adjustment'::character varying])::text[])))); (((change_type IS NULL) OR ((change_type)::text = ANY ((ARRAY['increase'::character varying, 'decrease'::character varying, 'correction'::character varying])::text[])))); (((end_date IS NULL) OR (end_date >= effective_date))); (((pay_frequency)::text = ANY ((ARRAY['weekly'::character varying, 'bi_weekly'::character varying, 'semi_monthly'::character varying, 'monthly'::character varying])::text[]))); (((pay_method)::text = ANY ((ARRAY['bank_transfer'::character varying, 'cash'::character varying, 'cheque'::character varying, 'wallet'::character varying])::text[])))

---
