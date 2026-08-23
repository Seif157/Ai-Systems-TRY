# Knowledge retrieval contract

Knowledge retrieval is a shared provider-neutral framework with isolated ERP-domain namespaces.
The first namespace is `hr`. Namespace metadata is not an entitlement: the `hr_knowledge`
capability requires the canonical `hr_core` entitlement, and each returned chunk declares every
additional required module such as `leave`.

The public input contains only a Unicode query of at most 1,000 characters. Namespace, result
limit, tenant, modules, permissions, roles, legal entities, purpose, locale, effective time, and
classification are server-owned. The fixed maximum is five results. Queries, matches, and content
must not be written to ordinary audit events.

The provider receives the raw query only after the gateway has authorized the tool invocation. A
production `KnowledgeRetrievalProvider` must not log, use for training, or persist queries or
retrieved content outside an explicitly approved retention policy. It must treat the trusted
retrieval scope as server-only data and apply tenant and authorization filters before similarity
search.

## Defense in depth

A production provider must apply customer, module, permission, purpose, legal-entity, effective
date, and classification filters before vector or lexical similarity retrieval. The Protocol
cannot prove this behavior, so the handler validates every returned match again and fails the
complete request if any match is malformed or unauthorized. It validates a maximum of five,
unique chunk and citation identifiers, at most 4,000 characters per excerpt, 12,000 combined
characters, and provider order by relevance descending then chunk ID ascending. It never sorts.

Global product documentation has no customer identifier. Customer policies must match the trusted
customer exactly. Non-empty document legal-entity scope must be contained in the trusted scope.
Documents must be effective at the context's `issued_at`, and classification must not exceed
`restricted`.

## Public excerpts and trust

Public excerpts contain an opaque citation, display metadata, positive integer document version,
content, and `content_trust="untrusted_knowledge_excerpt"`. Citations identify the approved source
without exposing storage or database identifiers. The trust marker is metadata, not sanitization.
Retrieved content is untrusted data and must never override system or developer instructions,
authorization, or tool-execution controls. Regex-based prompt-injection removal is intentionally
not attempted.

`citation_id` is only an opaque display reference; possession of it is not proof of authorization.
A future citation-resolution endpoint must reauthorize tenant, modules, permissions, purpose,
legal entities, and document effectiveness on every request. It must never decode or reconstruct
a storage path, direct object URL, database identifier, or other storage location from the
citation.

## Audit boundary

Knowledge search uses the existing `ToolAuditEvent` and mandatory gateway sink, not a separate
audit system. Approved correlation, customer environment, authenticated user, trusted purpose,
tool identity, governance metadata, outcome, and coarse internal gateway reason remain audit
metadata; they are not retrieval payload leakage. No query, content, title, section, citation,
document/chunk ID, score, storage location, embedding/vector metadata, employee ID, legal-entity
IDs, roles, permissions, enabled modules, provider exception, or detailed authorization denial may
enter the event. Public success and failure envelopes never contain the audit event.

Only approved product documentation and customer policies belong in this path. Live employee,
leave, payroll, or other transactional ERP data must continue through typed permission-aware ERP
tools. There is no ingestion, embedding, vector database, network, filesystem, or SQL integration
in the current implementation; tests inject in-memory fake providers.
