<!-- Module: Training | Domain: HR | Split from DATABASE_SCHEMA.md -->

> **Canonical V2 note:** Apply [global standards](../02_GLOBAL_SCHEMA_STANDARDS.md) and this subdomain's final rules in [canonical module corrections](../04_CANONICAL_MODULE_CORRECTIONS.md). Those rules override this generated base definition.

## Training

### `certifications`

| Column | Type | Null | Default |
|---|---|---|---|
| cert_id 🔑 | uuid | no | `gen_random_uuid()` |
| employee_id | uuid | no |  |
| course_id | uuid | no |  |
| cert_name | varchar(200) | no |  |
| cert_name_local | varchar(200) | yes |  |
| issuing_body | varchar(200) | yes |  |
| obtained_date | date | no |  |
| expiry_date | date | yes |  |
| status | varchar(20) | no | `active` |
| certificate_url | varchar(500) | yes |  |
| created_by | bigint | no |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |

- **Primary key:** cert_id
- **Foreign keys:** `course_id` → `training_courses.course_id` (on delete RESTRICT)
- **Indexes:** employee_id, expiry_date; status
- **Checks:** (((status)::text = ANY ((ARRAY['active'::character varying, 'expiring_soon'::character varying, 'expired'::character varying, 'revoked'::character varying])::text[])))

### `course_modules`

| Column | Type | Null | Default |
|---|---|---|---|
| module_id 🔑 | uuid | no | `gen_random_uuid()` |
| course_id | uuid | no |  |
| sequence_order | smallint | no |  |
| title | varchar(200) | no |  |
| description | text | yes |  |
| material_url | varchar(500) | yes |  |
| duration_minutes | integer | yes |  |
| created_at | timestamptz | no | `CURRENT_TIMESTAMP` |
| is_active | boolean | no | `true` |
| created_by | bigint | yes |  |
| updated_at | timestamptz | no | `now()` |

- **Primary key:** module_id
- **Foreign keys:** `course_id` → `training_courses.course_id` (on delete CASCADE)
- **Indexes:** course_id, sequence_order

### `course_prerequisites`

| Column | Type | Null | Default |
|---|---|---|---|
| prereq_id 🔑 | uuid | no | `gen_random_uuid()` |
| course_id | uuid | no |  |
| prerequisite_course_id | uuid | no |  |
| created_at | timestamptz | no | `CURRENT_TIMESTAMP` |
| is_active | boolean | no | `true` |
| created_by | bigint | yes |  |
| updated_at | timestamptz | no | `now()` |

- **Primary key:** prereq_id
- **Foreign keys:** `course_id` → `training_courses.course_id` (on delete CASCADE); `prerequisite_course_id` → `training_courses.course_id` (on delete CASCADE)
- **Unique:** (course_id, prerequisite_course_id)
- **Indexes:** course_id, prerequisite_course_id

### `employee_skills`

| Column | Type | Null | Default |
|---|---|---|---|
| emp_skill_id 🔑 | uuid | no | `gen_random_uuid()` |
| employee_id | uuid | no |  |
| skill_id | uuid | no |  |
| current_level | smallint | no |  |
| target_level | smallint | yes |  |
| assessed_by | uuid | yes |  |
| assessed_at | timestamptz | yes |  |
| source | varchar(20) | no | `self` |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |

- **Primary key:** emp_skill_id
- **Foreign keys:** `skill_id` → `skills.skill_id` (on delete RESTRICT)
- **Unique:** (employee_id, skill_id)
- **Indexes:** employee_id; skill_id, current_level; employee_id, skill_id
- **Checks:** (((current_level >= 1) AND (current_level <= 5))); (((source)::text = ANY ((ARRAY['self'::character varying, 'manager'::character varying, 'assessment'::character varying, 'certification'::character varying, 'training'::character varying])::text[]))); (((target_level IS NULL) OR ((target_level >= 1) AND (target_level <= 5))))

### `program_cohorts`

| Column | Type | Null | Default |
|---|---|---|---|
| cohort_id 🔑 | uuid | no | `gen_random_uuid()` |
| program_id | uuid | no |  |
| cohort_name | varchar(150) | no |  |
| start_date | date | yes |  |
| end_date | date | yes |  |
| capacity | integer | yes |  |
| enrolled_count | integer | no | `0` |
| status | varchar(20) | no | `planned` |
| created_at | timestamptz | no | `CURRENT_TIMESTAMP` |
| is_active | boolean | no | `true` |
| created_by | bigint | yes |  |
| updated_at | timestamptz | no | `now()` |

- **Primary key:** cohort_id
- **Foreign keys:** `program_id` → `training_programs.program_id` (on delete CASCADE)
- **Unique:** (program_id, cohort_name)
- **Indexes:** program_id, status; program_id, cohort_name
- **Checks:** (((status)::text = ANY ((ARRAY['planned'::character varying, 'open'::character varying, 'full'::character varying, 'in_progress'::character varying, 'completed'::character varying, 'cancelled'::character varying])::text[])))

### `program_courses`

| Column | Type | Null | Default |
|---|---|---|---|
| program_course_id 🔑 | uuid | no | `gen_random_uuid()` |
| program_id | uuid | no |  |
| course_id | uuid | no |  |
| sequence_order | smallint | no | `1` |
| is_mandatory | boolean | no | `true` |
| created_at | timestamptz | no | `CURRENT_TIMESTAMP` |
| is_active | boolean | no | `true` |
| created_by | bigint | yes |  |
| updated_at | timestamptz | no | `now()` |

- **Primary key:** program_course_id
- **Foreign keys:** `course_id` → `training_courses.course_id` (on delete RESTRICT); `program_id` → `training_programs.program_id` (on delete CASCADE)
- **Unique:** (program_id, course_id)
- **Indexes:** program_id, sequence_order; program_id, course_id

### `program_enrollments`

| Column | Type | Null | Default |
|---|---|---|---|
| enrollment_id 🔑 | uuid | no | `gen_random_uuid()` |
| program_id | uuid | no |  |
| cohort_id | uuid | yes |  |
| employee_id | uuid | no |  |
| status | varchar(20) | no | `enrolled` |
| enrolled_at | timestamptz | yes |  |
| completion_pct | numeric(5,2) | no | `0` |
| completed_at | timestamptz | yes |  |
| approval_request_id | uuid | yes |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |

- **Primary key:** enrollment_id
- **Foreign keys:** `cohort_id` → `program_cohorts.cohort_id` (on delete SET NULL); `program_id` → `training_programs.program_id` (on delete RESTRICT)
- **Unique:** (program_id, employee_id)
- **Indexes:** employee_id, status; program_id, status; program_id, employee_id
- **Checks:** (((completion_pct >= (0)::numeric) AND (completion_pct <= (100)::numeric))); (((status)::text = ANY ((ARRAY['enrolled'::character varying, 'in_progress'::character varying, 'completed'::character varying, 'dropped'::character varying, 'withdrawn'::character varying])::text[])))

### `role_skill_requirements`

| Column | Type | Null | Default |
|---|---|---|---|
| req_id 🔑 | uuid | no | `gen_random_uuid()` |
| job_grade_id | uuid | no |  |
| skill_id | uuid | no |  |
| required_level | smallint | no |  |
| created_at | timestamptz | no | `CURRENT_TIMESTAMP` |
| is_active | boolean | no | `true` |
| created_by | bigint | yes |  |
| updated_at | timestamptz | no | `now()` |

- **Primary key:** req_id
- **Foreign keys:** `skill_id` → `skills.skill_id` (on delete RESTRICT)
- **Unique:** (job_grade_id, skill_id)
- **Indexes:** job_grade_id; job_grade_id, skill_id
- **Checks:** (((required_level >= 1) AND (required_level <= 5)))

### `session_attendances`

| Column | Type | Null | Default |
|---|---|---|---|
| attendance_id 🔑 | uuid | no | `gen_random_uuid()` |
| session_id | uuid | no |  |
| employee_id | uuid | no |  |
| attended | boolean | no | `false` |
| score | numeric(5,2) | yes |  |
| result | varchar(10) | no | `pending` |
| marked_by | uuid | yes |  |
| marked_at | timestamptz | yes |  |
| created_at | timestamptz | no | `CURRENT_TIMESTAMP` |
| is_active | boolean | no | `true` |
| created_by | bigint | yes |  |
| updated_at | timestamptz | no | `now()` |

- **Primary key:** attendance_id
- **Foreign keys:** `session_id` → `training_sessions.session_id` (on delete CASCADE)
- **Unique:** (session_id, employee_id)
- **Indexes:** employee_id; session_id, employee_id
- **Checks:** (((result)::text = ANY ((ARRAY['pass'::character varying, 'fail'::character varying, 'pending'::character varying])::text[]))); (((score IS NULL) OR ((score >= (0)::numeric) AND (score <= (100)::numeric))))

### `session_enrollments`

| Column | Type | Null | Default |
|---|---|---|---|
| enrollment_id 🔑 | uuid | no | `gen_random_uuid()` |
| session_id | uuid | no |  |
| employee_id | uuid | no |  |
| status | varchar(20) | no | `requested` |
| waitlist_position | integer | yes |  |
| approval_request_id | uuid | yes |  |
| enrolled_at | timestamptz | yes |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |

- **Primary key:** enrollment_id
- **Foreign keys:** `session_id` → `training_sessions.session_id` (on delete CASCADE)
- **Unique:** (session_id, employee_id)
- **Indexes:** employee_id, status; session_id, employee_id
- **Checks:** (((status)::text = ANY ((ARRAY['requested'::character varying, 'approved'::character varying, 'enrolled'::character varying, 'waitlisted'::character varying, 'attended'::character varying, 'no_show'::character varying, 'cancelled'::character varying])::text[])))

### `skills`

| Column | Type | Null | Default |
|---|---|---|---|
| skill_id 🔑 | uuid | no | `gen_random_uuid()` |
| skill_code | varchar(30) | no |  |
| skill_name | varchar(150) | no |  |
| skill_name_local | varchar(150) | yes |  |
| category | varchar(50) | no |  |
| description | text | yes |  |
| is_active | boolean | no | `true` |
| created_by | bigint | no |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |

- **Primary key:** skill_id
- **Unique:** (skill_code)
- **Indexes:** category; is_active; skill_code

### `training_courses`

| Column | Type | Null | Default |
|---|---|---|---|
| course_id 🔑 | uuid | no | `gen_random_uuid()` |
| course_code | varchar(30) | no |  |
| course_name | varchar(200) | no |  |
| course_name_local | varchar(200) | yes |  |
| category | varchar(50) | no |  |
| delivery_mode | varchar(30) | no |  |
| level | varchar(20) | no |  |
| duration_hours | numeric(6,2) | no |  |
| provider | varchar(200) | yes |  |
| cost_per_seat | numeric(12,2) | no | `0` |
| currency_code | varchar(3) | no | `EGP` |
| passing_score | numeric(5,2) | yes |  |
| validity_months | smallint | yes |  |
| is_mandatory | boolean | no | `false` |
| is_active | boolean | no | `true` |
| created_by | bigint | no |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |

- **Primary key:** course_id
- **Unique:** (course_code)
- **Indexes:** category, is_active; course_code
- **Checks:** (((category)::text = ANY ((ARRAY['technical'::character varying, 'soft_skills'::character varying, 'compliance'::character varying, 'leadership'::character varying, 'onboarding'::character varying, 'safety'::character varying, 'product'::character varying])::text[]))); ((cost_per_seat >= (0)::numeric)); (((delivery_mode)::text = ANY ((ARRAY['classroom'::character varying, 'e_learning'::character varying, 'blended'::character varying, 'online'::character varying, 'hybrid'::character varying])::text[]))); (((level)::text = ANY ((ARRAY['beginner'::character varying, 'intermediate'::character varying, 'advanced'::character varying, 'expert'::character varying])::text[]))); (((passing_score IS NULL) OR ((passing_score >= (0)::numeric) AND (passing_score <= (100)::numeric))))

### `training_feedbacks`

| Column | Type | Null | Default |
|---|---|---|---|
| feedback_id 🔑 | uuid | no | `gen_random_uuid()` |
| session_id | uuid | no |  |
| employee_id | uuid | no |  |
| content_rating | smallint | no |  |
| trainer_rating | smallint | no |  |
| relevance_rating | smallint | no |  |
| would_recommend | boolean | no | `true` |
| comments | text | yes |  |
| submitted_at | timestamptz | no | `CURRENT_TIMESTAMP` |
| is_active | boolean | no | `true` |
| updated_at | timestamptz | no | `now()` |

- **Primary key:** feedback_id
- **Foreign keys:** `session_id` → `training_sessions.session_id` (on delete CASCADE)
- **Unique:** (session_id, employee_id)
- **Indexes:** session_id; session_id, employee_id
- **Checks:** (((content_rating >= 1) AND (content_rating <= 5))); (((relevance_rating >= 1) AND (relevance_rating <= 5))); (((trainer_rating >= 1) AND (trainer_rating <= 5)))

### `training_programs`

| Column | Type | Null | Default |
|---|---|---|---|
| program_id 🔑 | uuid | no | `gen_random_uuid()` |
| program_code | varchar(30) | no |  |
| program_name | varchar(200) | no |  |
| program_name_local | varchar(200) | yes |  |
| category | varchar(50) | no |  |
| description | text | yes |  |
| status | varchar(20) | no | `draft` |
| provider | varchar(200) | yes |  |
| owner_emp_id | uuid | yes |  |
| target_audience | varchar(300) | yes |  |
| total_duration_hours | numeric(8,2) | no | `0` |
| cost_per_seat | numeric(12,2) | no | `0` |
| currency_code | varchar(3) | no | `EGP` |
| max_cohort_size | integer | yes |  |
| start_date | date | yes |  |
| end_date | date | yes |  |
| is_active | boolean | no | `true` |
| created_by | bigint | no |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |

- **Primary key:** program_id
- **Unique:** (program_code)
- **Indexes:** category, status; owner_emp_id; program_code
- **Checks:** (((category)::text = ANY ((ARRAY['technical'::character varying, 'soft_skills'::character varying, 'compliance'::character varying, 'leadership'::character varying, 'onboarding'::character varying, 'safety'::character varying, 'product'::character varying])::text[]))); ((cost_per_seat >= (0)::numeric)); (((status)::text = ANY ((ARRAY['draft'::character varying, 'active'::character varying, 'paused'::character varying, 'completed'::character varying, 'archived'::character varying])::text[])))

### `training_sessions`

| Column | Type | Null | Default |
|---|---|---|---|
| session_id 🔑 | uuid | no | `gen_random_uuid()` |
| course_id | uuid | no |  |
| cohort_id | uuid | yes |  |
| start_datetime | timestamptz | no |  |
| end_datetime | timestamptz | no |  |
| trainer_emp_id | uuid | yes |  |
| external_trainer | varchar(200) | yes |  |
| venue | varchar(300) | yes |  |
| delivery_mode | varchar(30) | no |  |
| max_seats | integer | no |  |
| enrolled_count | integer | no | `0` |
| waitlist_count | integer | no | `0` |
| status | varchar(20) | no | `scheduled` |
| created_by | bigint | no |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |

- **Primary key:** session_id
- **Foreign keys:** `cohort_id` → `program_cohorts.cohort_id` (on delete SET NULL); `course_id` → `training_courses.course_id` (on delete RESTRICT)
- **Indexes:** course_id, start_datetime; status
- **Checks:** ((end_datetime > start_datetime)); (((delivery_mode)::text = ANY ((ARRAY['classroom'::character varying, 'e_learning'::character varying, 'blended'::character varying, 'online'::character varying, 'hybrid'::character varying])::text[]))); ((max_seats > 0)); (((status)::text = ANY ((ARRAY['scheduled'::character varying, 'open'::character varying, 'full'::character varying, 'in_progress'::character varying, 'completed'::character varying, 'cancelled'::character varying])::text[])))

---
