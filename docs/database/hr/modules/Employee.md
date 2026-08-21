<!-- Module: Employee | Domain: HR | Split from DATABASE_SCHEMA.md -->

> **Canonical V2 note:** Apply [global standards](../02_GLOBAL_SCHEMA_STANDARDS.md) and this subdomain's final rules in [canonical module corrections](../04_CANONICAL_MODULE_CORRECTIONS.md). Those rules override this generated base definition.

## Employee

### `employee_export_jobs`

| Column | Type | Null | Default |
|---|---|---|---|
| export_job_id 🔑 | uuid | no | `gen_random_uuid()` |
| requested_by | bigint | no |  |
| format | varchar(10) | no |  |
| scope | varchar(20) | no |  |
| filename | varchar(150) | no |  |
| status | varchar(20) | no | `queued` |
| file_path | varchar(255) | yes |  |
| error_message | text | yes |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |

- **Primary key:** export_job_id
- **Checks:** (((format)::text = ANY ((ARRAY['xlsx'::character varying, 'csv'::character varying, 'pdf'::character varying])::text[]))); (((scope)::text = ANY ((ARRAY['all'::character varying, 'filtered'::character varying, 'selected'::character varying])::text[]))); (((status)::text = ANY ((ARRAY['queued'::character varying, 'processing'::character varying, 'completed'::character varying, 'failed'::character varying])::text[])))

### `employees`

| Column | Type | Null | Default |
|---|---|---|---|
| employee_id 🔑 | uuid | no | `gen_random_uuid()` |
| employee_number | varchar(20) | no |  |
| branch_id | uuid | yes |  |
| dept_id | uuid | yes |  |
| position_id | uuid | yes |  |
| job_grade_id | uuid | yes |  |
| manager_id | uuid | yes |  |
| cost_centre_id | uuid | yes |  |
| first_name | varchar(100) | no |  |
| middle_name | varchar(100) | yes |  |
| last_name | varchar(100) | no |  |
| first_name_local | varchar(100) | yes |  |
| last_name_local | varchar(100) | yes |  |
| national_id | varchar(50) | yes |  |
| national_id_type | varchar(20) | yes |  |
| passport_number | varchar(50) | yes |  |
| passport_expiry | date | yes |  |
| date_of_birth | date | yes |  |
| place_of_birth | varchar(100) | yes |  |
| gender | varchar(10) | yes |  |
| marital_status | varchar(20) | yes |  |
| nationality | varchar(3) | yes |  |
| religion | varchar(50) | yes |  |
| blood_type | varchar(5) | yes |  |
| email_work | varchar(200) | no |  |
| email_personal | varchar(200) | yes |  |
| phone_work | varchar(30) | yes |  |
| phone_mobile | varchar(30) | yes |  |
| phone_home | varchar(30) | yes |  |
| address_line1 | varchar(200) | yes |  |
| address_line2 | varchar(200) | yes |  |
| city | varchar(100) | yes |  |
| state | varchar(100) | yes |  |
| country | varchar(3) | yes |  |
| postal_code | varchar(20) | yes |  |
| employment_status | varchar(20) | no | `active` |
| employment_type | varchar(20) | no |  |
| hire_date | date | no |  |
| seniority_date | date | yes |  |
| confirmation_date | date | yes |  |
| termination_date | date | yes |  |
| termination_reason | text | yes |  |
| termination_type | varchar(30) | yes |  |
| is_active | boolean | no | `true` |
| photo_path | varchar(500) | yes |  |
| created_by | bigint | yes |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| locale | varchar(10) | yes |  |
| theme | varchar(20) | yes |  |
| eligible_for_rehire | boolean | yes |  |

- **Primary key:** employee_id
- **Foreign keys:** `branch_id` → `organization_branches.branch_id` (on delete SET NULL); `cost_centre_id` → `cost_centers.cost_centre_id` (on delete SET NULL); `dept_id` → `branch_departments.dept_id` (on delete SET NULL); `job_grade_id` → `job_grades.job_grade_id` (on delete SET NULL); `manager_id` → `employees.employee_id` (on delete SET NULL); `position_id` → `positions.position_id` (on delete SET NULL)
- **Unique:** (email_work); (employee_number); (national_id)
- **Indexes:** branch_id; date_of_birth; dept_id; email_work; employee_number; hire_date; is_active; job_grade_id; manager_id; national_id; position_id; hire_date
- **Checks:** (((blood_type IS NULL) OR ((blood_type)::text = ANY ((ARRAY['a+'::character varying, 'a-'::character varying, 'b+'::character varying, 'b-'::character varying, 'ab+'::character varying, 'ab-'::character varying, 'o+'::character varying, 'o-'::character varying])::text[])))); (((gender IS NULL) OR ((gender)::text = ANY ((ARRAY['male'::character varying, 'female'::character varying])::text[])))); (((date_of_birth IS NULL) OR (hire_date > date_of_birth))); (((marital_status IS NULL) OR ((marital_status)::text = ANY ((ARRAY['single'::character varying, 'married'::character varying, 'divorced'::character varying, 'widowed'::character varying])::text[])))); (((national_id_type IS NULL) OR ((national_id_type)::text = ANY ((ARRAY['national_id'::character varying, 'passport'::character varying, 'iqama'::character varying, 'work_permit'::character varying, 'other'::character varying])::text[])))); (((employment_status)::text = ANY ((ARRAY['active'::character varying, 'probation'::character varying, 'on_leave'::character varying, 'suspended'::character varying, 'terminated'::character varying, 'resigned'::character varying, 'retired'::character varying, 'inactive'::character varying])::text[]))); (((termination_date IS NULL) OR (termination_date >= hire_date))); (((termination_type IS NULL) OR ((termination_type)::text = ANY ((ARRAY['resignation'::character varying, 'termination'::character varying, 'retirement'::character varying, 'contract_end'::character varying, 'death'::character varying, 'redundancy'::character varying])::text[])))); (((employment_type)::text = ANY ((ARRAY['full_time'::character varying, 'part_time'::character varying, 'contract'::character varying, 'internship'::character varying, 'temporary'::character varying])::text[])))

### `onboarding_task_completions`

| Column | Type | Null | Default |
|---|---|---|---|
| completion_id 🔑 | uuid | no | `gen_random_uuid()` |
| employee_id | uuid | no |  |
| template_id | uuid | no |  |
| completed_at | timestamptz | yes |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |

- **Primary key:** completion_id
- **Foreign keys:** `template_id` → `onboarding_task_templates.template_id` (on delete CASCADE)
- **Unique:** (employee_id, template_id)
- **Indexes:** employee_id, template_id

### `onboarding_task_templates`

| Column | Type | Null | Default |
|---|---|---|---|
| template_id 🔑 | uuid | no | `gen_random_uuid()` |
| day_milestone | integer | no |  |
| title | varchar(150) | no |  |
| description | text | yes |  |
| sort_order | integer | no | `0` |
| is_active | boolean | no | `true` |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| created_by | bigint | yes |  |

- **Primary key:** template_id
- **Indexes:** day_milestone; is_active
- **Checks:** ((day_milestone = ANY (ARRAY[1, 30, 90])))

---
