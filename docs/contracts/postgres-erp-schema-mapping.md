# Reviewed PostgreSQL ERP provider mapping

This mapping is normative for Step 19. `LE` means the row's direct `legal_entity_id` must equal one
of the trusted legal-entity IDs in the SQL predicate. `EMP` means the row's direct `employee_id`
must equal the trusted linked employee. All joins are static and schema-qualified. Source documents
are `Employee.md` (E), `Leave.md` (L), `OrganizationBranch.md` (OB), `BranchDepartment.md` (BD),
`Position.md` (P), foundation/control tables (F), canonical corrections (C), and ERP-owner Decision
A recorded in `05A_STRUCTURED_AI_READ_CONTRACT.md` (A).

## Employee profile view

No row ordering is required because `(employee_id,legal_entity_id)` identifies at most one row.

| Provider field | Source | PostgreSQL type | Null | Join | Conditions | Docs |
|---|---|---|---:|---|---|---|
| employee_id | employees.employee_id | uuid | no | base | EMP+LE | E,C,A |
| legal_entity_id | employees.legal_entity_id | uuid | no | base | LE | C,A |
| employee_number | employees.employee_number | varchar(20) | no | base | EMP+LE | E |
| display_name | employees.display_name | varchar(200) | no | base | EMP+LE | A |
| work_email | employees.email_work | varchar(200) | no | base | EMP+LE | E |
| job_title | positions.position_title | varchar(200) | yes | employee.position_id and LE | same LE | P,A |
| department_name | branch_departments.dept_name | varchar(200) | yes | employee.dept_id and LE | same LE | BD,A |
| branch_name | organization_branches.branch_name | varchar(200) | yes | employee.branch_id and LE | same LE | OB,A |
| legal_entity_name | legal_entities.legal_name | varchar(250) | no | employee.legal_entity_id | LE | F,A |
| employment_status | employees.employment_status | varchar(20) | no | base | exact enum | E |
| hire_date | employees.hire_date | date | no | base | EMP+LE | E |
| manager_display_name | manager.display_name | varchar(200) | yes | employee.manager_id and LE | same LE | E,C,A |
| freshness_at | employees.profile_freshness_at | timestamptz | no | base | never updated_at | A |

## Leave balance view

Ordering is `fiscal_year, leave_type_code, legal_entity_id, leave_type_id`. The view joins leave type
on both ID and LE; composite FKs bind balance employee and leave type to LE.

| Provider field | Source | PostgreSQL type | Null | Join/conditions | Docs |
|---|---|---|---:|---|---|
| employee_id | leave_balances.employee_id | uuid | no | EMP+LE | L,C,A |
| legal_entity_id | leave_balances.legal_entity_id | uuid | no | LE | C,A |
| leave_type_id | leave_balances.leave_type_id | uuid | no | same-LE leave type | L,A |
| leave_type_code | leave_types.leave_code | varchar(20) | no | type ID+LE | L |
| leave_type_name | leave_types.leave_name | varchar(100) | no | type ID+LE | L |
| leave_type_name_local | leave_types.leave_name_local | varchar(100) | no | type ID+LE | L |
| fiscal_year | leave_balances.fiscal_year | smallint | no | EMP+LE | L |
| opening_days | leave_balances.opening_balance | numeric(7,2) | no | unchanged | L |
| accrued_days | leave_balances.accrued_ytd | numeric(7,2) | no | unchanged | L |
| used_days | leave_balances.used_ytd | numeric(7,2) | no | unchanged | L |
| pending_days | leave_balances.pending_ytd | numeric(7,2) | no | unchanged | L |
| available_days | leave_balances.available_days | numeric(7,2) | no | unchanged; negative allowed | A |
| calculated_at | leave_balances.calculated_at | timestamptz | no | cache freshness | C,A |
| source_watermark | leave_balances.source_watermark | varchar(128) | no | trimmed/nonblank | C,A |
| calculation_version | leave_balances.calculation_version | varchar(64) | no | full SemVer | C,A |

## Leave request view

Listing orders `submitted_at DESC, request_id ASC`; detail selects the strict request UUID. Both
also enforce EMP+LE. Drafts are excluded by the view.

| Provider field | Source | PostgreSQL type | Null | Join/conditions | Docs |
|---|---|---|---:|---|---|
| request_id | leave_requests.request_id | uuid | no | strict selector/keyset | L |
| employee_id | leave_requests.employee_id | uuid | no | EMP+LE | L,A |
| legal_entity_id | leave_requests.legal_entity_id | uuid | no | LE | A |
| leave_type_id | leave_requests.leave_type_id | uuid | no | same-LE leave type | L,A |
| leave_type_code | leave_types.leave_code | varchar(20) | no | type ID+LE | L |
| leave_type_name | leave_types.leave_name | varchar(100) | no | type ID+LE | L |
| leave_type_name_local | leave_types.leave_name_local | varchar(100) | no | type ID+LE | L |
| start_date | leave_requests.start_date | date | no | SQL date filters | L |
| end_date | leave_requests.end_date | date | no | stored | L |
| working_days | leave_requests.working_days | numeric(5,2) | no | stored; no arithmetic | L,C |
| is_half_day | leave_requests.is_half_day | boolean | no | stored | L |
| half_day_period | leave_requests.half_day_period | varchar(15) | yes | half-day invariant | L |
| status | leave_requests.status | varchar(20) | no | SQL status filter; no draft | L,A |
| submitted_at | leave_requests.submitted_at | timestamptz | no | immutable/order/ceiling | A |
| updated_at | leave_requests.updated_at | timestamptz | yes | stored | L |
| working_days_calculation_version | leave_requests.working_days_calculation_version | varchar(64) | no | full SemVer | C,A |

## Leave request history view

The view joins workflow history through an EMP+LE-filtered leave request, restricts entity type to
`leave_request`, and orders `changed_at ASC, history_id ASC` inside the same repeatable-read
transaction as detail.

| Provider field | Source | PostgreSQL type | Null | Join/conditions | Docs |
|---|---|---|---:|---|---|
| history_id | workflow_status_history.history_id | uuid | no | stable tie-breaker | F |
| entity_type | workflow_status_history.entity_type | varchar(80) | no | `leave_request` only | F |
| entity_id | workflow_status_history.entity_id | uuid | no | request_id alias | F |
| from_status | workflow_status_history.from_status | varchar(40) | yes | safe transition | F |
| to_status | workflow_status_history.to_status | varchar(40) | no | safe transition | F |
| changed_at | workflow_status_history.changed_at | timestamptz | no | ascending order | F |
| reason_code | workflow_status_history.reason_code | varchar(50) | yes | text excluded | F |

The history view also carries server-only request ownership columns (`request_id`, `employee_id`,
`legal_entity_id`) for SQL filtering; they are not copied into the safe history record. Runtime
metadata maps `contract_version varchar(64)` and `contract_sha256 char(64)` directly from
`ai_read.contract_metadata_v1` and returns neither publicly.
