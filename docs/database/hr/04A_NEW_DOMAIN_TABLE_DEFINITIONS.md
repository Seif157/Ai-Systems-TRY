# New Domain Table Definitions

These tables complete the canonical V2 design. They follow all global audit, lifecycle, FK, security, and indexing rules.

## `leave_ledger_entries`

Authoritative append-only source for leave movements.

| Column | Type | Null | Default |
|---|---|---:|---|
| ledger_entry_id | uuid PK | no | `gen_random_uuid()` |
| employee_id | uuid | no | |
| leave_type_id | uuid | no | |
| policy_id | uuid | yes | |
| fiscal_year | smallint | no | |
| effective_date | date | no | |
| entry_type | varchar(30) | no | |
| days_delta | numeric(7,2) | no | |
| balance_after | numeric(7,2) | no | |
| source_type | varchar(40) | no | |
| source_id | uuid | yes | |
| reversal_of_entry_id | uuid | yes | |
| idempotency_key | varchar(100) | no | |
| reason | text | yes | |
| created_by_user_id | bigint | yes | |
| created_at | timestamptz | no | `now()` |
| correlation_id | uuid | no | |

- FKs: employee, leave type, policy, and self-reversal; all `RESTRICT`.
- Unique: `idempotency_key`; one reversal per original entry.
- Checks: nonzero delta; valid fiscal year; reversal cannot reference itself; entry type in `accrual`, `reserve`, `consume`, `release`, `adjustment`, `carry_forward`, `expiry`, `reversal`.
- Indexes: `(employee_id,leave_type_id,effective_date,created_at)`; `(source_type,source_id)`.
- UPDATE/DELETE revoked from application roles.

## `attendance_punches`

Immutable raw clock event.

| Column | Type | Null | Default |
|---|---|---:|---|
| punch_id | uuid PK | no | `gen_random_uuid()` |
| employee_id | uuid | no | |
| punch_at | timestamptz | no | |
| resolved_local_date | date | no | |
| timezone | varchar(64) | no | |
| punch_type | varchar(20) | no | |
| source | varchar(20) | no | |
| device_id | varchar(100) | yes | |
| latitude | numeric(10,7) | yes | |
| longitude | numeric(10,7) | yes | |
| accuracy_meters | numeric(8,2) | yes | |
| integrity_status | varchar(20) | no | `accepted` |
| idempotency_key | varchar(100) | no | |
| received_at | timestamptz | no | `now()` |
| created_by_user_id | bigint | yes | |
| correlation_id | uuid | no | |

- FK employee `ON DELETE RESTRICT`.
- Unique: `(source,idempotency_key)`.
- Checks: valid punch/source/integrity states; latitude -90..90; longitude -180..180; nonnegative accuracy.
- Indexes: `(employee_id,punch_at)`; `(employee_id,resolved_local_date)`.
- Location fields are Restricted and retained according to attendance policy.

## `work_shift_days`

| Column | Type | Null | Default |
|---|---|---:|---|
| shift_day_id | uuid PK | no | `gen_random_uuid()` |
| shift_id | uuid | no | |
| iso_weekday | smallint | no | |
| is_working_day | boolean | no | `true` |
| planned_start_time | time | yes | |
| planned_end_time | time | yes | |
| break_minutes | smallint | no | `0` |
| planned_minutes | smallint | no | `0` |
| created_at | timestamptz | no | `now()` |

- FK shift `ON DELETE CASCADE` only while the shift version is draft; activated versions use `RESTRICT` through application policy.
- Unique: `(shift_id,iso_weekday)`.
- Checks: weekday 1–7; nonnegative durations; working day requires start/end and positive planned minutes.

## `pay_components`

| Column | Type | Null | Default |
|---|---|---:|---|
| component_id | uuid PK | no | `gen_random_uuid()` |
| legal_entity_id | uuid | no | |
| component_code | varchar(30) | no | |
| component_name | varchar(150) | no | |
| component_name_local | varchar(150) | yes | |
| direction | varchar(10) | no | |
| component_type | varchar(30) | no | |
| calculation_method | varchar(30) | no | `fixed` |
| taxable | boolean | no | `false` |
| insurable | boolean | no | `false` |
| recurring | boolean | no | `true` |
| gl_account_code | varchar(50) | yes | |
| effective_from | date | no | |
| effective_to | date | yes | |
| is_active | boolean | no | `true` |
| created_by_user_id | bigint | no | |
| created_at | timestamptz | no | `now()` |
| updated_at | timestamptz | no | `now()` |
| row_version | bigint | no | `1` |

- Unique effective component code per legal entity.
- Direction: `earning`, `deduction`, `employer_contribution`.
- Calculation: `fixed`, `percentage`, `formula`, `quantity_rate`.
- Non-overlap for effective versions of the same component code.

## `salary_components`

| Column | Type | Null | Default |
|---|---|---:|---|
| salary_component_id | uuid PK | no | `gen_random_uuid()` |
| salary_id | uuid | no | |
| component_id | uuid | no | |
| amount | numeric(15,2) | yes | |
| percentage | numeric(5,2) | yes | |
| quantity | numeric(12,4) | yes | |
| rate | numeric(15,4) | yes | |
| currency_code | char(3) | no | |
| formula_snapshot | jsonb | yes | |
| created_at | timestamptz | no | `now()` |

- FKs salary/component `ON DELETE RESTRICT` after approval.
- Unique: `(salary_id,component_id)` unless the component definition explicitly allows multiple lines.
- Checks: nonnegative numeric inputs; percentage 0–100; exactly the required inputs for the component calculation method.
- Approved salary component rows are immutable.

## `employee_payment_methods`

Highly Restricted payment destination.

| Column | Type | Null | Default |
|---|---|---:|---|
| payment_method_id | uuid PK | no | `gen_random_uuid()` |
| employee_id | uuid | no | |
| method_type | varchar(20) | no | |
| beneficiary_name_encrypted | bytea | no | |
| bank_name | varchar(150) | yes | |
| account_number_encrypted | bytea | yes | |
| account_number_hash | bytea | yes | |
| iban_encrypted | bytea | yes | |
| iban_hash | bytea | yes | |
| wallet_number_encrypted | bytea | yes | |
| wallet_number_hash | bytea | yes | |
| currency_code | char(3) | yes | |
| is_primary | boolean | no | `false` |
| verification_status | varchar(20) | no | `unverified` |
| verified_by_user_id | bigint | yes | |
| verified_at | timestamptz | yes | |
| effective_from | date | no | |
| effective_to | date | yes | |
| created_by_user_id | bigint | no | |
| created_at | timestamptz | no | `now()` |
| row_version | bigint | no | `1` |

- FK employee `ON DELETE RESTRICT`.
- One current primary method per employee using an effective/current partial constraint.
- Checks: method-specific required fields; verification actor/time consistency; valid dates.
- Access and every read are audited.

## `ps_payslip_lines`

Immutable calculation snapshot line.

| Column | Type | Null | Default |
|---|---|---:|---|
| payslip_line_id | uuid PK | no | `gen_random_uuid()` |
| payslip_id | uuid | no | |
| component_code | varchar(30) | no | |
| component_name_snapshot | varchar(150) | no | |
| direction | varchar(10) | no | |
| quantity | numeric(12,4) | yes | |
| rate | numeric(15,4) | yes | |
| amount | numeric(15,2) | no | |
| currency_code | char(3) | no | |
| taxable | boolean | no | `false` |
| insurable | boolean | no | `false` |
| source_type | varchar(30) | yes | |
| source_id | uuid | yes | |
| calculation_metadata | jsonb | no | `'{}'` |
| display_order | smallint | no | `0` |
| created_at | timestamptz | no | `now()` |

- FK payslip `ON DELETE RESTRICT` after generation.
- Checks: positive/nonnegative amount as defined; valid direction; metadata schema version required.
- Header gross/deduction/net values must reconcile before publication.

## `rec_application_stage_history`

| Column | Type | Null | Default |
|---|---|---:|---|
| stage_history_id | uuid PK | no | `gen_random_uuid()` |
| application_id | uuid | no | |
| from_stage_id | uuid | yes | |
| to_stage_id | uuid | no | |
| from_status | varchar(20) | yes | |
| to_status | varchar(20) | no | |
| reason_code | varchar(50) | yes | |
| note | text | yes | |
| score_snapshot | numeric(5,2) | yes | |
| changed_by_user_id | bigint | no | |
| changed_at | timestamptz | no | `now()` |
| correlation_id | uuid | no | |

- FKs application/stages `ON DELETE RESTRICT`.
- Constraint trigger verifies stages belong to the application's requisition.
- Append-only; current application stage/status is updated in the same transaction.

## `rec_interview_panel_members`

| Column | Type | Null | Default |
|---|---|---:|---|
| panel_member_id | uuid PK | no | `gen_random_uuid()` |
| interview_id | uuid | no | |
| interviewer_employee_id | uuid | no | |
| panel_role | varchar(30) | no | `interviewer` |
| rating | numeric(4,2) | yes | |
| recommendation | varchar(20) | yes | |
| feedback | text | yes | |
| submitted_at | timestamptz | yes | |
| created_at | timestamptz | no | `now()` |

- Unique: `(interview_id,interviewer_employee_id)`.
- Checks: rating 1–5; submitted fields consistent.
- Feedback is Restricted and immutable after final submission except through an audited amendment.

## `rec_candidate_employee_conversions`

| Column | Type | Null | Default |
|---|---|---:|---|
| conversion_id | uuid PK | no | `gen_random_uuid()` |
| candidate_id | uuid | no | |
| application_id | uuid | no | |
| employee_id | uuid | no | |
| idempotency_key | varchar(100) | no | |
| converted_by_user_id | bigint | no | |
| converted_at | timestamptz | no | `now()` |
| correlation_id | uuid | no | |

- FKs candidate/application/employee `ON DELETE RESTRICT`.
- Unique candidate/application conversion, employee conversion, and idempotency key.
- Append-only.

## `tal_career_path_competencies`

| Column | Type | Null | Default |
|---|---|---:|---|
| path_competency_id | uuid PK | no | `gen_random_uuid()` |
| career_path_id | uuid | no | |
| competency_id | uuid | no | |
| required_level | smallint | no | |
| weight_pct | numeric(5,2) | no | `0` |
| is_mandatory | boolean | no | `true` |
| created_at | timestamptz | no | `now()` |

- Unique: `(career_path_id,competency_id)`.
- Checks: required level 1–5; weight 0–100; path weights validated before activation.

## `employee_skill_assessments`

Authoritative skill history; `employee_skills.current_level` is a current-state cache.

| Column | Type | Null | Default |
|---|---|---:|---|
| assessment_id | uuid PK | no | `gen_random_uuid()` |
| employee_id | uuid | no | |
| skill_id | uuid | no | |
| assessed_level | smallint | no | |
| assessment_source | varchar(20) | no | |
| assessor_employee_id | uuid | yes | |
| evidence_file_id | uuid | yes | |
| assessed_at | timestamptz | no | |
| expires_at | timestamptz | yes | |
| created_by_user_id | bigint | no | |
| correlation_id | uuid | no | |

- FKs employee, skill, assessor, secure file; all history-preserving.
- Checks: level 1–5; expiry after assessment; source-specific assessor/evidence requirements.
- Append-only; corrections create replacement assessments.

