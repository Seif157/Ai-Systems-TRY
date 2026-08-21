<!-- Module: EmployeeContract | Domain: HR | Split from DATABASE_SCHEMA.md -->

> **Canonical V2 note:** Apply [global standards](../02_GLOBAL_SCHEMA_STANDARDS.md) and this subdomain's final rules in [canonical module corrections](../04_CANONICAL_MODULE_CORRECTIONS.md). Those rules override this generated base definition.

## EmployeeContract

### `employee_contracts`

| Column | Type | Null | Default |
|---|---|---|---|
| contract_id 🔑 | uuid | no | `gen_random_uuid()` |
| employee_id | uuid | no |  |
| contract_number | varchar(20) | no |  |
| contract_type | varchar(30) | no |  |
| branch_id | uuid | yes |  |
| dept_id | uuid | yes |  |
| position_id | uuid | yes |  |
| job_grade_id | uuid | yes |  |
| start_date | date | no |  |
| end_date | date | yes |  |
| is_open_ended | boolean | no | `false` |
| work_location | varchar(255) | yes |  |
| work_schedule | varchar(30) | yes |  |
| weekly_hours | smallint | yes |  |
| probation_days | smallint | yes |  |
| probation_end_date | date | yes |  |
| notice_period_days | smallint | yes |  |
| notice_period_unit | varchar(10) | yes |  |
| renewal_type | varchar(30) | yes |  |
| renewal_count | smallint | no | `0` |
| contract_status | varchar(30) | no | `active` |
| special_conditions | text | yes |  |
| file_path | text | yes |  |
| is_current | boolean | no | `true` |
| approved_by | bigint | yes |  |
| approved_date | date | yes |  |
| created_by | bigint | no |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |

- **Primary key:** contract_id
- **Foreign keys:** `branch_id` → `organization_branches.branch_id` (on delete SET NULL); `dept_id` → `branch_departments.dept_id` (on delete SET NULL); `employee_id` → `employees.employee_id` (on delete RESTRICT); `job_grade_id` → `job_grades.job_grade_id` (on delete SET NULL); `position_id` → `positions.position_id` (on delete SET NULL)
- **Unique:** (contract_number)
- **Indexes:** contract_number; employee_id; end_date; employee_id, is_current; contract_status; employee_id
- **Checks:** (((end_date IS NULL) OR (end_date > start_date))); (((contract_status)::text = ANY ((ARRAY['draft'::character varying, 'active'::character varying, 'expired'::character varying, 'terminated'::character varying, 'renewed'::character varying, 'suspended'::character varying])::text[]))); (((contract_type)::text = ANY ((ARRAY['permanent'::character varying, 'fixed_term'::character varying, 'temporary'::character varying, 'internship'::character varying, 'contract'::character varying, 'seasonal'::character varying, 'secondment'::character varying])::text[]))); (((notice_period_unit IS NULL) OR ((notice_period_unit)::text = ANY ((ARRAY['day'::character varying, 'week'::character varying, 'month'::character varying])::text[])))); (((NOT is_open_ended) OR (end_date IS NULL))); (((work_schedule IS NULL) OR ((work_schedule)::text = ANY ((ARRAY['standard'::character varying, 'shift'::character varying, 'flexible'::character varying, 'remote'::character varying, 'hybrid'::character varying])::text[]))))

---
