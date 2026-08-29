# Production runtime composition contract

The core runtime remains provider-neutral. A deployment may supply the direct OpenAI bundle's
model provider and lifecycle lease, but `erp_ai.runtime` neither imports nor constructs OpenAI.
Customer-bound embedding providers are composed with each production RAG route externally.

Step 27 leaves core runtime composition provider-neutral. The Laravel package exposes an explicit
bundle whose handlers and lifecycle must be injected into `ExternalRuntimeBundle`; core runtime
modules neither import nor construct Laravel adapters. Construction remains I/O-free; Laravel
contract verification occurs during lifecycle startup. Laravel and customer-database routing
remain external ERP-team responsibilities.

Step 26 supplies one composition root, `compose_production_runtime`, and no server launcher.
The core reads no environment variables, `.env` files, configuration files, certificates,
keys, or secret-manager responses. A deployment-owned launcher must construct an immutable
`ExternalRuntimeBundle` from validated objects and transfer exclusive lifecycle ownership.

The bundle requires transport, assertion, ERP-trust, TLS, runtime-only audit, route, registry,
handler, model-provider, provider-lifecycle, orchestration-limit, request-ID, clock, and intent
lifetime inputs. Required security dependencies have no `None`, no-op, or ambient defaults.
Configuration models are defensively revalidated; registries, routes, handlers, and customer
routes are copied into immutable snapshots. This is structural/reference immutability: Python
cannot deeply freeze arbitrary providers, clocks, factories, or `SSLContext` internals. Dependency
references cannot be replaced through the frozen bundle, and its representation hides them. This
boundary does not prove that an injected provider has legal, privacy, quality, or security
approval; the deployment owner remains responsible for that approval.

The supplied `SSLContext` is ownership-transferred security state. The caller must never mutate it
after bundle construction. Its certificate and hostname policy is checked during composition and
again immediately before the ERP client opens, so a detectable downgrade before startup fails
closed. Python still cannot prove that a client certificate/private key was loaded; provisioning
that identity remains a deployment responsibility. Provider approval, internal thread safety, and
the safety of provider-owned mutable state likewise remain deployment-owner responsibilities.

Construction is deterministic and performs no external I/O:

1. Validate and freeze the external bundle.
2. Validate the registry and exact handler set.
3. Construct the closed runtime-only PostgreSQL audit router.
4. Construct application, agent, and tool PostgreSQL sinks from that router.
5. Construct the Ed25519 ERP authenticator.
6. Construct one closed ERP trust HTTP client.
7. Construct the resolver and snapshot verifier using that same client.
8. Validate the trusted route catalog against the installed registry and handlers.
9. Construct the read-only gateway, orchestrator, and trusted application service.
10. Construct one runtime lifecycle.
11. Construct the internal FastAPI app with the same application sink and lifecycle.
12. Return an immutable `ComposedRuntime` exposing only the app and safe runtime state.

The installed handler set must exactly match every registered descriptor by name and version.
Commands, duplicate handlers, missing or extra handlers, non-strict inputs, and unavailable
trusted routes fail before startup. Message content is never inspected for routing. There is no
fallback route, keyword matching, model inference, or authorization grant through route intent.
Gateway authorization remains authoritative.

## Runtime authority and lifecycle

`RuntimeAuditDatabaseConfig` contains writer DSNs and static identity/role expectations only.
Migration-owner DSNs, migration runners, DDL, automatic migrations, and schema repair are absent
from the composed runtime. Startup uses the frozen Step 23 verification contract; the application
sink targets control storage, while agent and tool sinks use static customer routes. Step 23 SQL,
versions, digests, checksums, RLS, ownership, privilege, and trigger contracts remain unchanged.

Each runtime starts in `created`. Startup opens and verifies audit storage, opens the ERP trust
client, then opens the external provider lifecycle. Only then is it `ready`. A failure or
cancellation performs synchronous reverse cleanup and leaves `failed`; cancellation propagates.
Shutdown first makes the runtime unavailable, then closes providers, ERP trust, and audit storage.
Every close is attempted, close failures are redacted into one generic failure, and no retry,
fallback, background task, or lifecycle audit event is created. Shutdown before startup closes
without opening resources. Startup and shutdown are serialized and execute at most once.

Readiness means configured resources opened and startup verification passed. It does not promise
that ERP, databases, or providers will remain reachable. Liveness performs no I/O. Separate
runtimes have separate state. A per-dependency `ProviderLifecycleLease` uses its own lock and no
process-global registry. A successful composition permanently consumes that lease; a failed
pre-return composition releases it. A second claim cannot silently double-open or double-close
provider resources. Python cannot prove that two different leases do not wrap the same underlying
provider, so the deployment owner must never wrap one provider lifecycle twice.

Composition is transactional. All side-effect-free validation precedes the ownership claim. If a
later constructor fails, the local lease claim is released before a generic composition error is
returned. Successful composition permanently commits the single-use claim; closing the runtime
does not make it reusable. The mechanism holds no module-global set, weak registry, object ID,
finalizer, history, or cleanup task.

The externally supplied request-ID factory remains responsible for canonical fresh UUIDv4 values,
with transport collision tracking bounded to in-flight requests. The supplied clock must return
timezone-aware values. Neither dependency is exposed by runtime representations.

The mandatory CI integration matrix runs audit storage, HTTP audit, and full production
composition tests without skips on digest-pinned PostgreSQL 15, 16, 17, and 18 images.
