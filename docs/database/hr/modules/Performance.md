<!-- Module: Performance | Domain: HR | Split from DATABASE_SCHEMA.md -->

> **Canonical V2 note:** Apply [global standards](../02_GLOBAL_SCHEMA_STANDARDS.md) and this subdomain's final rules in [canonical module corrections](../04_CANONICAL_MODULE_CORRECTIONS.md). Those rules override this generated base definition.

## Performance

### `appraisal_ratings`

| Column | Type | Null | Default |
|---|---|---|---|
| rating_id 🔑 | uuid | no | `gen_random_uuid()` |
| appraisal_id | uuid | no |  |
| item_type | varchar(20) | no |  |
| item_id | uuid | no |  |
| weight_pct | numeric(5,2) | no | `0` |
| self_rating | numeric(5,2) | yes |  |
| manager_rating | numeric(5,2) | yes |  |
| self_comment | text | yes |  |
| manager_comment | text | yes |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |

- **Primary key:** rating_id
- **Foreign keys:** `appraisal_id` → `appraisals.appraisal_id` (on delete CASCADE)
- **Indexes:** appraisal_id; item_type, item_id
- **Checks:** (((item_type)::text = ANY ((ARRAY['kpi'::character varying, 'goal'::character varying, 'competency'::character varying])::text[]))); (((weight_pct >= (0)::numeric) AND (weight_pct <= (100)::numeric)))

### `appraisals`

| Column | Type | Null | Default |
|---|---|---|---|
| appraisal_id 🔑 | uuid | no | `gen_random_uuid()` |
| cycle_id | uuid | no |  |
| employee_id | uuid | no |  |
| reviewer_emp_id | uuid | yes |  |
| self_score | numeric(5,2) | yes |  |
| manager_score | numeric(5,2) | yes |  |
| final_score | numeric(5,2) | yes |  |
| status | varchar(30) | no | `pending` |
| self_submitted_at | timestamptz | yes |  |
| manager_submitted_at | timestamptz | yes |  |
| acknowledged_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |
| created_by | bigint | no |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |

- **Primary key:** appraisal_id
- **Foreign keys:** `cycle_id` → `review_cycles.cycle_id` (on delete RESTRICT)
- **Unique:** (cycle_id, employee_id)
- **Indexes:** cycle_id, employee_id; cycle_id; employee_id; cycle_id, status
- **Checks:** (((status)::text = ANY ((ARRAY['pending'::character varying, 'self_in_progress'::character varying, 'self_submitted'::character varying, 'manager_in_progress'::character varying, 'manager_submitted'::character varying, 'finalised'::character varying, 'acknowledged'::character varying, 'calibrated'::character varying])::text[])))

### `calibration_entries`

| Column | Type | Null | Default |
|---|---|---|---|
| entry_id 🔑 | uuid | no | `gen_random_uuid()` |
| session_id | uuid | no |  |
| employee_id | uuid | no |  |
| original_rating | numeric(5,2) | yes |  |
| calibrated_rating | numeric(5,2) | yes |  |
| performance_axis | numeric(5,2) | yes |  |
| potential_axis | numeric(5,2) | yes |  |
| box_position | smallint | yes |  |
| notes | text | yes |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |
| created_by | bigint | yes |  |

- **Primary key:** entry_id
- **Foreign keys:** `session_id` → `calibration_sessions.session_id` (on delete CASCADE)
- **Indexes:** employee_id; session_id
- **Checks:** (((box_position IS NULL) OR ((box_position >= 1) AND (box_position <= 9))))

### `calibration_sessions`

| Column | Type | Null | Default |
|---|---|---|---|
| session_id 🔑 | uuid | no | `gen_random_uuid()` |
| cycle_id | uuid | no |  |
| scope | varchar(20) | no | `dept` |
| scope_id | uuid | yes |  |
| status | varchar(20) | no | `draft` |
| facilitator_emp_id | uuid | yes |  |
| finalised_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |
| created_by | bigint | no |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |

- **Primary key:** session_id
- **Foreign keys:** `cycle_id` → `review_cycles.cycle_id` (on delete RESTRICT)
- **Indexes:** cycle_id; status
- **Checks:** (((scope)::text = ANY ((ARRAY['all'::character varying, 'dept'::character varying, 'grade'::character varying])::text[]))); (((status)::text = ANY ((ARRAY['draft'::character varying, 'in_progress'::character varying, 'finalised'::character varying])::text[])))

### `competencies`

| Column | Type | Null | Default |
|---|---|---|---|
| competency_id 🔑 | uuid | no | `gen_random_uuid()` |
| competency_name | varchar(200) | no |  |
| competency_name_local | varchar(200) | yes |  |
| grade_scope | uuid | yes |  |
| description | text | yes |  |
| is_active | boolean | no | `true` |
| created_by | bigint | no |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |

- **Primary key:** competency_id
- **Indexes:** grade_scope; is_active

### `cycle_participants`

| Column | Type | Null | Default |
|---|---|---|---|
| participant_id 🔑 | uuid | no | `gen_random_uuid()` |
| cycle_id | uuid | no |  |
| employee_id | uuid | no |  |
| reviewer_emp_id | uuid | yes |  |
| phase_status | varchar(30) | no | `pending` |
| self_done_at | timestamptz | yes |  |
| manager_done_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| created_by | bigint | yes |  |

- **Primary key:** participant_id
- **Foreign keys:** `cycle_id` → `review_cycles.cycle_id` (on delete RESTRICT)
- **Unique:** (cycle_id, employee_id)
- **Indexes:** cycle_id, employee_id; cycle_id; employee_id; cycle_id, phase_status
- **Checks:** (((phase_status)::text = ANY ((ARRAY['pending'::character varying, 'self_in_progress'::character varying, 'self_done'::character varying, 'manager_in_progress'::character varying, 'manager_done'::character varying, 'calibrated'::character varying, 'finalised'::character varying])::text[])))

### `feedback_requests`

| Column | Type | Null | Default |
|---|---|---|---|
| request_id 🔑 | uuid | no | `gen_random_uuid()` |
| cycle_id | uuid | no |  |
| subject_emp_id | uuid | no |  |
| rater_emp_id | uuid | no |  |
| relationship | varchar(20) | no |  |
| status | varchar(20) | no | `sent` |
| sent_at | timestamptz | yes |  |
| responded_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| created_by | bigint | yes |  |

- **Primary key:** request_id
- **Foreign keys:** `cycle_id` → `review_cycles.cycle_id` (on delete RESTRICT)
- **Indexes:** cycle_id; rater_emp_id; subject_emp_id
- **Checks:** (((relationship)::text = ANY ((ARRAY['peer'::character varying, 'subordinate'::character varying, 'manager'::character varying, 'self'::character varying, 'external'::character varying])::text[]))); (((status)::text = ANY ((ARRAY['pending'::character varying, 'sent'::character varying, 'responded'::character varying, 'declined'::character varying, 'expired'::character varying])::text[])))

### `feedback_responses`

| Column | Type | Null | Default |
|---|---|---|---|
| response_id 🔑 | uuid | no | `gen_random_uuid()` |
| request_id | uuid | no |  |
| ratings_json | jsonb | yes |  |
| strengths | text | yes |  |
| improvements | text | yes |  |
| is_anonymous | boolean | no | `false` |
| submitted_at | timestamptz | yes |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |
| created_by | bigint | yes |  |

- **Primary key:** response_id
- **Foreign keys:** `request_id` → `feedback_requests.request_id` (on delete CASCADE)
- **Unique:** (request_id)
- **Indexes:** request_id; request_id

### `goal_checkins`

| Column | Type | Null | Default |
|---|---|---|---|
| checkin_id 🔑 | uuid | no | `gen_random_uuid()` |
| goal_id | uuid | no |  |
| progress_pct | numeric(5,2) | no |  |
| comment | text | yes |  |
| created_by | bigint | no |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |

- **Primary key:** checkin_id
- **Foreign keys:** `goal_id` → `goals.goal_id` (on delete CASCADE)
- **Indexes:** goal_id
- **Checks:** (((progress_pct >= (0)::numeric) AND (progress_pct <= (100)::numeric)))

### `goals`

| Column | Type | Null | Default |
|---|---|---|---|
| goal_id 🔑 | uuid | no | `gen_random_uuid()` |
| employee_id | uuid | no |  |
| title | varchar(255) | no |  |
| title_local | varchar(255) | yes |  |
| description | text | yes |  |
| goal_type | varchar(20) | no |  |
| category | varchar(50) | yes |  |
| weight_pct | numeric(5,2) | no | `0` |
| parent_goal_id | uuid | yes |  |
| cycle_id | uuid | yes |  |
| start_date | date | no |  |
| due_date | date | no |  |
| progress_pct | numeric(5,2) | no | `0` |
| status | varchar(20) | no | `draft` |
| approval_request_id | uuid | yes |  |
| is_active | boolean | no | `true` |
| created_by | bigint | no |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |

- **Primary key:** goal_id
- **Foreign keys:** `parent_goal_id` → `goals.goal_id` (on delete RESTRICT)
- **Indexes:** cycle_id; employee_id, cycle_id; employee_id; parent_goal_id; status
- **Checks:** (((progress_pct >= (0)::numeric) AND (progress_pct <= (100)::numeric))); (((status)::text = ANY ((ARRAY['draft'::character varying, 'submitted'::character varying, 'approved'::character varying, 'active'::character varying, 'completed'::character varying, 'cancelled'::character varying])::text[]))); (((goal_type)::text = ANY ((ARRAY['smart'::character varying, 'okr'::character varying])::text[]))); (((weight_pct >= (0)::numeric) AND (weight_pct <= (100)::numeric)))

### `improvement_plans`

| Column | Type | Null | Default |
|---|---|---|---|
| pip_id 🔑 | uuid | no | `gen_random_uuid()` |
| employee_id | uuid | no |  |
| cycle_id | uuid | yes |  |
| reason | text | no |  |
| objectives_json | jsonb | yes |  |
| start_date | date | no |  |
| end_date | date | no |  |
| status | varchar(20) | no | `draft` |
| manager_emp_id | uuid | yes |  |
| hr_emp_id | uuid | yes |  |
| outcome | text | yes |  |
| is_active | boolean | no | `true` |
| created_by | bigint | no |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |

- **Primary key:** pip_id
- **Indexes:** cycle_id; employee_id; status
- **Checks:** ((end_date > start_date)); (((status)::text = ANY ((ARRAY['draft'::character varying, 'active'::character varying, 'monitoring'::character varying, 'completed'::character varying, 'failed'::character varying, 'cancelled'::character varying])::text[])))

### `key_results`

| Column | Type | Null | Default |
|---|---|---|---|
| kr_id 🔑 | uuid | no | `gen_random_uuid()` |
| goal_id | uuid | no |  |
| description | varchar(500) | no |  |
| metric_type | varchar(20) | no |  |
| currency_code | char(3) | no | `EGP` |
| start_value | numeric(15,2) | no | `0` |
| target_value | numeric(15,2) | no |  |
| current_value | numeric(15,2) | no | `0` |
| progress_pct | numeric(5,2) | no | `0` |
| is_active | boolean | no | `true` |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| created_by | bigint | yes |  |

- **Primary key:** kr_id
- **Foreign keys:** `goal_id` → `goals.goal_id` (on delete CASCADE)
- **Indexes:** goal_id
- **Checks:** (((metric_type)::text = ANY ((ARRAY['number'::character varying, 'percentage'::character varying, 'currency'::character varying, 'boolean'::character varying])::text[]))); (((progress_pct >= (0)::numeric) AND (progress_pct <= (100)::numeric)))

### `kpi_assignments`

| Column | Type | Null | Default |
|---|---|---|---|
| assignment_id 🔑 | uuid | no | `gen_random_uuid()` |
| kpi_id | uuid | no |  |
| assignee_type | varchar(20) | no |  |
| assignee_id | uuid | no |  |
| cycle_id | uuid | yes |  |
| weight_pct | numeric(5,2) | no | `0` |
| target_value | numeric(15,2) | yes |  |
| currency_code | char(3) | no | `EGP` |
| threshold_min | numeric(15,2) | yes |  |
| threshold_max | numeric(15,2) | yes |  |
| period | varchar(7) | yes |  |
| status | varchar(20) | no | `active` |
| is_active | boolean | no | `true` |
| created_by | bigint | no |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |

- **Primary key:** assignment_id
- **Foreign keys:** `kpi_id` → `kpi_library.kpi_id` (on delete RESTRICT)
- **Indexes:** assignee_type, assignee_id; cycle_id; kpi_id
- **Checks:** (((assignee_type)::text = ANY ((ARRAY['employee'::character varying, 'role'::character varying, 'dept'::character varying])::text[]))); (((status)::text = ANY ((ARRAY['active'::character varying, 'inactive'::character varying, 'archived'::character varying])::text[]))); (((weight_pct >= (0)::numeric) AND (weight_pct <= (100)::numeric)))

### `kpi_library`

| Column | Type | Null | Default |
|---|---|---|---|
| kpi_id 🔑 | uuid | no | `gen_random_uuid()` |
| kpi_code | varchar(30) | no |  |
| kpi_name | varchar(200) | no |  |
| kpi_name_local | varchar(200) | no |  |
| category | varchar(50) | no |  |
| unit | varchar(50) | yes |  |
| direction | varchar(20) | no |  |
| measurement_type | varchar(20) | no |  |
| formula | text | yes |  |
| data_source | varchar(100) | yes |  |
| description | text | yes |  |
| is_active | boolean | no | `true` |
| created_by | bigint | no |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |

- **Primary key:** kpi_id
- **Unique:** (kpi_code)
- **Indexes:** category; is_active; kpi_code
- **Checks:** (((direction)::text = ANY ((ARRAY['higher_better'::character varying, 'lower_better'::character varying, 'exact'::character varying])::text[]))); (((measurement_type)::text = ANY ((ARRAY['number'::character varying, 'percentage'::character varying, 'currency'::character varying, 'ratio'::character varying, 'boolean'::character varying])::text[])))

### `review_cycles`

| Column | Type | Null | Default |
|---|---|---|---|
| cycle_id 🔑 | uuid | no | `gen_random_uuid()` |
| cycle_name | varchar(200) | no |  |
| cycle_name_local | varchar(200) | yes |  |
| cycle_type | varchar(30) | no |  |
| period_start | date | no |  |
| period_end | date | no |  |
| phases_json | jsonb | yes |  |
| rating_scale | smallint | no | `5` |
| status | varchar(30) | no | `draft` |
| is_active | boolean | no | `true` |
| created_by | bigint | no |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |

- **Primary key:** cycle_id
- **Indexes:** status; cycle_type
- **Checks:** ((period_end > period_start)); (((status)::text = ANY ((ARRAY['draft'::character varying, 'active'::character varying, 'self_review'::character varying, 'manager_review'::character varying, 'calibration'::character varying, 'completed'::character varying, 'closed'::character varying])::text[]))); (((cycle_type)::text = ANY ((ARRAY['annual'::character varying, 'semi_annual'::character varying, 'quarterly'::character varying, 'probation'::character varying, 'project'::character varying])::text[]))); (((rating_scale >= 3) AND (rating_scale <= 10)))

---
