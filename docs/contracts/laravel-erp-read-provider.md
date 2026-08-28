# Laravel ERP read provider

The Python adapter uses one startup-configured HTTPS origin and one shared lifecycle-managed
`LaravelErpReadClient` for all four capability providers. Customer values cannot affect the
origin, path, credentials, or routing. Construction performs no I/O; startup performs exactly one
contract-metadata verification for a successful client lifecycle.

The caller supplies an already provisioned `SSLContext`. The client requires certificate and
hostname verification and TLS 1.2 or newer, and revalidates that policy at startup. Certificate
and private-key loading remain deployment responsibilities; Python cannot prove from an
`SSLContext` alone that the intended client certificate was loaded.

HTTP behavior is fixed: redirects, environment proxy trust, retries, fallback, streaming API
mode, cookies, compression, and caching are disabled. Requests use compact UTF-8 JSON with an
explicit field projection. Responses are bounded while streaming, require one JSON content type,
strict UTF-8, unique JSON keys, finite numbers, and exact typed projections. Each operation makes
at most one request. Cancellation propagates unchanged. Every other transport, Laravel denial,
metadata drift, malformed response, binding mismatch, or provider exception becomes the single
internal `LaravelErpReadUnavailable` boundary without including provider details.

Authorization remains layered:

1. The trusted application service verifies context and snapshot freshness.
2. The server-owned route catalog selects an installed route.
3. `ReadToolGateway` rechecks modules, permissions, purpose, linked employee, legal scope,
   version, and read-only operation before the provider is invoked.
4. Laravel independently revalidates the snapshot and business visibility.
5. Laravel alone routes to and connects to the customer's database.

A gateway denial produces no Laravel request. The adapter never grants entitlement, infers
authority from arguments, converts denial to success, or falls back to another route/customer.
The frozen list endpoint carries only `page_size` and `cursor`; this adapter fails closed when the
provider-neutral request contains status or date filters rather than silently dropping them.

The explicit Laravel bundle supplies four handlers and one shared client lifecycle for injection
into the provider-neutral runtime bundle. Core `erp_ai.runtime` code does not import or construct
Laravel. Existing direct PostgreSQL ERP adapters are independently tested legacy infrastructure,
not an implicit fallback; the approved production path delegates customer database access to Laravel.

No provider-specific audit exists. Existing transport/application/agent/tool audit ownership and
schemas remain unchanged. Bodies, employee/snapshot/legal IDs, cursors, selectors, TLS details,
and exceptions never enter those audit projections.
