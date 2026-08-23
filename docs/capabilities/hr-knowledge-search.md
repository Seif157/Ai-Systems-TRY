# HR knowledge search

`search_hr_knowledge` version `1.0.0` is a read-only production capability contract for approved
HR product documentation and customer policies.

Authorization requires `hr_core`, permission `hr.knowledge.read`, and purpose
`employee_self_service`. It has no literal role or linked-employee requirement. The capability
code is `hr_knowledge`; the isolated retrieval namespace is `hr`. Leave material must explicitly
require `leave`, and payroll material must explicitly require its canonical entitlement. Query
text never determines module access.

The provider receives a fixed namespace and result limit plus trusted customer, module,
permission, role, legal-entity, purpose, locale, and effective-time scope. It must filter before
retrieval. The handler then independently verifies tenant ownership, entitlements, authorization,
effective dates, classification, limits, uniqueness, and canonical ordering before constructing
the public allowlist.

An empty authorized result is successful. Provider errors or any invalid match fail with the
gateway's generic safe error. The existing mandatory audit sink receives exactly one invocation
outcome and no query, content, titles, citations, document/chunk IDs, scores, or raw authorization
collections. Public content is labeled `untrusted_knowledge_excerpt`; that label does not make the
text executable or trusted.

The established audit identity and governance fields—trusted correlation ID, customer
environment, authenticated user, purpose, tool identity, audit action, classification, outcome,
and coarse gateway reason—remain allowed and are not retrieval payload. Employee ID, legal-entity
IDs, roles, permissions, modules, provider exceptions, and detailed denial reasons remain
prohibited. Public results contain no audit event, and audit delivery failure withholds retrieved
results and returns `AUDIT_UNAVAILABLE`.

The provider receives raw query text only for an already-authorized retrieval and must not log,
train on, or persist query/content outside approved retention. Citation IDs are opaque display
references, not authorization grants. Future citation resolution must reauthorize every scope and
effectiveness rule and must never derive storage paths or direct object URLs from a citation.

Production storage, ingestion approval, deletion/supersession, citation resolution, hybrid search,
tamper resistance, and customer-isolated delivery remain future responsibilities.
