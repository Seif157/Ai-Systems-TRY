# ERP trust integration deployment

The AI adapter cannot prove that ERP consumes references atomically. Laravel storage transactions
and independent conformance tests must guarantee at most one successful consume under concurrency.

Laravel/ERP must authenticate the user and approved workflow, store current trusted context plus
route intent behind 32 random bytes, and issue the exact short-lived Ed25519 assertion described in
the contract. Storage must expire references and atomically allow at most one consume. Signing keys
remain exclusively in ERP. Rotate verification keys with overlapping activation windows and keep ERP
and AI clocks synchronized.

Deploy the two fixed trust endpoints behind mutual TLS. The AI client certificate/private key and
trusted CA/public-key configuration are supplied by future secret-managed composition; they are not
loaded by this package. Proxies and both applications must disable Authorization and body logging.
Do not log reference values, response bodies, certificate data, or exception details.

The canonical body digest is the Step 24 compact insertion-ordered UTF-8 JSON digest. A lost resolve
response is never retried because ERP may already have consumed the reference; the UI must request a
new assertion. Production FastAPI composition, certificate provisioning, secret loading, endpoint
operations, retention, and monitoring remain deployment responsibilities.
