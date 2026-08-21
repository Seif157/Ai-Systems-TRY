<!-- Module: ServiceRequests | Domain: HR | Split from DATABASE_SCHEMA.md -->

> **Canonical V2 note:** Apply [global standards](../02_GLOBAL_SCHEMA_STANDARDS.md) and this subdomain's final rules in [canonical module corrections](../04_CANONICAL_MODULE_CORRECTIONS.md). Those rules override this generated base definition.

## ServiceRequests

### `sr_generated_letters`

| Column | Type | Null | Default |
|---|---|---|---|
| letter_id 🔑 | uuid | no | `gen_random_uuid()` |
| request_id | uuid | yes |  |
| template_id | uuid | no |  |
| context_snapshot | jsonb | yes |  |
| pdf_path | varchar(255) | no |  |
| reference_no | varchar(40) | no |  |
| generated_by | bigint | no |  |
| generated_at | timestamptz | no |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |

- **Primary key:** letter_id
- **Foreign keys:** `template_id` → `sr_letter_templates.template_id` (on delete RESTRICT)
- **Unique:** (reference_no)
- **Indexes:** request_id; reference_no

### `sr_letter_templates`

| Column | Type | Null | Default |
|---|---|---|---|
| template_id 🔑 | uuid | no | `gen_random_uuid()` |
| code | varchar(40) | no |  |
| name | varchar(120) | no |  |
| body_ar | text | no |  |
| body_en | text | no |  |
| header_footer_config | jsonb | yes |  |
| version | integer | no | `1` |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |
| created_by | bigint | yes |  |

- **Primary key:** template_id
- **Unique:** (code)
- **Indexes:** code

### `sr_request_types`

| Column | Type | Null | Default |
|---|---|---|---|
| type_id 🔑 | uuid | no | `gen_random_uuid()` |
| code | varchar(40) | no |  |
| name_ar | varchar(120) | no |  |
| name_en | varchar(120) | no |  |
| category | varchar(20) | no |  |
| requires_approval | boolean | no | `true` |
| sla_hours | integer | no | `48` |
| letter_template_id | uuid | yes |  |
| is_active | boolean | no | `true` |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| created_by | bigint | yes |  |

- **Primary key:** type_id
- **Unique:** (code)
- **Indexes:** category; code
- **Checks:** (((category)::text = ANY ((ARRAY['letter'::character varying, 'ticket'::character varying])::text[])))

### `sr_requests`

| Column | Type | Null | Default |
|---|---|---|---|
| request_id 🔑 | uuid | no | `gen_random_uuid()` |
| request_no | varchar(30) | no |  |
| employee_id | uuid | no |  |
| request_type_id | uuid | no |  |
| category | varchar(20) | no |  |
| payload | jsonb | yes |  |
| status | varchar(20) | no | `submitted` |
| approval_request_id | uuid | yes |  |
| assigned_to | uuid | yes |  |
| sla_due_at | timestamptz | no |  |
| resolved_at | timestamptz | yes |  |
| output_document_id | uuid | yes |  |
| created_by | bigint | no |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |

- **Primary key:** request_id
- **Foreign keys:** `request_type_id` → `sr_request_types.type_id` (on delete RESTRICT)
- **Unique:** (request_no)
- **Indexes:** employee_id; status; request_no
- **Checks:** (((category)::text = ANY ((ARRAY['letter'::character varying, 'ticket'::character varying])::text[]))); (((status)::text = ANY ((ARRAY['submitted'::character varying, 'pending_approval'::character varying, 'in_progress'::character varying, 'resolved'::character varying, 'rejected'::character varying, 'closed'::character varying])::text[])))

---
