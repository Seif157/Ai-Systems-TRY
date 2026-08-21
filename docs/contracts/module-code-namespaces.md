# Module-code namespaces

The current contracts use three distinct identifiers that happen to describe the HR domain:

| Namespace | Current value | Purpose |
|---|---|---|
| AI capability code | `hr_core` | Identifies the immutable capability manifest |
| Canonical AI entitlement code | `hr_core` | Value injected into `TrustedRequestContext.enabled_modules` |
| RAG document namespace | `hr` | Metadata namespace for approved HR knowledge documents |

These values belong to different namespaces and must not be compared, joined, or translated
automatically. In particular, the RAG namespace `hr` is not proof that the `hr_core` AI
entitlement is enabled.

The database defines `erp_module_installations.module_code` but does not provide its canonical
production values. A future trusted entitlement resolver must map raw ERP installation codes to
canonical AI entitlement codes through an explicit, allowlisted mapping. Unknown raw codes must
fail closed and must not become capability entitlements through normalization or naming guesses.

The ERP owner must confirm the raw ERP module-code values and the allowlisted mapping before any
production integration. This repository intentionally keeps the current capability and canonical
AI entitlement code as `hr_core` and adds no resolver or database access.
