<!-- Module: EmployeeDocuments | Domain: HR | Split from DATABASE_SCHEMA.md -->

> **Canonical V2 note:** Apply [global standards](../02_GLOBAL_SCHEMA_STANDARDS.md) and this subdomain's final rules in [canonical module corrections](../04_CANONICAL_MODULE_CORRECTIONS.md). Those rules override this generated base definition.

## EmployeeDocuments

### `employee_documents`

| Column | Type | Null | Default |
|---|---|---|---|
| document_id 🔑 | uuid | no | `gen_random_uuid()` |
| employee_id | uuid | no |  |
| document_type | varchar(40) | no |  |
| document_category | varchar(20) | no |  |
| document_title | varchar(255) | no |  |
| document_number | varchar(100) | yes |  |
| issuing_authority | varchar(255) | yes |  |
| issuing_country | varchar(2) | yes |  |
| issue_date | date | yes |  |
| expiry_date | date | yes |  |
| alert_days_before | smallint | no | `30` |
| file_path | text | yes |  |
| file_type | varchar(20) | yes |  |
| file_size_kb | integer | yes |  |
| is_mandatory | boolean | no | `false` |
| is_verified | boolean | no | `false` |
| verified_by | bigint | yes |  |
| verified_date | timestamptz | yes |  |
| verification_notes | text | yes |  |
| is_active | boolean | no | `true` |
| uploaded_at | timestamptz | yes |  |
| uploaded_by | bigint | yes |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |

- **Primary key:** document_id
- **Foreign keys:** `employee_id` → `employees.employee_id` (on delete RESTRICT)
- **Indexes:** employee_id; expiry_date; employee_id, expiry_date; document_type
- **Checks:** (((document_category)::text = ANY ((ARRAY['identity'::character varying, 'legal'::character varying, 'educational'::character varying, 'professional'::character varying, 'medical'::character varying, 'internal'::character varying, 'other'::character varying])::text[]))); (((expiry_date IS NULL) OR (issue_date IS NULL) OR (expiry_date > issue_date))); (((document_type)::text = ANY ((ARRAY['degree'::character varying, 'passport'::character varying, 'degree_certificate'::character varying, 'professional_cert'::character varying, 'national_id'::character varying, 'birth_certificate'::character varying, 'work_permit'::character varying, 'visa'::character varying, 'iban_letter'::character varying, 'other'::character varying])::text[]))); (((file_type IS NULL) OR ((file_type)::text = ANY ((ARRAY['pdf'::character varying, 'jpg'::character varying, 'jpeg'::character varying, 'png'::character varying, 'docx'::character varying])::text[]))))

---
