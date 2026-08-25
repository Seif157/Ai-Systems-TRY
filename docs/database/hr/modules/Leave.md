<!-- Module: Leave | Domain: HR | Split from DATABASE_SCHEMA.md -->

> **Canonical V2 note:** Apply [global standards](../02_GLOBAL_SCHEMA_STANDARDS.md) and this subdomain's final rules in [canonical module corrections](../04_CANONICAL_MODULE_CORRECTIONS.md). Those rules override this generated base definition.

## Leave

### Canonical structured-read additions

`leave_balances` additionally has `legal_entity_id uuid NOT NULL`, stored
`available_days numeric(7,2) NOT NULL`, `calculated_at timestamptz NOT NULL`,
`source_watermark varchar(128) NOT NULL`, and `calculation_version varchar(64) NOT NULL`.
Availability may be negative and is not generated or recalculated by AI.

`leave_requests` additionally has immutable `legal_entity_id uuid NOT NULL`,
`submitted_at timestamptz NOT NULL`, and
`working_days_calculation_version varchar(64) NOT NULL`. A canonical row is submitted; drafts are
outside the AI contract. Composite ownership constraints bind balance/request employee and leave
type to the captured legal entity.

### `leave_accrual_logs`

| Column | Type | Null | Default |
|---|---|---|---|
| log_id 🔑 | uuid | no | `gen_random_uuid()` |
| employee_id | uuid | no |  |
| leave_type_id | uuid | no |  |
| balance_id | uuid | no |  |
| accrual_date | date | no |  |
| days_accrued | numeric(5,2) | no |  |
| balance_before | numeric(7,2) | no |  |
| balance_after | numeric(7,2) | no |  |
| accrual_formula | varchar(20) | no |  |
| notes | text | yes |  |
| run_id | uuid | yes |  |
| created_at | timestamptz | no | `CURRENT_TIMESTAMP` |

- **Primary key:** log_id
- **Foreign keys:** `balance_id` → `leave_balances.balance_id` (on delete RESTRICT); `employee_id` → `employees.employee_id` (on delete RESTRICT); `leave_type_id` → `leave_types.leave_type_id` (on delete RESTRICT)
- **Indexes:** employee_id, accrual_date; run_id
- **Checks:** (((accrual_formula)::text = ANY ((ARRAY['annual_lump'::character varying, 'monthly'::character varying, 'anniversary'::character varying, 'none'::character varying])::text[])))

### `leave_adjustments`

| Column | Type | Null | Default |
|---|---|---|---|
| adjustment_id 🔑 | uuid | no | `gen_random_uuid()` |
| employee_id | uuid | no |  |
| leave_type_id | uuid | no |  |
| fiscal_year | smallint | no |  |
| adjustment_days | numeric(5,2) | no |  |
| reason | text | no |  |
| adjusted_by | bigint | no |  |
| created_at | timestamptz | no | `CURRENT_TIMESTAMP` |
| is_active | boolean | no | `true` |

- **Primary key:** adjustment_id
- **Foreign keys:** `employee_id` → `employees.employee_id` (on delete RESTRICT); `leave_type_id` → `leave_types.leave_type_id` (on delete RESTRICT)
- **Indexes:** employee_id, fiscal_year

### `leave_balances`

| Column | Type | Null | Default |
|---|---|---|---|
| balance_id 🔑 | uuid | no | `gen_random_uuid()` |
| employee_id | uuid | no |  |
| leave_type_id | uuid | no |  |
| fiscal_year | smallint | no |  |
| opening_balance | numeric(7,2) | no | `0` |
| accrued_ytd | numeric(7,2) | no | `0` |
| used_ytd | numeric(7,2) | no | `0` |
| pending_ytd | numeric(7,2) | no | `0` |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |
| created_by | bigint | yes |  |

- **Primary key:** balance_id
- **Foreign keys:** `employee_id` → `employees.employee_id` (on delete RESTRICT); `leave_type_id` → `leave_types.leave_type_id` (on delete RESTRICT)
- **Indexes:** employee_id, fiscal_year; leave_type_id, fiscal_year; employee_id, leave_type_id, fiscal_year
- **Checks:** (((opening_balance >= (0)::numeric) AND (accrued_ytd >= (0)::numeric) AND (used_ytd >= (0)::numeric) AND (pending_ytd >= (0)::numeric)))

### `leave_policies`

| Column | Type | Null | Default |
|---|---|---|---|
| policy_id 🔑 | uuid | no | `gen_random_uuid()` |
| leave_type_id | uuid | no |  |
| scope | varchar(10) | no | `all` |
| scope_id | uuid | yes |  |
| annual_entitlement_days | numeric(5,1) | no | `0` |
| accrual_method | varchar(20) | no | `annual_lump` |
| accrual_rate | numeric(5,2) | yes |  |
| max_carry_forward_days | numeric(5,1) | yes |  |
| min_service_months | smallint | no | `0` |
| max_consecutive_days | smallint | yes |  |
| notice_days | smallint | no | `0` |
| allow_negative_balance | boolean | no | `false` |
| gender_eligibility | varchar(10) | no | `all` |
| is_active | boolean | no | `true` |
| created_by | bigint | no |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |

- **Primary key:** policy_id
- **Foreign keys:** `leave_type_id` → `leave_types.leave_type_id` (on delete RESTRICT)
- **Indexes:** leave_type_id; scope, scope_id; leave_type_id, scope, COALESCE((scope_id
- **Checks:** (((accrual_method)::text = ANY ((ARRAY['annual_lump'::character varying, 'monthly'::character varying, 'anniversary'::character varying, 'none'::character varying])::text[]))); ((annual_entitlement_days >= (0)::numeric)); (((gender_eligibility)::text = ANY ((ARRAY['all'::character varying, 'male'::character varying, 'female'::character varying])::text[]))); (((scope)::text = ANY ((ARRAY['all'::character varying, 'grade'::character varying, 'dept'::character varying])::text[]))); ((((scope)::text = 'all'::text) OR (scope_id IS NOT NULL)))

### `leave_requests`

| Column | Type | Null | Default |
|---|---|---|---|
| request_id 🔑 | uuid | no | `gen_random_uuid()` |
| employee_id | uuid | no |  |
| leave_type_id | uuid | no |  |
| start_date | date | no |  |
| end_date | date | no |  |
| working_days | numeric(5,2) | no |  |
| is_half_day | boolean | no | `false` |
| half_day_period | varchar(15) | yes |  |
| reason | text | yes |  |
| medical_certificate_path | text | yes |  |
| medical_certificate_mime | varchar(100) | yes |  |
| status | varchar(20) | no | `pending` |
| approval_request_id | uuid | yes |  |
| reviewed_by_emp_id | uuid | yes |  |
| reviewed_at | timestamptz | yes |  |
| review_notes | text | yes |  |
| is_active | boolean | no | `true` |
| created_by | bigint | no |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |

- **Primary key:** request_id
- **Foreign keys:** `approval_request_id` → `approval_requests.request_id` (on delete SET NULL); `employee_id` → `employees.employee_id` (on delete RESTRICT); `leave_type_id` → `leave_types.leave_type_id` (on delete RESTRICT); `reviewed_by_emp_id` → `employees.employee_id` (on delete SET NULL)
- **Indexes:** start_date, end_date; employee_id, status; status; leave_type_id; employee_id, start_date, end_date
- **Checks:** ((end_date >= start_date)); (((half_day_period IS NULL) OR ((half_day_period)::text = ANY ((ARRAY['first_half'::character varying, 'second_half'::character varying])::text[])))); (((status)::text = ANY ((ARRAY['draft'::character varying, 'pending'::character varying, 'approved'::character varying, 'rejected'::character varying, 'returned'::character varying, 'cancelled'::character varying])::text[]))); ((working_days > (0)::numeric))

### `leave_types`

| Column | Type | Null | Default |
|---|---|---|---|
| leave_type_id 🔑 | uuid | no | `gen_random_uuid()` |
| leave_code | varchar(20) | no |  |
| leave_name | varchar(100) | no |  |
| leave_name_local | varchar(100) | no |  |
| category | varchar(30) | no |  |
| is_paid | boolean | no | `true` |
| requires_document | boolean | no | `false` |
| affects_attendance | boolean | no | `true` |
| color_hex | char(7) | no | `#6366F1` |
| is_active | boolean | no | `true` |
| created_by | bigint | no |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |

- **Primary key:** leave_type_id
- **Unique:** (leave_code)
- **Indexes:** category; is_active; leave_code
- **Checks:** ((color_hex ~ '^#[0-9A-Fa-f]{6}$'::text)); (((category)::text = ANY ((ARRAY['annual'::character varying, 'sick'::character varying, 'maternity'::character varying, 'paternity'::character varying, 'unpaid'::character varying, 'emergency'::character varying, 'bereavement'::character varying, 'compassionate'::character varying, 'hajj'::character varying, 'study'::character varying, 'other'::character varying])::text[])))

### `working_day_calendars`

| Column | Type | Null | Default |
|---|---|---|---|
| calendar_id 🔑 | uuid | no | `gen_random_uuid()` |
| calendar_date | date | no |  |
| is_working_day | boolean | no |  |
| day_type | varchar(20) | no |  |
| description | text | yes |  |
| country_code | char(2) | no | `EG` |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |
| created_by | bigint | yes |  |

- **Primary key:** calendar_id
- **Unique:** (calendar_date)
- **Indexes:** calendar_date; is_working_day, calendar_date; calendar_date
- **Checks:** (((day_type)::text = ANY ((ARRAY['weekday'::character varying, 'weekend'::character varying, 'public_holiday'::character varying, 'company_holiday'::character varying])::text[])))

---
