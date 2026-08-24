# Hybrid knowledge retrieval contract

Step 17 defines a provider-neutral, server-controlled hybrid candidate. It is evaluation-only;
it does not replace the production HR knowledge provider and does not approve a production
semantic threshold.

## Deterministic fusion

PostgreSQL returns independently authorized lexical and exact-cosine candidate lists. Trusted
application code combines one-based ranks using weighted Reciprocal Rank Fusion:

`lexical_weight/(rank_constant+lexical_rank) + semantic_weight/(rank_constant+semantic_rank)`

Missing ranks contribute zero. Ordering uses exact rational arithmetic, then `chunk_id` ascending.
Raw lexical scores and cosine values are never combined or exposed. Duplicate candidates, limit
violations, generation mismatches, or differing immutable metadata for the same chunk fail closed.

## Snapshot and authorization

The query is transformed and embedded exactly once before database access. Identity validation,
one active-generation resolution, complete embedding-set verification, lexical retrieval, and
semantic retrieval occur in one read-only `REPEATABLE READ` transaction. Both SQL paths filter
customer/source ownership, namespace, generation, modules, permissions, purpose, legal entities,
effective dates, classification, and the exact semantic profile before ranking. Results are
defensively revalidated. An operational semantic failure fails the complete request; an authorized
empty list from either path is valid.

## Policy and public boundary

The frozen policy binds candidate/final limits, integer weights, rank constant, generation and
embedding-profile digests, the semantic threshold, its `unapproved_test_only` status, and TEI
resource/runtime provenance. It is server-owned and unavailable to public or model input. Public
knowledge matches retain the existing citation shape and untrusted-excerpt marking; no query,
rank, score, vector, generation, policy, runtime identity, or authorization data is projected.

Evaluation executes lexical, semantic, and hybrid candidates sequentially with no retries, winner
selection, fallback, or production promotion. Fingerprints include the candidate and all bound
provenance. Approximate indexes, rerankers, and model-selected routing remain out of scope.

## Step 17 evaluation limitations

On the controlled live dataset, hybrid retrieval matched semantic retrieval and did not improve
its aggregate or language-slice quality metrics. The live Qwen evaluation covered product
documentation only; customer-policy retrieval quality remains unverified with real Qwen
embeddings. This small synthetic dataset cannot approve either semantic or hybrid retrieval for
production use. The threshold and its `unapproved_test_only` status must be supplied explicitly
by trusted evaluation configuration and are not module-level defaults. Exact vector-search
latency and capacity remain unbenchmarked at production corpus scale.
