# Module-code namespaces

The current contracts use three distinct identifiers that happen to describe the HR domain:

| Namespace | Current value | Purpose |
|---|---|---|
| AI capability code | `hr_core` | Identifies the immutable capability manifest |
| Canonical AI entitlement code | `hr_core` | Value injected into `TrustedRequestContext.enabled_modules` |
| RAG document namespace | `hr` | Metadata namespace for approved HR knowledge documents |

For Leave, the corresponding namespaces are:

| Namespace | Current value | Purpose |
|---|---|---|
| AI capability code | `leave` | Identifies the immutable Leave capability manifest |
| Canonical AI entitlement code | `leave` | Value injected into `TrustedRequestContext.enabled_modules` |
| RAG document namespace | `hr` | Shared approved HR knowledge-document namespace |
| RAG subdomain | `leave` | Narrows approved HR documents to Leave |

These values belong to different namespaces and must not be compared, joined, or translated
automatically. In particular, the RAG namespace `hr` and subdomain `leave` are not proof that
either the `hr_core` or `leave` AI entitlement is enabled.

The production `hr_knowledge` capability therefore requires the canonical `hr_core` entitlement
while sending the fixed `hr` namespace to its retrieval provider. Every match separately declares
all canonical AI entitlements it requires. A Leave match requires `leave`; this is validated from
trusted context and is never inferred from the query or the namespace.

The database defines `erp_module_installations.module_code` but does not provide its canonical
production values. A future trusted entitlement resolver must map raw ERP installation codes to
canonical AI entitlement codes through an explicit, allowlisted mapping. Unknown raw codes must
fail closed and must not become capability entitlements through normalization or naming guesses.

The ERP owner must confirm the raw ERP module-code values and the allowlisted mapping before any
production integration. This repository intentionally keeps the current capability and canonical
AI entitlement code as `hr_core` and adds no resolver or database access.
