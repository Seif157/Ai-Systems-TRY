# Laravel ERP read API contract

The frozen private contract is version `1.0.0`, service `laravel_erp_read_api`, digest
`a1eb5534adf3925ae4fa44e219373de6f4bf67fd8661df55640d4d5e6f7ee1b1`. The digest is
domain-separated and binds the insertion-ordered, compact, finite UTF-8 JSON descriptor without
a trailing newline. It covers methods, paths, ordered fields, types, bounds, nullability, enums,
outcomes, collection ordering, and provider projection signatures.

This repository contains no Laravel/PHP implementation. Metadata agreement detects contract drift;
it cannot prove authorization, isolation, business-rule, or database behavior.

| Operation | Method | Exact path |
| --- | --- | --- |
| Metadata | `GET` | `/internal/ai/v1/read-contract` |
| Profile | `POST` | `/internal/ai/v1/hr/profile/read-self` |
| Balances | `POST` | `/internal/ai/v1/leave/balances/read-self` |
| Request list | `POST` | `/internal/ai/v1/leave/requests/list-self` |
| Request detail | `POST` | `/internal/ai/v1/leave/requests/get-self` |

No aliases, trailing slashes, dynamic segments, or query parameters are accepted.

Metadata contains exactly `service_identity`, `contract_version`, `contract_digest`, and strict
boolean `read_only=true`. Every business request contains exactly, in order:
`contract_version`, `correlation_request_id`, `customer_environment_id`, `user_id`, `employee_id`,
`authorization_snapshot_id`, `purpose`, `legal_entity_ids`, `tool_name`, and `tool_version`, plus
only its operation fields. List adds `page_size` and nullable `cursor`; detail adds
`leave_request_id`. Profile and balances add nothing.

Every successful response echoes those ten binding fields exactly, then contains `outcome` and its
operation data: nullable `profile`, `balances`, `requests`, or nullable `leave_request`. Profile and
detail use `found` or `not_found`; the nullable value must agree with the outcome. Balances and list
use `found`. UUIDs are canonical lowercase hyphenated values, legal-entity order is preserved, and
nullable fields are serialized explicitly.

Laravel must authenticate the mTLS service identity, revalidate the authorization snapshot and all
bindings, enforce legal-entity and record visibility, route to the customer database, execute only
predefined reads, and generate/validate opaque cursors. Cursor authenticity, expiry, tenant/filter
binding, and confidentiality are Laravel responsibilities. Python bindings are not authority.

The synthetic mTLS service is a protocol fixture, not Laravel interoperability evidence. A real
Laravel implementation and joint acceptance test remain production dependencies.
