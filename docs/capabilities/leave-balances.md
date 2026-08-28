# Leave: my balances

The production provider contract maps this tool only to
`POST /internal/ai/v1/leave/balances/read-self`. Laravel owns customer routing, snapshot
revalidation, balance business rules, and visibility. Python has no customer-database access.

`get_my_leave_balances` is a read-only employee-self-service capability that returns
authoritative, ERP-calculated current leave balances. This repository defines only the typed
contract and uses fake providers in tests.

## Ledger and calculated cache boundary

`leave_ledger_entries` is the authoritative append-only source of leave movements.
`leave_balances` is a calculated cache carrying `calculated_at`, `source_watermark`, and
`calculation_version`. The AI handler never reads either table, interprets ledger entries,
applies policy, selects a fiscal year, or calculates or verifies `available_days`. A future ERP
provider must return authoritative calculated values for the ERP-selected current fiscal year.

## Authorization

The `leave` capability requires both canonical AI entitlements, `hr_core` and `leave`. Its tool
requires a trusted linked employee, the `leave.balance.read_self` permission, and the
`employee_self_service` purpose. It has no literal role requirement. Missing authorization hides
the tool and prevents provider execution.

The strict frozen public input is empty. Fiscal year, employee, customer, legal-entity, and module
values cannot be supplied by the model. The handler passes only trusted customer, employee, and
authorized legal-entity values to `LeaveReadProvider`.

## Provider and scope validation

The asynchronous provider returns immutable `LeaveBalanceRecord` values. Before returning any
result, the handler verifies every employee ID, every legal-entity scope, and uniqueness by legal
entity, leave type, and fiscal year. One invalid record fails the complete response. Empty provider
results are valid and remain empty.

The Protocol is not a production ERP adapter. Authentication, tenant routing, ERP authorization,
current-fiscal-year selection, cache production, and ledger reconciliation remain ERP
responsibilities.

## Decimal and freshness rules

Opening, accrued, used, and pending days are nonnegative `Decimal` values. `available_days` may be
negative when authoritative policy permits it. All values follow `numeric(7,2)` bounds and retain
at most two decimal places; they are never converted to floating point. `calculated_at` is
timezone-aware, and `calculation_version` identifies the ERP calculation implementation.
`source_watermark` is retained internally for provider/cache provenance but is not public.

## Safe output and audit

The safe output contains leave type code and localized names, fiscal year, the five Decimal balance
values, `calculated_at`, and `calculation_version`. It excludes employee, customer, legal-entity,
leave-type, balance, ledger, policy, and request identifiers; source watermarks; raw ledger entries;
and other calculation metadata.

Gateway auditing uses `restricted` classification and action `leave.balance.read_self`. Audit
events contain no balance values, provider records, source watermark, arguments, or output. No
database, SQL, HTTP, policy engine, ledger calculation, RAG, model provider, or write command is
implemented by this capability.
