# Production deployment and operations

## Composition and lifecycle

Only `erp_ai.deployment` may assemble PostgreSQL audit sinks, ERP assertion/trust clients, Laravel
read providers, production RAG, direct OpenAI model/embedding providers, the read-only registry,
gateway, application service, runtime lifecycle, and internal HTTP app. Construction is ordered:
configuration validation, secret-reference validation, SSL contexts, static routers, provider
bundles, registry/handlers, audit sinks, trust services, gateway, orchestrator, application, then
HTTP transport. Construction performs no I/O except explicit configuration/secret loading and no
provider startup. Startup opens audit, ERP trust, Laravel/RAG/OpenAI dependencies in fixed order;
failure or cancellation closes already-opened dependencies synchronously in reverse order.
Shutdown is serialized, at most once, and reverse ordered. Readiness is false before completion and
through shutdown.

The packaged `erp-ai-serve` command is the concrete composition root. Deployment owners mount
strict JSON values and referenced secret files; they do not supply Python factories or callbacks.
Provider startup order is Laravel, customer knowledge PostgreSQL routers, and the shared direct
OpenAI client. Rollback and normal shutdown use the exact reverse order. Audit storage and ERP
trust remain the outer runtime lifecycle and therefore open before providers and close after them.

Administrative commands are separate executables:
`erp-ai-migrate-control-audit`, `erp-ai-migrate-customer-audit`,
`erp-ai-migrate-customer-knowledge`, and `erp-ai-production-preflight`. Migration Jobs mount their
own `/etc/erp-ai/admin.json` and `/run/secrets/erp-ai-admin` boundary. Runtime pods neither mount
those credentials nor invoke migrations during startup or over HTTP.

The server uses one worker, ASGI lifespan, an unprivileged configured port (normally 8080), bounded
concurrency/backlog/keep-alive/graceful shutdown, no reload/debug/access logs, no proxy trust, and
no server/date headers. Kubernetes replicas provide horizontal scaling. The HTTP surface remains
only `/v1/chat`, `/health/live`, and `/health/ready`.

Deployment catalogs are duplicate-key-free strict JSON. JSON timestamps and durations are decoded
with strict JSON semantics; the ERP Ed25519 verification key is an unpadded canonical base64url
string decoded only by the composition boundary. Secret byte values are never accepted directly
from a public request.

## Reproducible image input

The container build fixes `SOURCE_DATE_EPOCH` to `1735689600` (2025-01-01T00:00:00Z). Release
verification supplies that same immutable value to two independent no-cache OCI exports with
timestamp rewriting enabled. It compares canonical index/config/manifest bytes, ordered layers,
extracted filesystem metadata, installed APK/Python inventories, the application wheel, and Syft
inventories. SBOM and provenance envelopes are generated separately from the equality proof.

## Release and rollback

1. Verify image digest, signature/provenance, SBOM, and vulnerability report.
2. Provision or rotate separate runtime and migration secrets.
3. Verify TLS/mTLS certificates and expiry.
4. Confirm database backups or restore points.
5. Run the control-audit migration Job.
6. Run one Job for each customer audit database.
7. Run one Job for each customer knowledge database.
8. Run read-only preflight without OpenAI content.
9. Deploy one canary replica.
10. Verify readiness, synthetic internal flow, audits, isolation, and monitoring.
11. Continue the rolling deployment and observe the approved soak period.
12. Record image, configuration-contract, and deployment-value digests.

Rollback changes only the image digest and only after compatibility with current forward-only
database contracts is proven. Never reverse migrations automatically, delete audit/knowledge data,
or disable auditing, authorization snapshots, RLS, ZDR, or TLS. If compatibility is unknown, stop
traffic and invoke incident handling.

## Logging, dashboards, and alerts

Process logs are fixed JSON lifecycle events containing only event, component, outcome, severity,
and deployment version. They exclude identifiers, content, credentials, configuration, provider
errors, stack traces, and audit bodies. Platform metrics must have no customer, actor, request,
database, organization, project, prompt, or tool labels.

Dashboards and alerts cover unready replicas, crash loops, rollout failure, HTTP status/latency,
concurrency saturation, mandatory-audit failure, PostgreSQL availability/pool exhaustion,
ERP/Laravel/RAG availability, migration failure, OpenAI rate/spend/ZDR/key rotation, certificate
expiry, and backup/restore-test failure.

## Backup, restore, retention, and incidents

Use encrypted, access-audited backups with separate control-audit and customer boundaries,
customer-isolated restore, PITR where supported, separated backup credentials, and synthetic
quarterly restore tests. Deployment owners approve and record RPO/RTO, retention, legal hold, and
backup access. Knowledge deletion/re-embedding must preserve generation and audit contracts;
append-only audit constraints remain authoritative.

Incident playbooks must support safe traffic suspension and rotation/revocation for OpenAI
credentials, mTLS keys, ERP assertion signing keys, and database credentials. Cross-customer
isolation, mandatory-audit outage, privacy-attestation expiry, and certificate compromise require
traffic suspension until authorization, audit, isolation, and TLS guarantees are restored. This
step implements no deletion automation, backup product, SIEM dispatch, or cloud-specific response.

## Supply chain

Builder/runtime bases and release tooling are version-and-digest pinned. CI builds the locked wheel
and OCI image, verifies non-root/read-only/no-capability/no-network execution, renders Kubernetes,
generates an external Syft SBOM, and scans the exact image digest with pinned Trivy vulnerability
data. SBOM, provenance, and reports are release artifacts and are never committed.

The runtime base is the immutable Python 3.12.13 Alpine 3.23 digest recorded in
`deploy/container-packages.lock.json`. Every APK added beyond that base is an exact official
`v3.23/main/x86_64` artifact bound to its URL, SHA-256, signed package metadata, aports identity,
license, and runtime purpose. The Docker build verifies signatures and hashes, installs only local
artifacts with networking and repositories disabled, and retains Alpine's installed-package
database for scanners. The Dockerfile frontend and uv acquisition image are also digest-pinned.
Alpine's runtime `libpq` package supplies the versioned `libpq.so.5` SONAME, while Python's
Linux discovery assumes the glibc `ldconfig -p` interface that Alpine does not implement. The
deployment console bootstrap therefore verifies that exact SONAME, temporarily maps only the
`pq` lookup while the pure-Python Psycopg implementation imports, and restores the resolver
before invoking the selected operation. It does not bundle libpq or add build tools.

Kubernetes uses an intentionally invalid image digest placeholder and a required configuration
checksum annotation. Release automation must replace both from reviewed immutable artifacts.
Standard NetworkPolicy cannot enforce the `api.openai.com` FQDN: the checked-in default deny and
DNS-only allowance remain fail closed until the deployment platform supplies an audited
FQDN-aware egress control plus explicit PostgreSQL and internal Laravel/ERP destinations. Do not
add broad TCP 443 or `0.0.0.0/0` egress as a substitute.
