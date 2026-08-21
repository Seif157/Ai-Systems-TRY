<!-- Module: JobGrade | Domain: HR | Split from DATABASE_SCHEMA.md -->

> **Canonical V2 note:** Apply [global standards](../02_GLOBAL_SCHEMA_STANDARDS.md) and this subdomain's final rules in [canonical module corrections](../04_CANONICAL_MODULE_CORRECTIONS.md). Those rules override this generated base definition.

## JobGrade

### `job_grades`

| Column | Type | Null | Default |
|---|---|---|---|
| job_grade_id 🔑 | uuid | no | `gen_random_uuid()` |
| grade_code | varchar(20) | no |  |
| grade_name | varchar(200) | no |  |
| grade_name_local | varchar(200) | yes |  |
| grade_level | smallint | no |  |
| grade_category | varchar(30) | no |  |
| min_salary | numeric(15,2) | no | `0` |
| mid_salary | numeric(15,2) | no | `0` |
| max_salary | numeric(15,2) | no | `0` |
| currency_code | char(3) | no |  |
| description | text | yes |  |
| overtime_eligible | boolean | no | `false` |
| annual_leave_days | smallint | no | `0` |
| sick_leave_days | smallint | no | `0` |
| is_active | boolean | no | `true` |
| created_by | bigint | yes |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |

- **Primary key:** job_grade_id
- **Unique:** (grade_code)
- **Indexes:** grade_category; is_active; grade_level; grade_code
- **Checks:** (((grade_category)::text = ANY ((ARRAY['executive'::character varying, 'management'::character varying, 'professional'::character varying, 'technical'::character varying, 'administrative'::character varying, 'operational'::character varying])::text[]))); (((annual_leave_days >= 0) AND (sick_leave_days >= 0))); ((grade_level >= 1)); (((min_salary >= (0)::numeric) AND (mid_salary >= min_salary) AND (max_salary >= mid_salary)))

---
