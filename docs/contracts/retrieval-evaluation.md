# Retrieval evaluation contract

Step 15 provides an offline, provider-neutral evaluation boundary for the production
`KnowledgeRetrievalProvider` contract. It compares lexical and exact-semantic candidates
independently against the same declared cases and trusted synthetic authorization scopes. It does
not route production traffic, evaluate generated answers, or select a provider for a public user.

## Dataset governance and safety

Every suite declares `approved_synthetic` or `approved_sanitized` governance and binds a suite
version to an exact published-corpus generation digest. Synthetic customer identifiers must use
the explicit `synthetic_` prefix. Dataset authors must exclude real employee identifiers,
production customer identifiers, payroll or attendance rows, credentials, raw request contexts,
database rows, embeddings, and database schema documents presented as employee-facing knowledge.

Queries and authorization scopes are input-only and hidden from representations. Reports contain
aggregate metrics and opaque failing case IDs only. They contain no query, excerpt, title, vector,
provider exception, or retrieved payload. Evaluation fixtures live under `tests/` and are not
exported by the production package.

## Deterministic metrics

For a declared cutoff `k`, the provider may return at most `k` results and its ordering is
preserved:

- Precision@k is the number of relevant returned results divided by `k`. An unfilled result list
  therefore does not receive the precision of a full list.
- Recall@k is relevant returned results divided by all declared relevant results. With no declared
  relevant results it is zero and the case is evaluated by expected-empty accuracy instead.
- MRR@k is the reciprocal rank of the first relevant result, or zero when none is returned.
- nDCG@k uses `(2^grade - 1) / log2(rank + 1)` for relevance grades 1 through 3 and divides by the
  ideal DCG at `k`; an empty ideal ranking yields zero.
- Expected-empty accuracy is one when an expected-empty case returns nothing and zero otherwise.
- Unexpected-provider-failure count records provider errors or malformed results; failures are
  never converted into successful empty results.
- Forbidden-result count counts explicitly forbidden chunk or citation identifiers.
- Authorization-leak rate is unauthorized returned results divided by all returned results, and is
  zero when no results were returned. Cross-customer results are also counted separately.

Relevance metrics are macro-averaged across non-empty cases. Expected-empty accuracy is averaged
only across expected-empty cases and defaults to one for a slice containing none. Reports include
overall, Arabic, English, mixed-language, product-documentation, and customer-policy slices. Empty
relevance slices have zero relevance metrics.

## Gates and failures

Callers must provide every quality threshold; this contract defines no universal acceptable
quality. A threshold miss is a `quality_failure`. Any forbidden, cross-customer, module,
permission, purpose, legal-entity, classification, or effective-date leak is an unconditional
`security_failure`, regardless of quality. A missing candidate, provider exception, invalid match,
duplicate result, or excess result is an `infrastructure_failure`. Security takes precedence over
infrastructure, which takes precedence over quality in the aggregate disposition.

## Reproducibility

The evaluation fingerprint is SHA-256 over canonical compact UTF-8 JSON containing the complete
suite contract, suite and corpus versions, candidate type, semantic embedding-profile,
server-owned embedding resource-policy, and observed effective runtime-identity digests when
applicable, cases and slices, limits, and metric thresholds. Configured and observed runtime values
remain distinct; changing either digest changes the fingerprint. Keys are sorted, Unicode is
preserved, and execution timestamps are excluded.
Candidates and cases run sequentially in declared order;
the service performs no retry, fallback, sorting, or result mutation.

Lexical and semantic results remain separate because combining them would introduce unapproved
ranking weights and obscure regressions. Hybrid retrieval, RRF, approximate vector indexes, and
production routing are deferred. A future real embedding model requires an approved immutable
profile, privacy and retention review, multilingual quality thresholds, reproducible corpus
evaluation, and passing security gates. The deterministic fake provider used by tests establishes
only mechanics and ranking reproducibility; it is not evidence of Arabic, English, mixed-language,
or paraphrase quality.
