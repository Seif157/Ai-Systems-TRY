# Leave: list my requests

`list_my_leave_requests` is a read-only employee-self-service tool that returns a paginated safe
summary of requests belonging to the trusted linked employee. This repository defines the
contract and uses only synthetic fake providers.

## Authorization

The existing `leave` capability requires both `hr_core` and `leave` entitlements. This tool also
requires a trusted employee link, `leave.request.read_self`, and the
`employee_self_service` purpose. It has no literal role requirement. The registry and gateway hide
and reject it before provider execution when any requirement is absent.

Customer, employee, and authorized legal-entity identifiers come only from
`TrustedRequestContext`. The public filters cannot override them.

## Filters and pagination

The strict frozen input supports:

- zero or more unique canonical statuses
- optional inclusive start-date bounds in ISO `YYYY-MM-DD` form
- at most 366 days when both bounds are explicit
- a limit from 1 through 50, defaulting to 20
- an optional opaque cursor of at most 512 characters

The service validates and forwards these filters but does not interpret leave policy, calculate
working days, select another employee, or decode or modify the cursor. Fiscal year, reviewer,
approval request, customer, employee, legal entity, entitlement, permission, and role fields are
not accepted.

## Provider and record validation

`LeaveReadProvider.list_my_leave_requests` receives the trusted customer, employee, and complete
authorized legal-entity tuple plus the validated filters. It returns an immutable internal page
already ordered by `submitted_at DESC, request_id ASC`. The provider must apply that exact order
before pagination and generate its cursor from the same order.

The handler preserves provider order and validates it; it does not sort or repair a page. It also
verifies every employee and legal entity, rejects duplicate request IDs, rejects more items than
the requested limit, and rejects an empty page carrying a continuation cursor. One bad record or
page invariant fails the complete response. An empty page without a cursor and a non-empty final
page without a cursor are valid.

The ERP supplies persisted `working_days` and its calculation version. The AI service preserves
the Decimal value and never recalculates days or interprets calendars or policies. Internal records
enforce the canonical request statuses, date order, `numeric(5,2)` limits, timezone-aware
timestamps, and half-day consistency: one date, a period, and exactly `0.50` working day.

## Safe output

Results preserve the validated canonical provider order: `submitted_at` descending and request
UUID ascending as the stable tie-breaker.
The output contains request ID, leave type display fields, dates, working days, half-day metadata,
status, timestamps, calculation version, and the opaque next cursor.

It excludes employee, legal-entity, and leave-type IDs; approval and reviewer IDs; review notes;
medical-certificate and secure-file fields; reason text; workflow correlations; creator identity;
and raw status-history rows. A detailed safe timeline is available only through the separately
authorized `get_my_leave_request` contract.

Audit events use `restricted` classification and `leave.request.list_self`. They contain no
request values, filter values, or cursors.

## Cursor security and current limitation

A production ERP provider must generate its cursor from `submitted_at DESC, request_id ASC`; bind
it to the customer environment, linked employee, original filters, and page size; make it
tamper-resistant; enforce expiration; keep sensitive plaintext out of it; and use consistent
pagination semantics that prevent records from being skipped or duplicated between pages.

The AI service forwards cursors unchanged. It never decodes, edits, reconstructs, logs, or attempts
to verify their contents. The current fake cursor proves only opaque pass-through and does not
provide the production guarantees above. No database, HTTP adapter, calculation engine, detail
tool, status-history tool, or write operation is implemented here.
