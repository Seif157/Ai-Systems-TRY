<!-- Module: BranchDepartment | Domain: HR | Split from DATABASE_SCHEMA.md -->

> **Canonical V2 note:** Apply [global standards](../02_GLOBAL_SCHEMA_STANDARDS.md) and this subdomain's final rules in [canonical module corrections](../04_CANONICAL_MODULE_CORRECTIONS.md). Those rules override this generated base definition.

## BranchDepartment

### `branch_departments`

| Column | Type | Null | Default |
|---|---|---|---|
| dept_id 🔑 | uuid | no | `gen_random_uuid()` |
| branch_id | uuid | no |  |
| parent_dept_id | uuid | yes |  |
| dept_code | varchar(20) | no |  |
| dept_name | varchar(200) | no |  |
| dept_name_local | varchar(200) | yes |  |
| dept_type | varchar(30) | no |  |
| manager_emp_id | uuid | yes |  |
| cost_centre_id | uuid | yes |  |
| headcount_budget | integer | no | `0` |
| headcount_filled | integer | no | `0` |
| effective_date | date | yes |  |
| is_active | boolean | no | `true` |
| created_by | bigint | yes |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |

- **Primary key:** dept_id
- **Foreign keys:** `branch_id` → `organization_branches.branch_id` (on delete RESTRICT); `parent_dept_id` → `branch_departments.dept_id` (on delete RESTRICT)
- **Unique:** (dept_code)
- **Indexes:** dept_code; branch_id; cost_centre_id; is_active; parent_dept_id; dept_type
- **Checks:** ((headcount_budget >= 0)); ((headcount_filled >= 0)); (((dept_type)::text = ANY ((ARRAY['operational'::character varying, 'administrative'::character varying, 'support'::character varying, 'technical'::character varying, 'management'::character varying])::text[])))

---
