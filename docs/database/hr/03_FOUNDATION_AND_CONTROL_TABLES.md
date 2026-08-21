# Foundation and Control Tables

These tables are mandatory additions to the supplied HR model.

## `legal_entities`

| Column | Type | Null | Default |
|---|---|---:|---|
| legal_entity_id | uuid PK | no | `gen_random_uuid()` |
| entity_code | varchar(30) | no | |
| legal_name | varchar(250) | no | |
| legal_name_local | varchar(250) | yes | |
| country_code | char(2) | no | |
| base_currency_code | char(3) | no | |
| timezone | varchar(64) | no | |
| registration_number_encrypted | bytea | yes | |
| registration_number_hash | bytea | yes | |
| tax_number_encrypted | bytea | yes | |
| tax_number_hash | bytea | yes | |
| is_active | boolean | no | `true` |
| created_by_user_id | bigint | no | |
| created_at | timestamptz | no | `now()` |
| updated_by_user_id | bigint | yes | |
| updated_at | timestamptz | no | `now()` |
| row_version | bigint | no | `1` |

- Unique: `entity_code`; registration/tax hashes when present.
- Checks: valid ISO codes; non-empty timezone.
- Every `organization_branch` belongs to one legal entity.

## `erp_module_installations`

| Column | Type | Null | Default |
|---|---|---:|---|
| installation_id | uuid PK | no | `gen_random_uuid()` |
| module_code | varchar(50) | no | |
| schema_version | varchar(30) | no | |
| status | varchar(20) | no | `enabled` |
| licensed_until | timestamptz | yes | |
| configuration | jsonb | no | `'{}'` |
| installed_at | timestamptz | no | `now()` |
| installed_by_user_id | bigint | yes | |
| updated_at | timestamptz | no | `now()` |

- Unique: `module_code`.
- Status: `enabled`, `disabled`, `suspended`, `expired`.
- The server, not the client, resolves module availability.

## `user_employee_links`

| Column | Type | Null | Default |
|---|---|---:|---|
| link_id | uuid PK | no | `gen_random_uuid()` |
| user_id | bigint | no | |
| employee_id | uuid | no | |
| is_primary | boolean | no | `true` |
| effective_from | timestamptz | no | `now()` |
| effective_to | timestamptz | yes | |
| created_at | timestamptz | no | `now()` |

- FKs: user to `users`; employee to `employees`, both `ON DELETE RESTRICT`.
- Unique current primary link per user and per employee using partial unique indexes.
- Check: `effective_to IS NULL OR effective_to > effective_from`.
- This table is the only accepted resolver for AI requests containing “my”.

## `hr_secure_files`

| Column | Type | Null | Default |
|---|---|---:|---|
| file_id | uuid PK | no | `gen_random_uuid()` |
| storage_provider | varchar(30) | no | |
| storage_object_key | text | no | |
| original_filename | varchar(255) | no | |
| media_type | varchar(150) | no | |
| size_bytes | bigint | no | |
| sha256 | char(64) | no | |
| classification | varchar(20) | no | `restricted` |
| encryption_key_version | varchar(50) | no | |
| malware_scan_status | varchar(20) | no | `pending` |
| retention_until | date | yes | |
| legal_hold | boolean | no | `false` |
| uploaded_by_user_id | bigint | no | |
| uploaded_at | timestamptz | no | `now()` |
| deleted_at | timestamptz | yes | |

- Unique: `(storage_provider, storage_object_key)`; `sha256` may be indexed but not globally unique.
- Checks: positive size; allowed classifications and scan states.
- Application access is denied until the scan is `clean`.

## `hr_audit_events`

| Column | Type | Null | Default |
|---|---|---:|---|
| audit_event_id | uuid PK | no | `gen_random_uuid()` |
| occurred_at | timestamptz | no | `now()` |
| actor_user_id | bigint | yes | |
| actor_type | varchar(20) | no | `user` |
| employee_context_id | uuid | yes | |
| action | varchar(80) | no | |
| entity_type | varchar(80) | no | |
| entity_id | uuid | yes | |
| correlation_id | uuid | no | |
| source | varchar(30) | no | |
| outcome | varchar(20) | no | |
| changed_fields | jsonb | yes | |
| metadata_redacted | jsonb | no | `'{}'` |
| ip_address | inet | yes | |

- Append-only; application roles have INSERT/SELECT but no UPDATE/DELETE.
- `changed_fields` stores field names and safe summaries, never plaintext secrets.
- Source includes `web`, `mobile`, `api`, `integration`, `ai_tool`, `system_job`.

## `workflow_status_history`

| Column | Type | Null | Default |
|---|---|---:|---|
| history_id | uuid PK | no | `gen_random_uuid()` |
| entity_type | varchar(80) | no | |
| entity_id | uuid | no | |
| from_status | varchar(40) | yes | |
| to_status | varchar(40) | no | |
| reason_code | varchar(50) | yes | |
| reason_text | text | yes | |
| approval_request_id | uuid | yes | |
| changed_by_user_id | bigint | yes | |
| changed_at | timestamptz | no | `now()` |
| correlation_id | uuid | no | |

- Append-only.
- Index: `(entity_type, entity_id, changed_at)`.
- A transition and its history row are committed in one transaction.

## `pay_periods`

| Column | Type | Null | Default |
|---|---|---:|---|
| pay_period_id | uuid PK | no | `gen_random_uuid()` |
| legal_entity_id | uuid | no | |
| period_code | char(7) | no | |
| period_start | date | no | |
| period_end | date | no | |
| fiscal_year | smallint | no | |
| fiscal_month | smallint | no | |
| currency_code | char(3) | no | |
| status | varchar(20) | no | `open` |
| locked_at | timestamptz | yes | |
| locked_by_user_id | bigint | yes | |
| created_at | timestamptz | no | `now()` |

- Unique: `(legal_entity_id, period_code)`.
- Checks: valid month code; end >= start; month 1–12; locked fields required when status is locked/closed.
- Status: `open`, `processing`, `locked`, `closed`, `reopened`.

## `work_calendars`

| Column | Type | Null | Default |
|---|---|---:|---|
| calendar_id | uuid PK | no | `gen_random_uuid()` |
| legal_entity_id | uuid | no | |
| branch_id | uuid | yes | |
| calendar_code | varchar(30) | no | |
| calendar_name | varchar(150) | no | |
| country_code | char(2) | no | |
| timezone | varchar(64) | no | |
| effective_from | date | no | |
| effective_to | date | yes | |
| priority | smallint | no | `100` |
| is_active | boolean | no | `true` |
| created_at | timestamptz | no | `now()` |

- Unique: `(legal_entity_id, calendar_code)`.
- Non-overlap for the same branch/calendar scope.
- Branch calendars override legal-entity calendars according to priority.

## `working_calendar_days`

This table replaces the global uniqueness rule on `working_day_calendars`.

| Column | Type | Null | Default |
|---|---|---:|---|
| calendar_day_id | uuid PK | no | `gen_random_uuid()` |
| calendar_id | uuid | no | |
| calendar_date | date | no | |
| is_working_day | boolean | no | |
| day_type | varchar(20) | no | |
| description | text | yes | |
| created_at | timestamptz | no | `now()` |

- Unique: `(calendar_id, calendar_date)`.
- FK: calendar to `work_calendars`, `ON DELETE RESTRICT` after activation.

## `hr_command_executions`

| Column | Type | Null | Default |
|---|---|---:|---|
| command_execution_id | uuid PK | no | `gen_random_uuid()` |
| idempotency_key | varchar(100) | no | |
| command_name | varchar(100) | no | |
| actor_user_id | bigint | no | |
| employee_context_id | uuid | yes | |
| target_entity_type | varchar(80) | yes | |
| target_entity_id | uuid | yes | |
| approval_request_id | uuid | yes | |
| request_hash | char(64) | no | |
| status | varchar(20) | no | `received` |
| result_reference | jsonb | yes | |
| error_code | varchar(80) | yes | |
| created_at | timestamptz | no | `now()` |
| completed_at | timestamptz | yes | |

- Unique: `idempotency_key`.
- Stores hashes and safe references, not raw sensitive prompts or payloads.
- Used by web, mobile, integrations, and AI write tools.

