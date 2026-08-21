<!-- Module: EmployeeChangeRequest | Domain: HR | Split from DATABASE_SCHEMA.md -->

> **Canonical V2 note:** Apply [global standards](../02_GLOBAL_SCHEMA_STANDARDS.md) and this subdomain's final rules in [canonical module corrections](../04_CANONICAL_MODULE_CORRECTIONS.md). Those rules override this generated base definition.

## EmployeeChangeRequest

### `employee_change_requests`

| Column | Type | Null | Default |
|---|---|---|---|
| request_id 🔑 | uuid | no | `gen_random_uuid()` |
| employee_id | uuid | no |  |
| field_name | varchar(255) | no |  |
| old_value | text | yes |  |
| new_value | text | no |  |
| status | varchar(20) | no | `pending` |
| requested_at | timestamptz | no |  |
| decided_by | integer | yes |  |
| decided_at | timestamptz | yes |  |
| decision_note | text | yes |  |
| is_active | boolean | no | `true` |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| created_by | bigint | yes |  |

- **Primary key:** request_id
- **Foreign keys:** `employee_id` → `employees.employee_id` (on delete CASCADE)
- **Indexes:** employee_id, status; status
- **Checks:** (((status)::text = ANY ((ARRAY['pending'::character varying, 'approved'::character varying, 'rejected'::character varying])::text[])))

---
