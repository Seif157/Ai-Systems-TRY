# HR Core: self employee profile

The production provider contract maps this tool only to
`POST /internal/ai/v1/hr/profile/read-self`. Laravel must revalidate the linked employee,
permission, purpose, legal scope, and customer database. Step 27 validates only the Python adapter.

`get_my_employee_profile` is the first production capability contract. It is a
read-only, employee-self-service tool; this repository still provides no real ERP
transport or employee data source.

## Registration and authorization

The immutable `hr_core` manifest registers version `1.0.0` of the tool with these
requirements:

- enabled module: `hr_core`
- every permission: `hr.profile.read_self`
- role restriction: none; the trusted employee link is authoritative
- allowed purpose: `employee_self_service`
- linked employee context: required
- operation: `read`
- data classification: `restricted`
- audit action: `hr.profile.read_self`

The registry and gateway evaluate only `TrustedRequestContext`. Missing employee,
module, permission, employee link, or purpose claims hide the tool from model-facing output
and prevent provider access. The public request and tool arguments cannot select or
override those values.

## Input and trusted provider boundary

The public input is an empty, strict Pydantic model. In particular, it accepts no
customer or employee identifier. `HrCoreReadProvider` is an asynchronous Protocol
whose implementation receives `customer_environment_id` and `employee_id` from the
trusted context through the handler. A future ERP adapter must enforce the same
customer boundary and return an `EmployeeProfileRecord`; the current tests use only
in-memory fakes.

The handler fails closed when a record is absent, when its employee does not match
the linked employee, or when its legal entity is outside the context's authorized
legal entities. Provider exceptions and these internal reasons are collapsed by the
gateway into its generic safe execution failure.

## Safe output

The explicitly mapped public output contains only:

- employee number (required, maximum 20 characters) and display name (required,
  maximum 200 characters)
- work email (required, maximum 200 characters) and hire date (required)
- optional job title, department, branch, legal-entity display name, and manager display name;
  optional strings reject blank values
- employment status, restricted to `active`, `probation`, `on_leave`, `suspended`,
  `terminated`, `resigned`, `retired`, or `inactive`
- a timezone-aware freshness timestamp

It excludes internal employee and legal-entity IDs, customer and user identity,
roles, permissions, entitlements, purpose, provider diagnostics, raw source rows,
compensation, government identifiers, bank details, medical data, and credentials.
Missing optional fields remain `null`; the handler does not infer or fabricate them. The ERP
remains responsible for authoritative email syntax validation; this contract intentionally adds
no email-validation dependency.

## Audit behavior

Every invocation continues through the mandatory gateway audit sink. The tool emits
the governed `restricted` classification and `hr.profile.read_self` audit action.
Audit events do not contain tool arguments, provider records, output fields, or the
restricted trusted context. Public results never contain audit events.

## Current limitations

The Protocol is a contract, not a production provider. It provides no authentication,
transport, timeout, retry, freshness policy, or external authorization lookup.
Those controls belong in a future typed ERP API adapter. This slice adds no database,
SQL, network, FastAPI, RAG, vector, model-provider, or command-execution integration.
