# Leave: get my request

The production provider contract maps this tool only to
`POST /internal/ai/v1/leave/requests/get-self`. Laravel must make nonexistent, foreign, and
out-of-scope records indistinguishable.

`get_my_leave_request` is a read-only employee-self-service tool for one owned Leave request and
its safe status timeline. It is an in-memory contract backed only by synthetic fake providers.

## Authorization and selector

The `leave` capability requires both `hr_core` and `leave`. This tool additionally requires a
trusted linked employee, `leave.request.read_self`, and `employee_self_service`; it has no literal
role requirement. Its only public input is a UUID `request_id` record selector.

The selector does not replace the trusted correlation request ID. Customer environment, linked
employee, legal-entity scope, permission, purpose, and entitlements come only from
`TrustedRequestContext`. The provider receives those trusted values separately and must
independently enforce customer and employee scope.

## Provider and ownership boundary

`LeaveReadProvider.get_my_leave_request` returns one strict internal detail or `None`. The handler
then verifies the returned selector, customer environment, employee owner, and legal entity. Not
found, wrong customer, wrong employee, selector mismatch, and unauthorized legal entity all
collapse to the same generic public execution failure; callers cannot use errors to discover an
inaccessible record.

The ERP supplies persisted Decimal working days and request status. The AI service does not
calculate days, interpret policy, or infer workflow state.

## Status timeline integrity

The provider must return transitions in canonical order:

1. `changed_at` ascending
2. `history_id` ascending when timestamps are equal

The handler preserves this order and fails closed instead of sorting. It rejects duplicate history
IDs, any entity type other than `leave_request`, entity IDs that do not match the selected request,
out-of-order events, broken `from_status`/previous-`to_status` chains, and a final transition that
does not match the request's current status. Only the first transition may have a null
`from_status`. No allowed transition graph is hardcoded because workflow policy remains
authoritative in the ERP.

An empty timeline is accepted for a newly created or migrated record. The canonical documentation
requires transitions to be recorded but does not guarantee that every historical record has an
initial row.

## Safe output

The public detail contains only the request UUID; approved leave-type code and names; request
dates; Decimal working days; half-day fields; current status; submitted/updated timestamps; and a
timeline containing `from_status`, `to_status`, `changed_at`, and optional validated
`reason_code`. The foundation schema explicitly defines `reason_code`, so the first version allows
its lowercase snake-case representation.

The output excludes customer, employee, legal-entity, leave-type, and history identifiers;
workflow actors and reviewers; approval and correlation IDs; medical-document identifiers or
paths; review notes; request text; raw reason text; and working-day calculation metadata. No raw
free text is accepted into the internal timeline contract or projected publicly.

## Auditing and limitations

Every invocation still crosses the mandatory fail-closed gateway audit sink exactly once. The
selected Leave request UUID, arguments, dates, working-day values, timeline, free text, employee,
and authorization collections are absent from the event. The audit event's existing
`request_id` is the trusted request correlation identifier, not the selected Leave request UUID.

There is no production ERP provider, transport, timeout, retry, database access, command path, or
workflow-policy engine. Provider authentication, tenant isolation, authoritative history
selection, and consistency between current status and append-only history remain production ERP
responsibilities.
