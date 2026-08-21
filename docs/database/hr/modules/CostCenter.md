<!-- Module: CostCenter | Domain: HR | Split from DATABASE_SCHEMA.md -->

> **Canonical V2 note:** Apply [global standards](../02_GLOBAL_SCHEMA_STANDARDS.md) and this subdomain's final rules in [canonical module corrections](../04_CANONICAL_MODULE_CORRECTIONS.md). Those rules override this generated base definition.

## CostCenter

### `cost_centers`

| Column | Type | Null | Default |
|---|---|---|---|
| cost_centre_id 🔑 | uuid | no | `gen_random_uuid()` |
| parent_cc_id | uuid | yes |  |
| branch_id | uuid | yes |  |
| dept_id | uuid | yes |  |
| cc_code | varchar(20) | no |  |
| cc_name | varchar(200) | no |  |
| cc_name_local | varchar(200) | yes |  |
| cc_type | varchar(30) | no |  |
| account_code | varchar(50) | yes |  |
| currency_code | char(3) | no |  |
| budget_amount | numeric(15,2) | no | `0` |
| fiscal_year | smallint | no |  |
| is_active | boolean | no | `true` |
| created_by | bigint | yes |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |

- **Primary key:** cost_centre_id
- **Foreign keys:** `branch_id` → `organization_branches.branch_id` (on delete RESTRICT); `dept_id` → `branch_departments.dept_id` (on delete RESTRICT); `parent_cc_id` → `cost_centers.cost_centre_id` (on delete RESTRICT)
- **Unique:** (cc_code, fiscal_year)
- **Indexes:** branch_id; cc_type; dept_id; fiscal_year; is_active; parent_cc_id; cc_code, fiscal_year
- **Checks:** ((budget_amount >= (0)::numeric)); (((fiscal_year >= 2000) AND (fiscal_year <= 2100))); (((cc_type)::text = ANY ((ARRAY['profit_centre'::character varying, 'cost_centre'::character varying, 'investment_centre'::character varying, 'revenue_centre'::character varying])::text[])))

---
