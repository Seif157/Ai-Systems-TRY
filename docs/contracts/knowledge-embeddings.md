# Knowledge embedding contract

Embeddings are an internal, provider-neutral representation of already approved immutable
knowledge chunks. An `EmbeddingProfile` fixes the provider/model revision, dimensions, cosine
metric, float32 storage, normalization version, allowed classifications, and a deterministic
profile digest. Profile metadata is server-only: it must not enter public results, model messages,
tool audits, or agent audits.

Providers receive only an immutable profile and opaque input ID, approved text, and its content
SHA-256. They never receive customer identity, roles, permissions, legal entities, enabled modules,
or request context. Results must correlate exactly: missing, duplicate, additional, mismatched, or
wrong-dimensional vectors fail the entire batch. Cancellation propagates; retries are deferred.

Values are converted to finite IEEE-754 float32 values before use. Boolean, nonnumeric, NaN,
infinite, overflowing, zero-cosine, and wrong-dimensional vectors are rejected. Vector hashes use
canonical big-endian float32 bytes rather than string formatting.

Materialization binds every stored chunk exactly once to its chunk ID and content hash, and binds
the complete set to customer scope, namespace, immutable generation ID/digest, and profile digest.
Batches are bounded and the deterministic set digest does not alter the publication digest. Text
and vectors use repr-safe models and must never be logged or audited.

Migration 0003 stores profiles, complete sets, vectors, idempotent operations, and a minimized
transactional outbox. A set becomes readable only after count, dimension, content-hash, and digest
verification in one transaction. Ready sets and vectors are immutable; no deletion, garbage
collection, HNSW, or IVFFlat exists.
