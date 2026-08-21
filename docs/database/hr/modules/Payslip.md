<!-- Module: Payslip | Domain: HR | Split from DATABASE_SCHEMA.md -->

> **Canonical V2 note:** Apply [global standards](../02_GLOBAL_SCHEMA_STANDARDS.md) and this subdomain's final rules in [canonical module corrections](../04_CANONICAL_MODULE_CORRECTIONS.md). Those rules override this generated base definition.

## Payslip

### `ps_payslip_access_log`

| Column | Type | Null | Default |
|---|---|---|---|
| log_id 🔑 | uuid | no | `gen_random_uuid()` |
| payslip_id | uuid | no |  |
| accessed_by | bigint | no |  |
| action | varchar(15) | no |  |
| ip | varchar(45) | yes |  |
| accessed_at | timestamptz | no |  |

- **Primary key:** log_id
- **Foreign keys:** `payslip_id` → `ps_payslip_documents.payslip_id` (on delete CASCADE)
- **Indexes:** payslip_id
- **Checks:** (((action)::text = ANY ((ARRAY['viewed'::character varying, 'downloaded'::character varying])::text[])))

### `ps_payslip_documents`

| Column | Type | Null | Default |
|---|---|---|---|
| payslip_id 🔑 | uuid | no | `gen_random_uuid()` |
| employee_id | uuid | no |  |
| period | varchar(7) | no |  |
| pdf_path | varchar(255) | yes |  |
| gross | numeric(12,2) | yes |  |
| total_deductions | numeric(12,2) | yes |  |
| net | numeric(12,2) | yes |  |
| status | varchar(15) | no | `draft` |
| published_at | timestamptz | yes |  |
| created_by | bigint | no |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |

- **Primary key:** payslip_id
- **Unique:** (employee_id, period)
- **Indexes:** employee_id; period; status; employee_id, period
- **Checks:** (((status)::text = ANY ((ARRAY['draft'::character varying, 'generated'::character varying, 'sent'::character varying])::text[])))

---
