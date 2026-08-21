<!-- Module: Recruitment | Domain: HR | Split from DATABASE_SCHEMA.md -->

> **Canonical V2 note:** Apply [global standards](../02_GLOBAL_SCHEMA_STANDARDS.md) and this subdomain's final rules in [canonical module corrections](../04_CANONICAL_MODULE_CORRECTIONS.md). Those rules override this generated base definition.

## Recruitment

### `rec_applications`

| Column | Type | Null | Default |
|---|---|---|---|
| application_id 🔑 | uuid | no | `gen_random_uuid()` |
| requisition_id | uuid | no |  |
| candidate_id | uuid | no |  |
| current_stage_id | uuid | no |  |
| status | varchar(20) | no | `active` |
| rejection_reason | varchar(255) | yes |  |
| score | numeric(4,1) | yes |  |
| applied_at | timestamptz | no |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| cover_note | text | yes |  |
| is_active | boolean | no | `true` |
| created_by | bigint | yes |  |

- **Primary key:** application_id
- **Foreign keys:** `candidate_id` → `rec_candidates.candidate_id` (on delete RESTRICT); `current_stage_id` → `rec_pipeline_stages.stage_id` (on delete RESTRICT); `requisition_id` → `rec_job_requisitions.requisition_id` (on delete RESTRICT)
- **Unique:** (requisition_id, candidate_id)
- **Indexes:** status; requisition_id, candidate_id
- **Checks:** (((status)::text = ANY ((ARRAY['active'::character varying, 'rejected'::character varying, 'withdrawn'::character varying, 'hired'::character varying])::text[])))

### `rec_candidates`

| Column | Type | Null | Default |
|---|---|---|---|
| candidate_id 🔑 | uuid | no | `gen_random_uuid()` |
| full_name | varchar(150) | no |  |
| email | varchar(150) | no |  |
| phone | varchar(30) | yes |  |
| source | varchar(30) | no |  |
| applicant_employee_id | uuid | yes |  |
| referred_by_employee_id | uuid | yes |  |
| cv_path | varchar(255) | yes |  |
| current_title | varchar(120) | yes |  |
| total_experience_years | numeric(4,1) | yes |  |
| gdpr_consent_at | timestamptz | yes |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |
| created_by | bigint | yes |  |

- **Primary key:** candidate_id
- **Indexes:** email
- **Checks:** (((source)::text = ANY ((ARRAY['internal'::character varying, 'referral'::character varying, 'portal'::character varying, 'agency'::character varying, 'linkedin'::character varying, 'walk_in'::character varying])::text[])))

### `rec_interviews`

| Column | Type | Null | Default |
|---|---|---|---|
| interview_id 🔑 | uuid | no | `gen_random_uuid()` |
| application_id | uuid | no |  |
| stage_id | uuid | no |  |
| interviewer_id | uuid | yes |  |
| scheduled_at | timestamptz | no |  |
| mode | varchar(15) | no |  |
| status | varchar(15) | no | `scheduled` |
| feedback | text | yes |  |
| rating | integer | yes |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |
| created_by | bigint | yes |  |

- **Primary key:** interview_id
- **Foreign keys:** `application_id` → `rec_applications.application_id` (on delete RESTRICT); `stage_id` → `rec_pipeline_stages.stage_id` (on delete RESTRICT)
- **Indexes:** application_id
- **Checks:** (((mode)::text = ANY ((ARRAY['onsite'::character varying, 'online'::character varying, 'phone'::character varying])::text[]))); (((rating IS NULL) OR ((rating >= 1) AND (rating <= 5)))); (((status)::text = ANY ((ARRAY['scheduled'::character varying, 'done'::character varying, 'no_show'::character varying, 'cancelled'::character varying])::text[])))

### `rec_job_requisitions`

| Column | Type | Null | Default |
|---|---|---|---|
| requisition_id 🔑 | uuid | no | `gen_random_uuid()` |
| requisition_no | varchar(30) | no |  |
| job_id | uuid | no |  |
| dept_id | uuid | yes |  |
| hiring_manager_id | uuid | yes |  |
| headcount | integer | no |  |
| filled_count | integer | no | `0` |
| status | varchar(20) | no | `draft` |
| visibility | varchar(15) | no | `external` |
| location_label | varchar(120) | yes |  |
| employment_type | varchar(20) | yes |  |
| approval_id | uuid | yes |  |
| opened_at | timestamptz | yes |  |
| closed_at | timestamptz | yes |  |
| created_by | bigint | no |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |

- **Primary key:** requisition_id
- **Foreign keys:** `dept_id` → `branch_departments.dept_id` (on delete SET NULL); `job_id` → `job_catalog.job_id` (on delete RESTRICT)
- **Unique:** (requisition_no)
- **Indexes:** status; visibility; requisition_no
- **Checks:** (((employment_type IS NULL) OR ((employment_type)::text = ANY ((ARRAY['full_time'::character varying, 'part_time'::character varying, 'contract'::character varying, 'internship'::character varying, 'temporary'::character varying])::text[])))); (((status)::text = ANY ((ARRAY['draft'::character varying, 'pending_approval'::character varying, 'open'::character varying, 'on_hold'::character varying, 'closed'::character varying, 'cancelled'::character varying])::text[]))); (((visibility)::text = ANY ((ARRAY['internal'::character varying, 'external'::character varying, 'both'::character varying])::text[])))

### `rec_offers`

| Column | Type | Null | Default |
|---|---|---|---|
| offer_id 🔑 | uuid | no | `gen_random_uuid()` |
| application_id | uuid | no |  |
| offered_grade_id | uuid | yes |  |
| gross_salary | numeric(12,2) | no |  |
| currency_code | char(3) | no | `EGP` |
| start_date | date | no |  |
| status | varchar(20) | no | `draft` |
| approval_id | uuid | yes |  |
| expires_at | timestamptz | yes |  |
| accepted_at | timestamptz | yes |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |
| created_by | bigint | yes |  |

- **Primary key:** offer_id
- **Foreign keys:** `application_id` → `rec_applications.application_id` (on delete RESTRICT); `offered_grade_id` → `job_grades.job_grade_id` (on delete RESTRICT)
- **Unique:** (application_id)
- **Indexes:** status; application_id
- **Checks:** (((status)::text = ANY ((ARRAY['draft'::character varying, 'pending_approval'::character varying, 'approved'::character varying, 'sent'::character varying, 'accepted'::character varying, 'declined'::character varying, 'expired'::character varying])::text[])))

### `rec_pipeline_stages`

| Column | Type | Null | Default |
|---|---|---|---|
| stage_id 🔑 | uuid | no | `gen_random_uuid()` |
| requisition_id | uuid | yes |  |
| name_ar | varchar(60) | no |  |
| name_en | varchar(60) | no |  |
| sequence_order | integer | no |  |
| stage_type | varchar(20) | no |  |
| is_terminal | boolean | no | `false` |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |
| created_by | bigint | yes |  |

- **Primary key:** stage_id
- **Foreign keys:** `requisition_id` → `rec_job_requisitions.requisition_id` (on delete CASCADE)
- **Indexes:** requisition_id
- **Checks:** (((stage_type)::text = ANY ((ARRAY['screening'::character varying, 'interview'::character varying, 'assessment'::character varying, 'offer'::character varying, 'hired'::character varying, 'rejected'::character varying])::text[])))

---
