# Read-only ERP tool gateway contract

For Laravel-backed reads, gateway denial occurs before any outbound request. Gateway authorization
does not grant ERP access: Laravel independently revalidates the snapshot and business scope. The
gateway has no URL, database, cursor-signing, or Laravel routing authority.

Production composition requires an exact one-to-one registry/handler match and rejects command,
missing, extra, duplicate, wrong-version, or non-strict handlers before startup. The gateway keeps
read-only authorization authoritative and uses the tool sink from the same audit router as the
application and agent sinks.

`ReadToolGateway` is the only approved execution boundary for model-requested read tools. It is
an immutable in-memory service constructed from a validated `CapabilityRegistry`, a fixed
collection of trusted `ReadToolHandler` implementations, and a mandatory `ToolAuditSink`. It
performs no discovery, filesystem, database, SQL, network, model, RAG, or command-execution work.

## Handler registration

Every handler declares a tool name and `MAJOR.MINOR.PATCH` version, strict frozen Pydantic input
and output models, and an async `execute` method. Trusted context is passed to that method as a
separate argument from the validated model-provided input.

Gateway construction fails when:

- A handler name is duplicated.
- No registered descriptor matches a handler.
- Descriptor and handler versions differ.
- A handler targets a command descriptor.
- An input or output model is not strict and frozen.
- An input model permits unknown fields.

Only tools that are both authorized for the current trusted context and backed by installed
handlers appear in `available_tools`. Registration is deterministic and contains no global mutable
state. Current tests use fake handlers only; no HR or other production tool is implemented.

## Invocation and authorization

`ToolInvocation` contains only a normalized tool name, exact version, and recursively immutable
arguments. `TrustedRequestContext` is always supplied separately. For every invocation, the
gateway recalculates capability access with `read_only_mode=True`; it does not trust an earlier
model-facing tool list. Modules, all-required permissions, any-required roles, and purpose are
therefore rechecked immediately before execution.

The gateway then verifies descriptor and handler registration, rejects commands, rejects reserved
trusted-context keys anywhere in nested arguments, validates the handler input, invokes the
handler, and validates its output. Handler exceptions and invalid output never produce success.

Reserved argument names are the trusted-context fields plus `read_only_mode`, except `request_id`.
That name may be an explicitly declared business-record selector, as it is for
`get_my_leave_request`; it never replaces the separately supplied trusted correlation request ID.
Any such selector must be declared by the handler's strict input model and independently scoped by
the handler and future ERP application API. Undeclared selectors and all other trusted-context
names still fail closed.

## Read-only enforcement

Read-only mode is unconditional inside this gateway. There is no public or method parameter that
can disable it. Command descriptors are rejected with `READ_ONLY_VIOLATION`, command handlers
cannot be registered, and command execution is not implemented. The capability layer's optional
`read_only_mode=False` behavior cannot alter this gateway.

## Public results and safe errors

Successful handler output is revalidated into the handler's frozen output model before being
returned in `PublicToolSuccess`. That public model contains only tool name, version, and verified
result. `PublicToolFailure` contains only tool name, version, safe error code, and safe message.
Neither public model can contain audit events, internal reasons, actor/customer context,
authorization collections, purpose, classification, audit action, arguments, or exception detail.

Failures use one stable code:

- `TOOL_UNAVAILABLE`
- `INVALID_TOOL_ARGUMENTS`
- `READ_ONLY_VIOLATION`
- `TOOL_EXECUTION_FAILED`
- `INVALID_TOOL_OUTPUT`
- `AUDIT_UNAVAILABLE`

Safe messages do not identify disabled modules, missing roles or permissions, validation values,
handler exception details, stack traces, or denied capabilities. Authorization failures collapse
to `TOOL_UNAVAILABLE`.

## Mandatory audit delivery

Every attempt produces an immutable `ToolAuditEvent` containing request/customer/user identifiers,
tool name and version, manifest audit action and classification, outcome, internal reason code, and
trusted purpose. It contains no raw arguments, output, employee ID, roles, permissions, enabled
modules, or legal-entity IDs.

For knowledge retrieval, approved customer/user/purpose fields are governance metadata rather than
retrieval payload. Query text, excerpts, display metadata, citations, document/chunk identifiers,
scores, storage or vector metadata, provider exceptions, and detailed denial information are
prohibited. The internal reason remains a fixed coarse gateway code.

The gateway awaits exactly one `ToolAuditSink.record(event)` call before returning every public
success or failure. There is no default or no-op sink. If recording raises, the gateway performs no
retry, withholds any successful handler output, and returns a generic `AUDIT_UNAVAILABLE` public
failure without exception details. The failed attempt is not followed by a second audit attempt.

Internal reasons remain server-side and are delivered only to the sink. A future production sink
must provide customer isolation, retention, access control, durability, and documented delivery
guarantees. Application code must not treat `repr=False` as a substitute for safe logging.

## Current limitations

The provider-neutral agent orchestrator may present authorized public input schemas to a model, but
the catalog remains advisory. Every model-selected invocation still passes through this gateway's
independent authorization, validation, execution, and tool-audit boundary. Agent-level terminal
auditing is separate and does not replace any tool audit.

- Handlers are trusted in-process objects; the Protocol cannot establish their provenance.
- The gateway enforces manifest authorization but cannot replace record-level authorization and
  data minimization in the future ERP API handler.
- There is no timeout, cancellation, retry, circuit breaker, rate limit, or production audit sink.
- Audit timeout, retry, and circuit-breaker policies remain deferred until external ERP and audit
  integrations are designed together.
- Context freshness and authorization snapshot verification remain upstream responsibilities.
- Tool results are typed but no public response-redaction policy exists yet.

Step 23 routes the unchanged tool event to the statically configured customer audit database. The
sink cannot access arguments, results, ERP pools, or knowledge pools.
