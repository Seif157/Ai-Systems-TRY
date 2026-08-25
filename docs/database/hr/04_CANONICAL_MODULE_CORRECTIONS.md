# Canonical Module Corrections

This document defines the final V2 changes to the complete table inventory in `modules/`. Unmentioned base columns remain, but all global standards still apply. “Replace” and “deprecate” instructions are normative.

## 1. OrganizationBranch

### `organization_branches`

- Add `legal_entity_id uuid NOT NULL` FK to `legal_entities`, `ON DELETE RESTRICT`.
- Add `timezone varchar(64) NOT NULL`; default may be copied from the legal entity during migration but must be stored explicitly when branches can differ.
- Change `country_code` to `char(2)`.
- Replace global `UNIQUE(branch_code)` with `UNIQUE(legal_entity_id, branch_code)`.
- Add FK `manager_emp_id -> employees.employee_id ON DELETE SET NULL` after the employee table is available.
- Enforce that a parent branch belongs to the same legal entity using `(legal_entity_id,parent_branch_id)` composite ownership validation.
- Prevent `parent_branch_id = branch_id` and hierarchy cycles with a deferred constraint trigger.
- Encrypt and hash `tax_id` according to the Restricted-data standard.

## 2. BranchDepartment

### `branch_departments`

- Replace global `UNIQUE(dept_code)` with `UNIQUE(branch_id, dept_code)`.
- Add FK `manager_emp_id -> employees.employee_id ON DELETE SET NULL`.
- Enforce that `parent_dept_id` belongs to the same branch and is not self; reject hierarchy cycles.
- Add `CHECK (headcount_filled <= headcount_budget)`.
- Add generated `headcount_vacant integer GENERATED ALWAYS AS (headcount_budget-headcount_filled) STORED`.
- Treat counters as caches; reconcile them from active positions and employee assignments.
- Resolve the circular department/cost-center link in staged migrations; both final FKs are `RESTRICT`/`SET NULL`, never cascade.

## 3. CostCenter

### `cost_centers`

- Add `legal_entity_id uuid NOT NULL`.
- Change `currency_code` to `char(3)`.
- Replace `UNIQUE(cc_code,fiscal_year)` with `UNIQUE(legal_entity_id,cc_code,fiscal_year)`.
- Ensure linked branch and department belong to the same legal entity.
- Ensure a child cost center has the same legal entity and fiscal year as its parent unless an explicitly approved carry-forward mapping exists.
- Add checks for valid currency, nonnegative budget, and valid fiscal year.

## 4. JobCatalog

### `job_catalog`

- Add `legal_entity_id uuid NOT NULL`.
- Replace `UNIQUE(job_code)` with `UNIQUE(legal_entity_id,job_code)`.
- Rename `job_category` to `employment_type` because its allowed values describe employment type, not job classification.
- Normalize skills through `role_skill_requirements`; keep `skills_required` only as a human-readable summary.
- Enforce that the referenced grade belongs to the same legal entity.

## 5. JobGrade

### `job_grades`

- Add `legal_entity_id uuid NOT NULL`.
- Change `currency_code` to `char(3)`.
- Replace `UNIQUE(grade_code)` with `UNIQUE(legal_entity_id,grade_code)`.
- Keep `min_salary <= mid_salary <= max_salary` and all amounts nonnegative.
- Deprecate `annual_leave_days` and `sick_leave_days` as entitlement sources. `leave_policies` is authoritative. These fields may remain temporarily as read-only migration inputs, then be removed.

## 6. Position

### `positions`

- Add `legal_entity_id uuid NOT NULL` and enforce ownership of branch, department, job, grade, and cost center.
- Replace `UNIQUE(position_code)` with `UNIQUE(legal_entity_id,position_code)`.
- Add `CHECK (headcount_filled <= headcount_budget)`.
- Make `headcount_vacant` generated, non-null, and read-only.
- Add a deferred reconciliation that compares `headcount_filled` with current employee-position assignments.
- Prevent overlapping active effective versions for the same position code.

## 7. Employee

### `employees`

- Add `legal_entity_id uuid NOT NULL`.
- Add ERP-maintained `display_name varchar(200) NOT NULL` and
  `profile_freshness_at timestamptz NOT NULL`. AI clients never assemble names or fall back to
  `updated_at`; freshness changes whenever any exposed profile value changes.
- Replace global employee-number uniqueness with `UNIQUE(legal_entity_id,employee_number)`.
- Enforce case-insensitive `UNIQUE(legal_entity_id,lower(email_work))`.
- Store `national_id`, `passport_number`, personal email, phone, address, religion, blood type, and other Restricted fields encrypted where required.
- Add deterministic keyed hashes for exact lookup of national ID and passport; uniqueness is applied to the hash in the chosen legal-entity scope.
- Add FK `manager_id -> employees.employee_id ON DELETE SET NULL` and `CHECK (manager_id IS NULL OR manager_id <> employee_id)`.
- Validate that branch, department, position, grade, manager, and cost center belong to the same legal entity.
- Add lifecycle fields `archived_at`, `archived_by_user_id`, `archive_reason`, `anonymized_at`.
- Block physical employee deletion for application roles.
- Define `employment_status` as the authoritative lifecycle state; `is_active` is derived or removed to prevent contradictory states.
- Dates must satisfy birth < hire, seniority <= hire unless imported exception is documented, confirmation >= hire, termination >= hire.

### `onboarding_task_completions`

- Add missing FK `employee_id -> employees.employee_id ON DELETE RESTRICT`.
- Keep `UNIQUE(employee_id,template_id)`.
- Record `completed_by_user_id`; completion is history and cannot be physically deleted.

### `onboarding_task_templates`

- Replace the hard-coded 1/30/90 CHECK with configurable milestones or a positive-day check.
- Version templates so historical onboarding records retain their original meaning.

### `employee_export_jobs`

- Add structured, versioned `filter_snapshot jsonb` with a JSON Schema.
- Replace raw `file_path` with `file_id` FK to `hr_secure_files`.
- Record purpose, requested fields, classification, expiry, download count, and audit events.

## 8. EmployeeContract

### `employee_contracts`

- Preserve the existing partial unique index allowing one `is_current=TRUE` row per employee.
- Add a PostgreSQL exclusion constraint preventing overlapping active contract periods for the same employee.
- Add `legal_entity_id` and enforce ownership of all referenced organization fields.
- Replace `file_path` with secure `file_id`.
- Add nonnegative checks for hours, probation, notice, and renewal count.
- Require `end_date IS NULL` when open-ended; require a non-null end date for fixed-term types.
- Final approved contracts are immutable; amendments create a new version and link through `supersedes_contract_id`.
- Keep a full `employee_id` history index even when a partial current index exists.

## 9. EmployeeOperations

### `employee_operations`

- Add FKs for every origin/target branch, department, position, grade, cost center, and manager reference.
- Enforce legal-entity ownership for every origin and target reference.
- Version and validate `changes_applied`, `warnings`, `next_steps`, `final_settlement`, and `before_state` JSONB.
- Require operation-specific fields through constraint triggers: transfer requires target organization fields; promotion requires target grade/position; termination requires termination type/reason.
- Reversal creates an immutable compensating operation; it does not update the original operation payload.

### `eo_settlement_documents`

- Add FK `employee_id -> employees.employee_id ON DELETE RESTRICT`.
- Replace `pdf_path` with `file_id`.
- Add `currency_code char(3)` and nonnegative amount checks.
- Store the calculation version and source snapshot/checksum.

### `eo_settlement_access_log`

- Rename `accessed_by` to `accessed_by_user_id bigint`.
- Do not cascade-delete access logs with documents; use `ON DELETE RESTRICT` and retention-managed secure files.

## 10. EmployeeDocuments

### `employee_documents`

- Replace `file_path`, `file_type`, and `file_size_kb` with `file_id` FK to `hr_secure_files` while retaining document business metadata.
- Change issuing country to `char(2)`.
- Add verification consistency: verified records require verifier/date; unverified records cannot have a verification date.
- Add nonnegative alert days and valid date checks.
- Consider partial uniqueness for identifiers such as active passport/national-ID document numbers after encrypted hash fields are added.
- Never cascade document history with an employee deletion.

## 11. EmergencyContacts

### `emergency_contacts`

- Add partial `UNIQUE(employee_id) WHERE is_primary=TRUE AND is_active=TRUE`.
- Encrypt contact national ID, phone, email, and address according to classification.
- Normalize phone values for lookup while retaining the entered display value.
- Employee deletion behavior is `RESTRICT`; privacy erasure follows employee anonymization policy.

## 12. EmployeeChangeRequest

### `employee_change_requests`

- Rename `decided_by` to `decided_by_user_id bigint` with user FK.
- Replace arbitrary `field_name` with an approved field registry or checked field key.
- Store typed old/new values using versioned JSON, encrypting sensitive values; audit logs must not copy plaintext secrets.
- Approved changes and the target-row update occur in one transaction with row-version checking.
- Require decision actor/time/note consistently for approved or rejected states.

## 13. Leave

### `leave_types`

- Add `legal_entity_id uuid NOT NULL`.
- Change `color_hex` to `char(7)`.
- Replace global leave-code uniqueness with `UNIQUE(legal_entity_id,leave_code)`.

### `leave_policies`

- Add `legal_entity_id`, `policy_code`, `version`, `effective_from`, `effective_to`, `jurisdiction_country_code char(2)`, and `priority`.
- Replace implicit current-policy logic with non-overlapping effective versions for the same code/scope.
- Enforce scope consistency: `all` requires null scope ID; grade and department require a valid owned ID. Prefer explicit nullable `job_grade_id`/`dept_id` FKs over a polymorphic `scope_id`.
- Extend scoping to employment type and branch only when there is a documented business requirement.
- Define deterministic precedence and reject equal-priority conflicts.
- `leave_policies.annual_entitlement_days` is the sole entitlement source.

### `leave_balances`

- Add `UNIQUE(employee_id,leave_type_id,fiscal_year)`.
- Add immutable `legal_entity_id uuid NOT NULL` plus composite ownership constraints for employee
  and leave type.
- Add stored `available_days numeric(7,2) NOT NULL`, `calculated_at timestamptz NOT NULL`,
  `source_watermark varchar(128) NOT NULL`, and `calculation_version varchar(64) NOT NULL`, with no
  metadata defaults. Availability may be negative and is never reconstructed by an AI reader.
- Treat balance columns as a cache of the authoritative leave ledger.
- Add `calculated_at`, `source_watermark`, and `calculation_version`.
- Add consistency checks: all components nonnegative unless policy allows negative available balance; pending/used cannot silently exceed authorized amounts.

### `leave_ledger_entries` — new authoritative table

Required columns: ledger entry ID, employee, leave type, effective date, entry type, signed days, source type/ID, fiscal year, balance-after snapshot, created actor/time, correlation ID, reversal reference.

- Unique idempotency key/source tuple prevents double accrual or double usage.
- Entries are append-only. Corrections use reversal entries.
- Accrual logs and adjustments become specialized source records that produce ledger entries.

### `leave_accrual_logs`

- Enforce that `balance_id` belongs to the same employee, leave type, and fiscal year using a composite FK/trigger.
- Add an idempotency uniqueness rule for each accrual run, employee, type, and date.

### `leave_adjustments`

- Rename actor to `adjusted_by_user_id`; require approval for configured thresholds.
- Every adjustment produces exactly one ledger entry.

### `leave_requests`

- Add immutable `legal_entity_id uuid NOT NULL` plus composite ownership constraints for employee
  and leave type.
- Add immutable `submitted_at timestamptz NOT NULL` and
  `working_days_calculation_version varchar(64) NOT NULL`. Canonical rows are submitted requests;
  drafts are outside the AI read contract. Submission time is never inferred from `created_at`.
- Compute `working_days` in the domain service from the applicable work calendar and persist a calculation snapshot/version.
- Add half-day consistency checks: half-day requires one-day range, valid period, and 0.5 working day; non-half-day requires null period.
- Add an exclusion/validated trigger preventing overlapping pending/approved requests for the same employee, while allowing explicitly configured partial-day combinations.
- Standardize approval FK and reviewer actor IDs.
- Every status transition is recorded; approved/cancelled changes produce ledger entries transactionally.
- Replace medical-certificate paths with secure file IDs.

### Calendars

- Deprecate global `working_day_calendars` in favor of `work_calendars` and `working_calendar_days` from the foundation schema.
- Calendar resolution order is employee override, branch, legal entity, then jurisdiction default.

## 14. TimeAttendance

### `attendance_punches` — new authoritative table

Record each raw clock event with employee, event time, resolved local date/timezone, punch type, source, device, location, integrity status, correlation/idempotency key, and immutable ingestion metadata.

- Raw punches are append-only.
- Location is Restricted and retained only for the approved period.
- Device and mobile sources require anti-replay identifiers.

### `attendance_records`

- Treat this as a calculated daily/shift summary, not the raw source.
- Replace `UNIQUE(employee_id,attendance_date)` with `UNIQUE(employee_id,attendance_date,shift_id)` to support split shifts; define a null-shift strategy explicitly.
- Add nonnegative checks and clock ordering that correctly handles overnight shifts.
- Record `calculated_at`, source watermark, and calculation version.
- Employee delete behavior is `RESTRICT`, not cascade.

### `attendance_summaries`

- Keep unique employee/year/month.
- Mark as cache and add calculation metadata.
- Reconcile component day counts and prevent negative totals.

### `work_shifts`

- Add legal entity, timezone, applicable calendar, and version/effective dates.
- Add valid geofence ranges and nonnegative duration thresholds.
- Use `work_shift_days` child rows for weekday patterns, planned minutes, and breaks.

### `shift_assignments`

- Add exclusion constraint preventing overlapping active assignments for one employee unless multi-shift scheduling is explicitly enabled.
- Check effective end >= start and use `RESTRICT` on employee/shift history.

### `overtime_requests`

- Add missing approval and reviewer FKs.
- Require positive requested minutes and `0 <= approved_minutes <= requested_minutes`.
- Approved records are immutable; corrections use cancellation/replacement.

## 15. Salary and Compensation

### `pay_components` — new configuration table

Define earning/deduction codes, names, type, taxability, recurrence, calculation method, default currency behavior, accounting mapping, effective dates, and active state. Codes are unique per legal entity.

### `salary`

- Preserve one-current partial unique index and add a full employee-history index.
- Add non-overlap exclusion for active effective periods.
- Add `legal_entity_id`, calculation version, approval workflow, and immutable approved versions.
- Retain `basic_salary`; deprecate hard-coded allowance columns after migrating them to `salary_components`.
- Keep generated `gross_salary` only if it sums canonical component values in the same row; otherwise calculate from approved salary components and snapshot the result.
- Remove `net_salary` as a compensation-package source. Net pay belongs to an immutable payslip period.
- Move bank details to `employee_payment_methods`.
- Rename `approved_by` to `approved_by_user_id bigint`.
- Check all amounts nonnegative and percentages within 0–100.

### `salary_components` — new child table

Columns include salary ID, component ID, amount/rate/formula snapshot, currency, effective dates, and source. Unique active component per salary package unless multiple lines are explicitly supported.

### `employee_payment_methods` — new Restricted table

Store employee, method type, encrypted account/IBAN/wallet data, keyed hashes, beneficiary name, bank metadata, effective dates, primary flag, verification status, and secure audit information. Enforce one current primary payment method.

## 16. AccountingSalary

### `accounting_salary`

- Replace textual `pay_period` with `pay_period_id`.
- Change currency to `char(3)`.
- Add legal-entity ownership and unique `(cost_centre_id,pay_period_id)`.
- Add nonnegative checks and reconciliation: gross, net, allowances, deductions, and employer contributions must match locked source snapshots.
- Replace textual `posted_by` with `posted_by_user_id bigint` or immutable external-finance actor metadata.
- Posted rows are locked. Reversal creates a linked reversal posting.
- Treat GL/journal fields as Finance integration output, not HR-owned mutable data.

## 17. PayrollGaps

### All PayrollGaps tables

- Add missing employee FKs with `ON DELETE RESTRICT`.
- Standardize all approval columns to `approval_request_id` after verifying they represent workflow requests.
- Replace period strings with `pay_period_id`.
- Change currency fields to `char(3)`.
- Enforce positive amounts and valid state transitions.

### `pg_loans`

- Checks: principal > 0; installments > 0; installment amount > 0; remaining between 0 and principal.
- Add consistency/reconciliation for schedule totals and remaining amount.
- Loan schedules are unique by `(loan_id,pay_period_id)`.

### `pg_expense_claims`

- Replace receipt path with secure file ID.
- Add legal-entity/currency ownership, positive amount, and immutable paid state.

### `pg_bonuses`

- Require positive amount and component/source code.
- An approved bonus can be injected once per pay period using an idempotent source key.

### `pg_payroll_injections`

- Preserve unique source idempotency, now including pay period.
- Validate that the source record belongs to the same employee and period through a trigger/application invariant.
- Included/sent rows are immutable.

## 18. Payslip

### `ps_payslip_documents`

- Add FK `employee_id -> employees ON DELETE RESTRICT`.
- Replace textual period with `pay_period_id`.
- Add `legal_entity_id`, `currency_code char(3)`, `document_version`, `calculation_version`, `supersedes_payslip_id`, and checksum.
- Replace `pdf_path` with secure `file_id`.
- Published/sent payslips are immutable. Corrections create a new version or reversal.
- Unique active published version per employee/pay period; preserve all historical versions.

### `ps_payslip_lines` — new immutable table

Store payslip, component code/name snapshot, direction, quantity, rate, amount, currency, taxable/insurable flags, source type/ID, display order, and calculation metadata.

- Amounts are nonnegative; direction defines addition/deduction.
- Lines and header totals reconcile exactly before publication.

### `ps_payslip_access_log`

- Rename actor to `accessed_by_user_id`.
- Do not cascade-delete access evidence.
- Record access purpose, device/session correlation, and outcome.

## 19. ServiceRequests

### `sr_letter_templates`

- Replace global `UNIQUE(code)` with `UNIQUE(code,version)`.
- Add effective dates, status, and immutable published versions.
- Sanitize template rendering; template variables come from an allowlist.

### `sr_request_types`

- Add FK to letter template/version.
- Add versioned `payload_schema jsonb`, allowed-role policy, and output contract.

### `sr_requests`

- Add FKs for employee, approval, assignee, and output document.
- Remove duplicated mutable `category`; derive it from the request type or validate equality.
- Validate payload against the request-type schema.
- Add status history, assignment history, SLA pause periods, and idempotency key.

### `sr_generated_letters`

- Add FK to request and replace PDF path with secure file ID.
- Add template version, context checksum, and generation correlation ID.
- Unique reference numbers reserve their value permanently.

## 20. Performance

### All Performance tables

- Add every missing employee, reviewer, facilitator, cycle, grade, goal, KPI, approval, and competency FK.
- Employee and reviewer delete behavior is `RESTRICT` for historical records.
- Scores must be between zero and the cycle rating scale; enforce through validated service/trigger logic.
- Weighted collections must total 100 before submission/finalization.
- Finalized and acknowledged appraisals are immutable; calibration creates explicit before/after evidence.
- Performance, feedback, calibration, succession, and PIP data is Highly Restricted.

### `appraisal_ratings`

- Enforce one item per appraisal/type/id.
- Validate polymorphic item ownership and active cycle membership.

### `appraisals` and `cycle_participants`

- Define `appraisals` as the score/result aggregate and `cycle_participants` as enrollment/workflow assignment; synchronize transitions transactionally to prevent status drift.

### `goals`

- Add employee, cycle, and approval FKs; date and parent-cycle ownership checks.
- Prevent goal hierarchy cycles.

### `feedback_requests` and `feedback_responses`

- Add subject/rater employee FKs and prevent invalid self/relationship combinations.
- Enforce anonymity at the authorization/query layer; do not expose rater identity through AI tools.

### `kpi_assignments` and polymorphic scopes

- Prefer explicit employee, role, and department assignment tables. If polymorphism remains, use an integrity trigger and document owner scope.
- Change currency to `char(3)` and replace weak period strings with a referenced measurement period.

### `improvement_plans`

- Add all employee/cycle/manager/HR FKs, milestone child records, status history, and Restricted access policy.

## 21. Recruitment

### `rec_candidates`

- Add legal entity and case-insensitive candidate email identity rules; support explicit duplicate/merge workflows.
- Add consent version, consent source, withdrawn date, retention-until date, anonymized date, and lawful-purpose code.
- Replace CV path with secure file ID.
- Add employee FKs for internal applicant/referrer when present.

### `rec_job_requisitions`

- Add legal entity, branch, hiring-manager FK, approval FK, `CHECK(headcount>0)`, and `CHECK(0<=filled_count<=headcount)`.
- Reconcile filled count from hired applications.

### `rec_pipeline_stages`

- Add `UNIQUE(requisition_id,sequence_order)` and a stage-code uniqueness rule.
- Default stages are copied/versioned into each requisition so historical pipelines are stable.

### `rec_application_stage_history` — new append-only table

Record application, from/to stage, status, actor, reason, score snapshot, occurred time, and correlation ID.

- Validate that every stage belongs to the application's requisition.
- `current_stage_id` is a cache of the latest history event.

### `rec_interviews`

- Add interviewer employee FK and validate stage/application requisition ownership.
- Add interview-panel child rows for multiple interviewers and per-interviewer feedback.
- Prevent impossible schedules where a configured resource is already booked.

### `rec_offers`

- Change currency to `char(3)` and enforce positive salary.
- Replace `UNIQUE(application_id)` with versioned offers and one-current partial uniqueness.
- Add approval FK, secure generated document, expiry/acceptance consistency, and immutable accepted state.
- Candidate-to-employee conversion records the resulting employee ID and is idempotent.

## 22. Talent

### All Talent tables

- Add missing employee, grade, position, and approval FKs.
- Promotion and succession information is Highly Restricted.

### `tal_career_paths`

- Add legal entity, uniqueness for from/to grade pair, positive tenure, and `from_grade_id <> to_grade_id`.
- Normalize required competencies to child rows rather than unvalidated JSON.

### `tal_employee_criterion_progress`

- Add employee FK, 0–100 progress check, nonnegative gaps, and states `not_met`, `in_progress`, `met`, `waived`.

### `tal_promotion_cases`

- Add current/proposed grade, employee, target-position, and approval FKs.
- Add `currency_code char(3)`, nonnegative salaries, one active case per employee/target path, and immutable applied state.

### `tal_succession_candidates`

- Add candidate employee FK.
- Add `UNIQUE(position_id,candidate_employee_id)` and `UNIQUE(position_id,rank)` for active records.
- Require positive rank and status/history for readiness changes.

### `tal_promotion_nominations`

- Add employee and nominator-user FKs and duplicate-nomination rules for a defined cycle/period.

## 23. Training

### All Training tables

- Add all missing employee, trainer, assessor, owner, grade, and approval FKs.
- Add legal-entity ownership where programs/courses are not company-global.
- Counts are calculated caches with reconciliation metadata.

### `course_modules`

- Add `UNIQUE(course_id,sequence_order)`, positive duration, and secure file references for protected materials.

### `course_prerequisites`

- Add `CHECK(course_id <> prerequisite_course_id)` and reject dependency cycles.

### `employee_skills`

- Add employee and assessor FKs; record assessment method/evidence/history rather than overwriting the only level.

### `program_cohorts`

- Check end >= start, capacity positive, and enrolled count within capacity.

### `program_enrollments`

- Add employee and approval FKs.
- Enforce that cohort belongs to program using a composite FK.
- Replace `UNIQUE(program_id,employee_id)` with a rule that permits a new cohort/version enrollment after withdrawal/completion while preventing duplicate active enrollment.

### `training_sessions`

- Add trainer employee FK, valid capacity/count checks, and timezone-aware scheduling.
- Enforce cohort/course/program ownership.

### `session_enrollments` and `session_attendances`

- Add employee, approver, marker FKs.
- Attendance requires a corresponding enrollment unless an approved walk-in exception is recorded.
- Waitlist position is positive and unique per session for active waitlisted records.

### `certifications`

- Add employee FK and secure certificate file.
- Allow nullable course for externally earned certifications; require issuer/evidence in that case.
- Check expiry > obtained date and derive expiry status rather than manually drifting it.

### `role_skill_requirements`

- Add job-grade FK and consider job/position-level requirements where grade alone is insufficient.

### `training_feedbacks`

- Add employee FK and enforce that only an attended/completed participant can submit one feedback record.
