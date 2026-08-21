<!-- Module: OrganizationBranch | Domain: HR | Split from DATABASE_SCHEMA.md -->

> **Canonical V2 note:** Apply [global standards](../02_GLOBAL_SCHEMA_STANDARDS.md) and this subdomain's final rules in [canonical module corrections](../04_CANONICAL_MODULE_CORRECTIONS.md). Those rules override this generated base definition.

## OrganizationBranch

### `organization_branches`

| Column | Type | Null | Default |
|---|---|---|---|
| branch_id 🔑 | uuid | no | `gen_random_uuid()` |
| branch_code | varchar(20) | no |  |
| branch_name | varchar(200) | no |  |
| branch_name_local | varchar(200) | yes |  |
| branch_type | varchar(50) | no |  |
| parent_branch_id | uuid | yes |  |
| country_code | varchar(2) | no |  |
| city | varchar(100) | no |  |
| address_line1 | text | yes |  |
| address_line2 | text | yes |  |
| postal_code | varchar(20) | yes |  |
| phone | varchar(50) | yes |  |
| email | varchar(200) | yes |  |
| tax_id | varchar(100) | yes |  |
| manager_emp_id | uuid | yes |  |
| is_head_office | boolean | no | `false` |
| is_active | boolean | no | `true` |
| established_date | date | yes |  |
| created_by | bigint | yes |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |

- **Primary key:** branch_id
- **Foreign keys:** `parent_branch_id` → `organization_branches.branch_id` (on delete RESTRICT)
- **Unique:** (branch_code)
- **Indexes:** is_active; country_code; is_head_office; parent_branch_id; branch_type; branch_code
- **Checks:** (((branch_type)::text = ANY ((ARRAY['head_office'::character varying, 'regional_office'::character varying, 'branch'::character varying, 'warehouse'::character varying, 'site'::character varying])::text[])))

---
