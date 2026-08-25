# Structured AI read contract v1

This is the reviewed ERP-owner contract for production read-only HR adapters. The ERP database
owner implements and certifies these columns, constraints, roles, and views. This AI repository
does not ship a production ERP migration.

## Source mappings

`hr_employee_profile_v1` maps identity, legal entity, employee number, canonical `display_name`,
work email, employment state, hire date, and `profile_freshness_at` from `employees`; `job_title`
from `positions.position_title`; department, branch, and legal-entity names from their canonical
tables; and manager display from `manager.display_name`. Optional joins remain nullable. Every
organization join matches `employees.legal_entity_id`.

`leave_balances_v1` maps stored balance values unchanged and joins `leave_types` on both type and
legal entity. `leave_requests_v1` maps immutable ownership, submission, and calculation values and
joins leave type on the same legal entity. `leave_request_history_v1` exposes only the safe workflow
subset for `entity_type='leave_request'`, with ownership joined through the request.

## Exact view signatures

Columns are ordered exactly as shown:

- `ai_read.hr_employee_profile_v1`: `employee_id uuid`, `legal_entity_id uuid`,
  `employee_number varchar(20)`, `display_name varchar(200)`, `work_email varchar(200)`,
  `job_title varchar(200)`, `department_name varchar(200)`, `branch_name varchar(200)`,
  `legal_entity_name varchar(250)`, `employment_status varchar(20)`, `hire_date date`,
  `manager_display_name varchar(200)`, `freshness_at timestamptz`.
- `ai_read.leave_balances_v1`: `employee_id uuid`, `legal_entity_id uuid`, `leave_type_id uuid`,
  `leave_type_code varchar(20)`, `leave_type_name varchar(100)`,
  `leave_type_name_local varchar(100)`, `fiscal_year smallint`, `opening_days numeric(7,2)`,
  `accrued_days numeric(7,2)`, `used_days numeric(7,2)`, `pending_days numeric(7,2)`,
  `available_days numeric(7,2)`, `calculated_at timestamptz`,
  `source_watermark varchar(128)`, `calculation_version varchar(64)`.
- `ai_read.leave_requests_v1`: `request_id uuid`, `employee_id uuid`, `legal_entity_id uuid`,
  `leave_type_id uuid`, `leave_type_code varchar(20)`, `leave_type_name varchar(100)`,
  `leave_type_name_local varchar(100)`, `start_date date`, `end_date date`,
  `working_days numeric(5,2)`, `is_half_day boolean`, `half_day_period varchar(15)`,
  `status varchar(20)`, `submitted_at timestamptz`, `updated_at timestamptz`,
  `working_days_calculation_version varchar(64)`.
- `ai_read.leave_request_history_v1`: `history_id uuid`, `request_id uuid`,
  `employee_id uuid`, `legal_entity_id uuid`, `entity_type varchar(80)`,
  `from_status varchar(40)`, `to_status varchar(40)`, `changed_at timestamptz`,
  `reason_code varchar(50)`.
- `ai_read.contract_metadata_v1`: `contract_version varchar(64)`, `contract_sha256 char(64)`.

Contract version is `1.0.0`; the contract digest is
`077528e247774f3584de47187b97975535d938f562cdf6ad59c61ce9a506aec5`.

Canonicalization is frozen: the descriptor contains the contract version, the four fully qualified
business-view names in their declared order, every `(column_name, PostgreSQL type)` pair in declared
order, and the fully qualified metadata-view name/signature. The descriptor object inserts keys in
the exact order `contract_version`, `views`, `metadata_view`. It is serialized as compact UTF-8 JSON
with no sorted-key reordering and no trailing newline. The metadata row's digest value is excluded
to avoid recursion. Repository filenames, database/customer names, DSNs, roles, and environment
configuration never participate. Runtime and ERP deployment tooling calculate the same value.

## Constraints, ownership, and grants

Employees, balances, requests, and leave types carry direct non-null legal-entity ownership.
Composite keys/FKs prove balance/request employee and leave type belong to that entity. Request
submission and transaction ownership are immutable. Calculation versions use complete
`MAJOR.MINOR.PATCH` SemVer; watermarks are trimmed, nonblank, and at most 128 characters.

Views use `security_barrier=true` and a dedicated non-login owner that owns no base table, is not
superuser, and has no `BYPASSRLS`. Revoke PUBLIC. The runtime reader receives only `USAGE` on
`ai_read` and `SELECT` on these five views, with no base-table or write/DDL privileges.

## Runtime verification and deployment certification

Startup verifies PostgreSQL 15â€“18, configured `current_database()`, metadata version/digest, exact
view signatures, view ownership, runtime role attributes, approved view SELECT, and absence of
direct base-table privileges. Public diagnostics expose only a safe contract digest.

Before enabling a route, an ERP-owner privileged check must compare `pg_attribute`,
`pg_constraint`, `pg_class`, `pg_roles`, `information_schema.role_table_grants`, and view definitions
with this contract; inspect underlying types/nullability, composite ownership FKs, immutability,
ownership, grants, and revoked PUBLIC access. Retain a signed certification bound to the digest.
Runtime reader credentials cannot perform this inspection. DSNs and cursor keys come from a
production secret manager, never public requests or repository files.
