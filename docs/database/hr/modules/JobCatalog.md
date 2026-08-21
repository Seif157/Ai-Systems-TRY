<!-- Module: JobCatalog | Domain: HR | Split from DATABASE_SCHEMA.md -->

> **Canonical V2 note:** Apply [global standards](../02_GLOBAL_SCHEMA_STANDARDS.md) and this subdomain's final rules in [canonical module corrections](../04_CANONICAL_MODULE_CORRECTIONS.md). Those rules override this generated base definition.

## JobCatalog

### `job_catalog`

| Column | Type | Null | Default |
|---|---|---|---|
| job_id 🔑 | uuid | no | `gen_random_uuid()` |
| job_grade_id | uuid | yes |  |
| job_code | varchar(30) | no |  |
| job_title | varchar(200) | no |  |
| job_title_local | varchar(200) | yes |  |
| job_family | varchar(100) | yes |  |
| job_subfamily | varchar(100) | yes |  |
| job_level | varchar(20) | no |  |
| job_category | varchar(20) | no |  |
| job_description | text | yes |  |
| qualifications_required | text | yes |  |
| skills_required | text | yes |  |
| min_experience_years | smallint | no | `0` |
| requires_approval | boolean | no | `false` |
| is_active | boolean | no | `true` |
| created_by | bigint | yes |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_internal | boolean | no | `true` |

- **Primary key:** job_id
- **Foreign keys:** `job_grade_id` → `job_grades.job_grade_id` (on delete RESTRICT)
- **Unique:** (job_code)
- **Indexes:** job_category; job_family; job_grade_id; is_active; job_level; job_code
- **Checks:** (((job_category)::text = ANY ((ARRAY['full_time'::character varying, 'part_time'::character varying, 'contract'::character varying, 'internship'::character varying, 'temporary'::character varying])::text[]))); ((min_experience_years >= 0)); (((job_level)::text = ANY ((ARRAY['entry'::character varying, 'junior'::character varying, 'mid'::character varying, 'senior'::character varying, 'lead'::character varying, 'principal'::character varying, 'manager'::character varying, 'director'::character varying, 'vp'::character varying, 'c_level'::character varying])::text[])))

---
