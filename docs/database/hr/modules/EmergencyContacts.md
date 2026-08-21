<!-- Module: EmergencyContacts | Domain: HR | Split from DATABASE_SCHEMA.md -->

> **Canonical V2 note:** Apply [global standards](../02_GLOBAL_SCHEMA_STANDARDS.md) and this subdomain's final rules in [canonical module corrections](../04_CANONICAL_MODULE_CORRECTIONS.md). Those rules override this generated base definition.

## EmergencyContacts

### `emergency_contacts`

| Column | Type | Null | Default |
|---|---|---|---|
| contact_id 🔑 | uuid | no | `gen_random_uuid()` |
| employee_id | uuid | no |  |
| full_name | varchar(255) | no |  |
| full_name_local | varchar(255) | yes |  |
| relationship | varchar(100) | no |  |
| phone_primary | varchar(30) | no |  |
| phone_secondary | varchar(30) | yes |  |
| email | varchar(255) | yes |  |
| address | text | yes |  |
| national_id | varchar(50) | yes |  |
| is_primary | boolean | no | `false` |
| is_active | boolean | no | `true` |
| created_by | bigint | yes |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |

- **Primary key:** contact_id
- **Foreign keys:** `employee_id` → `employees.employee_id` (on delete CASCADE)
- **Indexes:** employee_id; employee_id

---
