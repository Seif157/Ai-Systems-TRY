<!-- Module: Position | Domain: HR | Split from DATABASE_SCHEMA.md -->

> **Canonical V2 note:** Apply [global standards](../02_GLOBAL_SCHEMA_STANDARDS.md) and this subdomain's final rules in [canonical module corrections](../04_CANONICAL_MODULE_CORRECTIONS.md). Those rules override this generated base definition.

## Position

### `positions`

| Column | Type | Null | Default |
|---|---|---|---|
| position_id 🔑 | uuid | no | `gen_random_uuid()` |
| position_code | varchar(30) | no |  |
| position_title | varchar(200) | no |  |
| position_title_local | varchar(200) | yes |  |
| dept_id | uuid | yes |  |
| branch_id | uuid | yes |  |
| job_id | uuid | yes |  |
| cost_centre_id | uuid | yes |  |
| headcount_budget | smallint | no | `1` |
| headcount_filled | smallint | no | `0` |
| position_status | varchar(20) | no | `open` |
| is_budgeted | boolean | no | `true` |
| effective_date | date | yes |  |
| expiry_date | date | yes |  |
| is_active | boolean | no | `true` |
| created_by | bigint | yes |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| headcount_vacant | smallint | yes |  |

- **Primary key:** position_id
- **Foreign keys:** `branch_id` → `organization_branches.branch_id` (on delete RESTRICT); `cost_centre_id` → `cost_centers.cost_centre_id` (on delete RESTRICT); `dept_id` → `branch_departments.dept_id` (on delete RESTRICT); `job_id` → `job_catalog.job_id` (on delete RESTRICT)
- **Unique:** (position_code)
- **Indexes:** branch_id; dept_id; is_active; job_id; position_status; position_code
- **Checks:** (((expiry_date IS NULL) OR (effective_date IS NULL) OR (expiry_date >= effective_date))); ((headcount_budget > 0)); ((headcount_filled >= 0)); (((position_status)::text = ANY ((ARRAY['open'::character varying, 'filled'::character varying, 'frozen'::character varying, 'closed'::character varying, 'on_hold'::character varying])::text[])))

---
