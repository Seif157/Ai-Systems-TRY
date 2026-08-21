<!-- Module: EmployeeOperations | Domain: HR | Split from DATABASE_SCHEMA.md -->

> **Canonical V2 note:** Apply [global standards](../02_GLOBAL_SCHEMA_STANDARDS.md) and this subdomain's final rules in [canonical module corrections](../04_CANONICAL_MODULE_CORRECTIONS.md). Those rules override this generated base definition.

## EmployeeOperations

### `employee_operations`

| Column | Type | Null | Default |
|---|---|---|---|
| operation_id 🔑 | uuid | no | `gen_random_uuid()` |
| employee_id | uuid | no |  |
| operation_type | varchar(20) | no |  |
| operation_status | varchar(20) | no | `executed` |
| effective_date | date | no |  |
| reason | text | yes |  |
| changes_applied | jsonb | yes |  |
| warnings | jsonb | yes |  |
| next_steps | jsonb | yes |  |
| final_settlement | jsonb | yes |  |
| origin_branch_id | uuid | yes |  |
| origin_dept_id | uuid | yes |  |
| origin_position_id | uuid | yes |  |
| origin_job_grade_id | uuid | yes |  |
| origin_cost_centre_id | uuid | yes |  |
| origin_manager_id | uuid | yes |  |
| target_branch_id | uuid | yes |  |
| target_dept_id | uuid | yes |  |
| target_position_id | uuid | yes |  |
| target_job_grade_id | uuid | yes |  |
| target_cost_centre_id | uuid | yes |  |
| target_manager_id | uuid | yes |  |
| termination_type | varchar(30) | yes |  |
| termination_reason | text | yes |  |
| new_basic_salary | numeric(15,2) | yes |  |
| executed_by | bigint | yes |  |
| executed_at | timestamptz | yes |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| notice_period_served | boolean | yes |  |
| before_state | jsonb | yes |  |
| reversed_by | bigint | yes |  |
| reversed_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |

- **Primary key:** operation_id
- **Foreign keys:** `employee_id` → `employees.employee_id` (on delete RESTRICT)
- **Indexes:** effective_date DESC; employee_id; executed_at DESC; operation_type
- **Checks:** (((termination_type IS NULL) OR ((termination_type)::text = ANY ((ARRAY['resignation'::character varying, 'termination'::character varying, 'retirement'::character varying, 'contract_end'::character varying, 'death'::character varying, 'redundancy'::character varying])::text[])))); (((operation_status)::text = ANY ((ARRAY['preview'::character varying, 'executed'::character varying, 'failed'::character varying, 'reversed'::character varying])::text[]))); (((operation_type)::text = ANY ((ARRAY['transfer'::character varying, 'promotion'::character varying, 'termination'::character varying])::text[])))

### `eo_settlement_access_log`

| Column | Type | Null | Default |
|---|---|---|---|
| log_id 🔑 | uuid | no | `gen_random_uuid()` |
| settlement_id | uuid | no |  |
| accessed_by | bigint | no |  |
| action | varchar(15) | no |  |
| ip | varchar(45) | yes |  |
| accessed_at | timestamptz | no |  |

- **Primary key:** log_id
- **Foreign keys:** `settlement_id` → `eo_settlement_documents.settlement_id` (on delete CASCADE)
- **Indexes:** settlement_id
- **Checks:** (((action)::text = ANY ((ARRAY['viewed'::character varying, 'downloaded'::character varying])::text[])))

### `eo_settlement_documents`

| Column | Type | Null | Default |
|---|---|---|---|
| settlement_id 🔑 | uuid | no | `gen_random_uuid()` |
| employee_id | uuid | no |  |
| pdf_path | varchar(255) | yes |  |
| gratuity | numeric(12,2) | yes |  |
| unused_leave | numeric(12,2) | yes |  |
| pro_rata_salary | numeric(12,2) | yes |  |
| total | numeric(12,2) | yes |  |
| generated_at | timestamptz | no |  |
| created_by | bigint | no |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |

- **Primary key:** settlement_id
- **Indexes:** employee_id

---
