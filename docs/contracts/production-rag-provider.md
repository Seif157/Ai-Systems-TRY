# Production RAG provider contract

The production provider reuses `KnowledgeRetrievalProvider`, the frozen knowledge models,
the injected embedding protocol, and the established exact pgvector cosine query. It does
not generate answers, rerank results, fall back to lexical search, or mutate knowledge.

Each approved customer has one statically configured, physically separate AI-owned
knowledge database. A route binds the trusted customer environment to an exact database
name and identity, reader role, secret DSN, contract digest, embedding model revision and
dimension, and bounded pool/timeouts. Customer input never constructs connection data.
Unknown routes fail before embedding or database access.

The runtime role has read-side authority only. Publisher and migration credentials cannot
be represented by the production route model. Startup opens each reader pool, verifies the
database and customer identity, PostgreSQL and pgvector versions, ordered migration hashes,
embedding identity, runtime role attributes, exact grants, forced-RLS and policy signatures,
the required lexical GIN index, and absence of database/schema creation privileges before
publishing the router. Partial startup closes every opened pool.

Retrieval first validates the immutable request, then performs exactly one query-embedding
attempt outside the database transaction. It subsequently uses one read-only,
repeatable-read transaction and the established parameterized query. Ordering remains
cosine distance ascending with `chunk_id` ascending as the stable tie-breaker, with the
existing maximum of five results. The handler retains the existing authorization,
effective-date, scope, citation, duplicate, and total-content validation.

Every retrieval transaction revalidates the configured database and session identities,
trusted customer scope, active generation and digest, ready complete embedding set, exact
embedding profile, and ordered migration hashes before running the semantic query. The
query uses exact `OPERATOR(public.<=>)` cosine distance and derives relevance as
`1 - distance / 2`; it rejects non-finite or out-of-range distance/score values and never
uses `hnsw` or `ivfflat`. The GIN index is required only for the separately established
lexical path and does not accelerate exact cosine retrieval.

Query text may leave the service only through the explicitly injected embedding provider.
It must never enter logs, exceptions, audits, or persistence. Production privacy approval
for the embedding provider remains a deployment prerequisite. The provider-neutral Python
protocol cannot cryptographically prove the remote embedding service's identity or privacy
behavior; deployment controls must establish those properties.

The provider returns only existing `KnowledgeMatch` values. Public citations remain the
existing minimal display references; citation identifiers are not authorization proof.
Retrieved content, vectors, storage identifiers, database identity, and provider errors do
not enter audit events. Existing application, agent, and tool exactly-once audit behavior is
unchanged, including fail-closed handling when audit delivery fails.

The immutable production bundle owns the reader-pool router lifecycle and references—but
does not own or close—the injected embedding provider. Construction performs no I/O.
Runtime startup opens and verifies pools; shutdown closes them in reverse order. No mutable
global pool registry exists. Concurrent startup and shutdown are serialized. Startup opens
each pool exactly once, and partial failure or cancellation closes opened pools in reverse
order. Shutdown is idempotent and makes the router permanently unavailable. Independent
application instances have independent lifecycle state.

Contract version is `1.0.0`. Its insertion-ordered compact UTF-8 JSON SHA-256 digest freezes
the three previously released migrations plus the additive identity-RLS migration, their
checksums, exact relation/security/compatibility signatures, and the established semantic
algorithm, parameter order, namespace, result limit, and ordering. It uses no sorted-key
reordering and no trailing newline.
The digest is `8ba30675da37ccab818d8b7ed8a6d243ca584aff28c84184f30105041be2ba0b`.
It also freezes the exact ordered names and PostgreSQL type strings of every relation field
read during verification or retrieval. The three earlier migration resources remain
byte-for-byte unchanged. Migration `0004` is required to force RLS on database identity:

- `0001_knowledge_schema.sql`: `23a4fa93f005fd79c92b9243bbfb0daff9af02cb2868e65b6de6bda21d4f595b`
- `0002_knowledge_security.sql`: `2f2842df084e09670fa2284059d183d873d39b4c5e78ce04d0880082ab6e3455`
- `0003_knowledge_embeddings.sql`: `a6b0c8b8e586c964479d937e7555a894c1acfa6891450f9d0bd13b958a0f66d6`
- `0004_force_database_identity_rls.sql`: `ab0ee110e577440b4d8b2a7a04c797d8c1d7334eab65a4926eae5a8f56cb3187`
