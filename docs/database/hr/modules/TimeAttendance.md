<!-- Module: TimeAttendance | Domain: HR | Split from DATABASE_SCHEMA.md -->

> **Canonical V2 note:** Apply [global standards](../02_GLOBAL_SCHEMA_STANDARDS.md) and this subdomain's final rules in [canonical module corrections](../04_CANONICAL_MODULE_CORRECTIONS.md). Those rules override this generated base definition.

## TimeAttendance

### `attendance_records`

| Column | Type | Null | Default |
|---|---|---|---|
| record_id 🔑 | uuid | no | `gen_random_uuid()` |
| employee_id | uuid | no |  |
| attendance_date | date | no |  |
| shift_id | uuid | yes |  |
| clock_in_at | timestamptz | yes |  |
| clock_out_at | timestamptz | yes |  |
| clock_in_source | varchar(20) | no | `web` |
| clock_out_source | varchar(20) | yes |  |
| clock_in_location | jsonb | yes |  |
| clock_out_location | jsonb | yes |  |
| late_minutes | smallint | no | `0` |
| early_departure_minutes | smallint | no | `0` |
| hours_worked | numeric(4,2) | no | `0` |
| overtime_minutes | smallint | no | `0` |
| notes | text | yes |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |
| created_by | bigint | yes |  |

- **Primary key:** record_id
- **Foreign keys:** `employee_id` → `employees.employee_id` (on delete CASCADE); `shift_id` → `work_shifts.shift_id` (on delete SET NULL)
- **Unique:** (employee_id, attendance_date)
- **Indexes:** employee_id, attendance_date; attendance_date; employee_id, attendance_date
- **Checks:** (((clock_in_source)::text = ANY ((ARRAY['web'::character varying, 'mobile'::character varying, 'kiosk'::character varying])::text[]))); (((clock_out_source IS NULL) OR ((clock_out_source)::text = ANY ((ARRAY['web'::character varying, 'mobile'::character varying, 'kiosk'::character varying])::text[]))))

### `attendance_summaries`

| Column | Type | Null | Default |
|---|---|---|---|
| summary_id 🔑 | uuid | no | `gen_random_uuid()` |
| employee_id | uuid | no |  |
| year | smallint | no |  |
| month | smallint | no |  |
| working_days_in_month | smallint | no | `0` |
| days_present | smallint | no | `0` |
| days_absent | smallint | no | `0` |
| days_on_leave | smallint | no | `0` |
| total_hours_worked | numeric(6,2) | no | `0` |
| total_late_minutes | integer | no | `0` |
| total_overtime_minutes | integer | no | `0` |
| total_early_departure_minutes | integer | no | `0` |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |
| created_by | bigint | yes |  |

- **Primary key:** summary_id
- **Foreign keys:** `employee_id` → `employees.employee_id` (on delete CASCADE)
- **Unique:** (employee_id, year, month)
- **Indexes:** employee_id, year, month; employee_id, year, month

### `overtime_requests`

| Column | Type | Null | Default |
|---|---|---|---|
| overtime_id 🔑 | uuid | no | `gen_random_uuid()` |
| employee_id | uuid | no |  |
| attendance_record_id | uuid | yes |  |
| overtime_date | date | no |  |
| requested_minutes | smallint | no |  |
| approved_minutes | smallint | yes |  |
| reason | text | yes |  |
| status | varchar(20) | no | `pending` |
| approval_request_id | uuid | yes |  |
| reviewed_by_emp_id | uuid | yes |  |
| reviewed_at | timestamptz | yes |  |
| review_notes | text | yes |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |
| created_by | bigint | yes |  |

- **Primary key:** overtime_id
- **Foreign keys:** `attendance_record_id` → `attendance_records.record_id` (on delete SET NULL); `employee_id` → `employees.employee_id` (on delete CASCADE)
- **Indexes:** employee_id; status
- **Checks:** (((status)::text = ANY ((ARRAY['pending'::character varying, 'approved'::character varying, 'rejected'::character varying])::text[]))); ((requested_minutes > 0))

### `shift_assignments`

| Column | Type | Null | Default |
|---|---|---|---|
| assignment_id 🔑 | uuid | no | `gen_random_uuid()` |
| employee_id | uuid | no |  |
| shift_id | uuid | no |  |
| effective_from | date | no |  |
| effective_to | date | yes |  |
| assigned_by | bigint | yes |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |
| is_active | boolean | no | `true` |
| created_by | bigint | yes |  |

- **Primary key:** assignment_id
- **Foreign keys:** `employee_id` → `employees.employee_id` (on delete CASCADE); `shift_id` → `work_shifts.shift_id` (on delete CASCADE)
- **Indexes:** employee_id, effective_from, effective_to; employee_id

### `work_shifts`

| Column | Type | Null | Default |
|---|---|---|---|
| shift_id 🔑 | uuid | no | `gen_random_uuid()` |
| shift_code | varchar(20) | no |  |
| shift_name | varchar(100) | no |  |
| shift_name_local | varchar(100) | yes |  |
| start_time | time | no |  |
| end_time | time | no |  |
| grace_period_minutes | smallint | no | `0` |
| break_duration_minutes | smallint | no | `0` |
| overtime_threshold_minutes | smallint | no | `60` |
| geofence_latitude | numeric(10,7) | yes |  |
| geofence_longitude | numeric(10,7) | yes |  |
| geofence_radius_meters | integer | yes |  |
| is_night_shift | boolean | no | `false` |
| is_active | boolean | no | `true` |
| created_by | bigint | yes |  |
| created_at | timestamptz | yes |  |
| updated_at | timestamptz | yes |  |

- **Primary key:** shift_id
- **Unique:** (shift_code)
- **Indexes:** is_active; shift_code

---
