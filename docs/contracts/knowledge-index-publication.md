# Knowledge index publication contract

Prepared bundles are published as immutable, customer-scoped full generations. Publication never
updates active chunks in place. A repository transaction persists an invisible candidate, checks
the expected active generation, activates the complete candidate, retires the previous generation,
persists one idempotent operation result, and writes one audit-outbox event. Failure leaves none of
those changes visible, so readers observe either the complete old generation or the complete new
one.

This package defines contracts and validation only. It has no PostgreSQL, pgvector, SQL, embedding,
search, network, or production storage adapter. The atomic in-memory repository exists under tests
only; a future adapter must actually provide the Protocol's transaction guarantee.

## Trusted scope and validation

`KnowledgePublicationContext` is strict, frozen server input containing operation/correlation IDs,
customer, authenticated administrative actor or service, namespace, installed modules,
authorization snapshot, and an aware issuance time. It never comes from public chat, tools, models,
retrieval results, or source catalogs. Its type does not prove authentication or authorization; a
trusted administrative resolver remains responsible for both and for stale-snapshot validation.

Every `KnowledgeIndexScope` has a namespace and customer. A generation can combine global product
documentation (no document customer) with policies for exactly that customer. There is no shared
cross-customer active pointer; global content may later be replicated into each customer's physical
knowledge store.

The publisher reconstructs strict models at its boundary to reject `model_construct` bypasses. It
checks namespaces, tenant ownership, installed modules, effective dates, supported classification,
manifest hash composition, deterministic chunk/citation IDs, contiguous ordinals, chunk/manifest
metadata, invariant chunk governance, uniqueness, non-empty totals, and server limits. Forbidden
storage paths, URLs, embeddings, relevance scores, and arbitrary fields are absent from the strict
prepared/publication schemas. Since a prepared bundle does not retain original section blocks or
approval inputs, publication cannot independently recreate Step 10's content/governance hashes; it
verifies their composition and all information retained in the prepared artifact.

Defaults allow 10,000 bundles/documents, 500,000 chunks, and 2 GiB normalized source content per
call. Totals are checked incrementally. The generation digest is incremental SHA-256 over canonical
compact UTF-8 JSON records sorted by document UUID/version. It binds scope, contract version,
document IDs/versions/fingerprints, governance and source-provenance fingerprints, ordered chunk
IDs/content hashes, and aggregate counts/bytes. It does not depend on caller, dictionary,
filesystem, or locale order.

## Concurrency, idempotency, and snapshots

First publication requires an expected active ID of `None`; replacement requires the exact current
ID. The repository uses compare-and-swap and returns a safe conflict for stale writers. Operation
IDs are idempotency keys: the same operation and digest returns the original result without another
generation or outbox row; reuse with another scope/digest fails. Generation and outbox UUIDs are
server-created.

Retrieval first acquires one immutable `KnowledgeIndexSnapshot` containing scope, active generation
ID, generation digest, and publication-contract version. A future query must bind every retrieval
operation to that ID and never reread the active pointer midway. Candidate generations are never
available through this snapshot. This contract adds no query, scoring, ranking, or vector behavior.

## Transactional audit outbox and rollback

Publication writes no best-effort external audit event. The same database transaction must persist
one immutable allowlisted outbox record containing only operation/request/customer/actor/namespace,
action, previous and activated IDs, generation digest, and success outcome. It excludes content,
titles, paths, citations, document/chunk collections, authorization collections, approval text, and
exceptions. Future delivery is at-least-once; consumers must deduplicate by outbox ID. External
exactly-once delivery is not claimed, and no dispatcher exists yet.

Rollback uses trusted context, CAS against the current active ID, and an existing retained
generation in exactly the same scope. It atomically retires the current generation, activates the
unaltered target, persists the idempotent result, and adds one outbox event. Candidates, missing or
cross-scope targets fail. Historical contents are never rebuilt. Physical deletion, retention
expiry, and garbage collection are future policies, as are PostgreSQL/pgvector persistence,
transaction isolation, recovery, outbox dispatch, and operational monitoring.
