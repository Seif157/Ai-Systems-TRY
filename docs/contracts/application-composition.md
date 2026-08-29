# Provider-neutral application composition

OpenAI project selection and privacy authorization occur behind the provider-neutral model
boundary using trusted context injected by this application layer. No project, credential,
model, endpoint, classification, or privacy mode is accepted from `PublicChatRequest`.

The production binding is defined by `production-runtime-composition.md`. It constructs the
trusted application only after exact registry/handler and route-catalog validation, shares one
application audit sink with transport, and performs no message-based route inference.

`TrustedChatApplication` fixes the internal processing order:

1. revalidate the public request and opaque trusted reference;
2. resolve and revalidate trusted context plus route intent;
3. verify exact bindings, timestamps, and bounded lifetime;
4. verify authorization-snapshot freshness once;
5. resolve the allowlisted server intent deterministically;
6. invoke `AgentOrchestrator` once;
7. attempt one application audit before returning the existing public result.

Failures before orchestration produce zero agent and tool audits. Invoked orchestration retains its
exactly-once agent audit; only `ReadToolGateway` controls tool auditing. Every terminal path attempts
one outer application audit. Its exact allowlist is request ID, coarse stage, outcome, and hidden
internal reason. It excludes message, response, handle, identities, context, intent, route, tool,
arguments, results, authorization collections, snapshot ID, and provider details. Audit delivery
failure withholds success and returns the existing generic audit-unavailable response.

Cancellation propagates unchanged and is not converted into a completed public result. The
exactly-once application-audit guarantee applies to completed outcomes. Audits are neither retried
nor shielded, and no background audit task is created.

Composition requires the resolver, snapshot verifier, route catalog, orchestrator, application
audit sink, trusted clock, and maximum intent lifetime explicitly. It validates routes against the
orchestrator's registry and installed gateway handlers. Production code supplies no fake/no-op
dependency, environment reader, credential, OpenRouter/PostgreSQL construction, HTTP endpoint, or
hidden default.

The current OpenRouter model remains synthetic-test-only. Production transport, trusted ERP
identity integration, intent minting, snapshot verification, audit delivery, provider/privacy
approval, and operational lifecycle remain future work.

Step 23 supplies a PostgreSQL application sink for the unchanged four-field event. It targets only
the central control-plane audit database and cannot store resolved customer or user identity. See
[`postgres-audit-storage.md`](postgres-audit-storage.md).

## Internal transport composition

The Step 24 HTTP application factory requires the trusted application, ingress authenticator,
server request-ID factory, application audit sink, and lifecycle owner explicitly. It does not
construct OpenRouter, PostgreSQL, ERP, knowledge, resolver, verifier, gateway, or orchestrator
dependencies. Pre-application failures are audited by the transport; forwarded requests are
audited only by the existing trusted application.
Step 25 provides concrete authenticator, resolver, and authorization-snapshot verifier adapters,
but deliberately does not add production FastAPI composition. Future composition must inject the
static verification keyring, aware clock, fixed ERP trust origin, and externally provisioned mTLS
`SSLContext`, then explicitly open and close the shared trust client.
