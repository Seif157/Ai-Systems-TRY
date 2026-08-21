# Trusted request context contract

`TrustedRequestContext` is server-owned security context. An authenticated application adapter
implements `TrustedContextSource` and supplies its claims to `resolve_trusted_context`.

Public clients and model output may provide only conversational input. They cannot provide or
override the customer environment, actor, employee link, roles, legal entities, enabled modules,
locale, or purpose. Unknown fields fail validation.

The context deliberately contains no credentials, authorization headers, database connections,
model configuration, or secret references. Enabled modules are resolved upstream from the ERP
entitlement source; this contract validates and carries that trusted result but does not query it.

