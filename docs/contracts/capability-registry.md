# Capability registry contract

The capability registry is an immutable in-memory snapshot of validated `CapabilityManifest`
objects. It performs no filesystem, database, SQL, network, model, or tool-execution work.

## Manifest and tool contracts

Every manifest declares a normalized capability code, version, required ERP modules, and its tool
descriptors. Capability and tool versions use exactly `MAJOR.MINOR.PATCH`, with no leading zeroes,
prerelease labels, or build metadata. Each tool declares a normalized name, `read` or `command`
operation, all required permissions, any accepted role, allowed purposes, data classification,
and audit action. Models are strict and frozen, reject unknown fields, normalize code collections,
and reject duplicate modules, permissions, roles, purposes, tools, capabilities, and global tool
names.

`data_classification` is one of `public`, `internal`, `restricted`, or `highly_restricted`.
Permission and audit-action codes accept strict lowercase dotted segments. Capability, module,
role, purpose, and tool codes remain lowercase snake case and do not accept dots.
`audit_action` is a canonical non-empty code. Both classification and action remain server-side
governance metadata and are deliberately absent from the minimal model-facing tool projection.

The registry sorts capabilities and tools by code/name so registration and access results are
deterministic. Manifests are supplied by trusted application startup wiring; YAML parsing and
dynamic package discovery are outside this step.

## Entitlement-aware access

`evaluate_capability_access` uses only `TrustedRequestContext.enabled_modules`,
`permission_codes`, `roles`, and `purpose`:

- Every required module must be enabled before a capability is model-visible.
- Every `required_permissions_all` value must be present. An empty tuple adds no permission rule.
- At least one `required_roles_any` value must be present when the tuple is non-empty. An empty
  tuple adds no role rule.
- The trusted context purpose must exactly match an `allowed_purposes` value. Wildcards are not
  supported.
- Command descriptors are excluded when `read_only_mode=True`; no command execution exists.
- Disabled capabilities and tools are absent from `model_capabilities`.
- Denial reasons exist only in the server-side `CapabilityAccessDecision.denials` collection and
  must not be placed in model-facing configuration.

`read_only_mode` defaults to `True` and is server-controlled. `PublicChatRequest` is never an
entitlement, authorization, purpose, or release-mode source and rejects forged module, permission,
role, purpose, and `read_only_mode` fields.

## Upstream responsibility

The ERP table `erp_module_installations` will eventually be resolved by an authenticated trusted
upstream provider into `TrustedRequestContext.enabled_modules`. The registry must never query that
table or hold customer database credentials. Freshness and authenticity remain the responsibility
of the trusted context resolver described in the trusted request-context contract.

The HR Core self-profile manifest is the first production capability contract. Other HR Core,
Leave, and Payroll manifests used by registry unit tests remain synthetic fixtures and are not
production registrations.
