<!-- Module: Talent | Domain: HR | Split from DATABASE_SCHEMA.md -->

> **Canonical V2 note:** Apply [global standards](../02_GLOBAL_SCHEMA_STANDARDS.md) and this subdomain's final rules in [canonical module corrections](../04_CANONICAL_MODULE_CORRECTIONS.md). Those rules override this generated base definition.

## Talent

### `tal_career_paths`

| Column | Type | Null | Default |
|---|---|---|---|
| path_id 🔑 | uuid | no | `gen_random_uuid()` |
| from_grade_id | uuid | no |  |
| to_grade_id | uuid | no |  |
| min_tenure_months | integer | no |  |
| required_competencies | jsonb | yes |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |
| created_by | bigint | yes |  |

- **Primary key:** path_id
- **Foreign keys:** `from_grade_id` → `job_grades.job_grade_id` (on delete RESTRICT); `to_grade_id` → `job_grades.job_grade_id` (on delete RESTRICT)
- **Indexes:** from_grade_id

### `tal_employee_criterion_progress`

| Column | Type | Null | Default |
|---|---|---|---|
| progress_id 🔑 | uuid | no | `gen_random_uuid()` |
| employee_id | uuid | no |  |
| criterion_id | uuid | no |  |
| state | varchar(20) | no |  |
| progress_percent | numeric(5,2) | no | `0` |
| gaps_count | integer | no | `0` |
| notes | text | yes |  |
| updated_by | bigint | no |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |
| created_by | bigint | yes |  |

- **Primary key:** progress_id
- **Foreign keys:** `criterion_id` → `tal_promotion_criteria.criterion_id` (on delete CASCADE)
- **Unique:** (employee_id, criterion_id)
- **Indexes:** employee_id; employee_id, criterion_id
- **Checks:** (((state)::text = ANY ((ARRAY['met'::character varying, 'in_progress'::character varying])::text[])))

### `tal_promotion_cases`

| Column | Type | Null | Default |
|---|---|---|---|
| case_id 🔑 | uuid | no | `gen_random_uuid()` |
| case_no | varchar(30) | no |  |
| employee_id | uuid | no |  |
| current_grade_id | uuid | yes |  |
| proposed_grade_id | uuid | no |  |
| target_position_id | uuid | yes |  |
| current_salary | numeric(12,2) | yes |  |
| proposed_salary | numeric(12,2) | no |  |
| effective_date | date | no |  |
| justification | text | yes |  |
| status | varchar(20) | no | `draft` |
| approval_id | uuid | yes |  |
| applied_at | timestamptz | yes |  |
| created_by | bigint | no |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |

- **Primary key:** case_id
- **Foreign keys:** `proposed_grade_id` → `job_grades.job_grade_id` (on delete RESTRICT)
- **Unique:** (case_no)
- **Indexes:** employee_id; status; case_no
- **Checks:** (((status)::text = ANY ((ARRAY['draft'::character varying, 'pending_approval'::character varying, 'approved'::character varying, 'applied'::character varying, 'rejected'::character varying])::text[])))

### `tal_promotion_criteria`

| Column | Type | Null | Default |
|---|---|---|---|
| criterion_id 🔑 | uuid | no | `gen_random_uuid()` |
| career_path_id | uuid | no |  |
| name | varchar(255) | no |  |
| weight | integer | no | `1` |
| sort_order | integer | no | `0` |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |
| created_by | bigint | yes |  |

- **Primary key:** criterion_id
- **Foreign keys:** `career_path_id` → `tal_career_paths.path_id` (on delete CASCADE)
- **Indexes:** career_path_id

### `tal_promotion_nominations`

| Column | Type | Null | Default |
|---|---|---|---|
| nomination_id 🔑 | uuid | no | `gen_random_uuid()` |
| employee_id | uuid | no |  |
| nominator_user_id | bigint | no |  |
| role_label | varchar(255) | yes |  |
| quote | text | yes |  |
| nominated_at | date | no |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |
| created_by | bigint | yes |  |

- **Primary key:** nomination_id
- **Indexes:** employee_id

### `tal_role_highlights`

| Column | Type | Null | Default |
|---|---|---|---|
| highlight_id 🔑 | uuid | no | `gen_random_uuid()` |
| operation_id | uuid | no |  |
| highlight | varchar(255) | no |  |
| sort_order | integer | no | `0` |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |
| created_by | bigint | yes |  |

- **Primary key:** highlight_id
- **Foreign keys:** `operation_id` → `employee_operations.operation_id` (on delete CASCADE)
- **Indexes:** operation_id

### `tal_succession_candidates`

| Column | Type | Null | Default |
|---|---|---|---|
| succession_id 🔑 | uuid | no | `gen_random_uuid()` |
| position_id | uuid | no |  |
| candidate_employee_id | uuid | no |  |
| readiness | varchar(20) | no |  |
| rank | integer | no |  |
| notes | text | yes |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |
| created_by | bigint | yes |  |

- **Primary key:** succession_id
- **Foreign keys:** `position_id` → `positions.position_id` (on delete RESTRICT)
- **Indexes:** position_id
- **Checks:** (((readiness)::text = ANY ((ARRAY['ready_now'::character varying, '1_2_years'::character varying, 'long_term'::character varying])::text[])))

---
