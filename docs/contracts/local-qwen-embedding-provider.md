# Local Qwen3 embedding test adapter

This integration is a test candidate, not production approval. It runs
`Qwen/Qwen3-Embedding-0.6B` (Apache-2.0) at immutable revision
`97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3` behind official Hugging Face Text
Embeddings Inference 1.9.3 CPU x86-64 image
`sha256:ad950d30878eceb72aaf32024d26fa2b1d04a75304fa0b4776b49aa1941fea07`.
No weights are stored in Git.

## Identity and transforms

Startup calls authenticated `/info` and fails closed unless model ID, full revision, TEI 1.9.3,
embedding type, `last-token` pooling, enabled server-side auto-truncation, a 1,024-token batch
budget, one batch request, one concurrent request, one tokenization worker, and client batch size
four match. The profile is 1,024-dimensional normalized float32 cosine output. Documents are
unchanged. Queries use transform version 1 exactly:

```text
Instruct: Given a user question about HR policies and ERP product documentation, retrieve relevant passages that answer the question.
Query: <query>
```

The instruction and document/query transform versions are bound into the embedding-profile digest
and are server controlled. Public/model input cannot select an endpoint, input kind, transform,
profile, or instruction.

## Resource policy and truncation boundary

The immutable local-test resource policy limits TEI to 1,024 batch tokens, one batch request, one
concurrent request, one tokenization worker, and four client inputs. TEI auto-truncation is enabled
only to reduce its warm-up allocation. The application never relies on it: it validates existing
raw byte and character limits, applies the exact server-owned transform, and sends each final
string to authenticated `/tokenize` with special tokens included. An individual input or aggregate
batch above 1,024 tokens fails before `/embed`. After validating the complete batch, the adapter
sends each identical transformed string sequentially as a one-input `/embed` request with
`truncate=false`; no partial result is returned. This preserves the one-request concurrency budget
and performs no retry. Tokenization bodies and responses are bounded and never logged.

Resource policy does not enter the embedding-profile digest because accepted text and resulting
vectors are unchanged. Its deterministic digest is required for semantic evaluation candidates,
so evaluation fingerprints retain the exact runtime-budget provenance. Public requests, model
tools, and retrieved content cannot select or modify resource limits.

TEI 1.9.3's pinned CPU backend reports an internal `max_batch_requests` value of four even when the
captured startup argument is one. Runtime provenance keeps these facts separate as
`configured_max_batch_requests=1`, `observed_max_batch_requests=4`,
`application_max_concurrent_requests=1`, and `application_execution_mode=sequential`. The resource
policy digest represents the configured policy; a separate effective runtime-identity digest binds
the observed value and application execution guarantee into evaluation fingerprints. The adapter
fails closed for any other observed value. It does **not** claim that TEI enforces one batch
request: the application independently token-validates the complete batch and executes one input
at a time. Runtime identity remains server-only and is never included in public/model contracts.

## Step 16 measurement status

The selected threshold `0.8170998503506278` is permanently labelled
`unapproved_test_only`; it is not a production default. Calibration aggregate metrics are live
verified. Holdout Arabic, English, mixed, and overall slices are live verified. Calibration
language-slice reporting was added after the single controlled TEI lifecycle was stopped and was
not live re-executed; those reporting-only slices must not be represented as live evidence without
a separately approved future run.

## Local operation

Set a synthetic `ERP_AI_TEI_API_KEY`, then run:

```powershell
docker compose -f docker-compose.embedding-test.yml up -d
$env:ERP_AI_REQUIRE_LOCAL_EMBEDDING_TESTS = "1"
$env:ERP_AI_TEI_ENDPOINT = "http://127.0.0.1:58080"
uv run pytest -m local_embedding --no-cov
docker compose -f docker-compose.embedding-test.yml down
```

The service binds only `127.0.0.1`. The server-controlled
`ERP_AI_EMBEDDING_CACHE_VOLUME` environment variable selects the named model-cache volume and
defaults safely to `erp_ai_qwen3_embedding_cache`. It is never accepted from a public request.
Normal `down` cleanup preserves the selected volume; deleting a cache is a separate, explicitly
authorized destructive operation.

The adapter uses one fixed async client with environment proxies disabled, no redirects, no
retries, bounded responses, strict JSON, normalized-vector validation, and generic failures. It
does not log queries, documents, vectors, secrets, remote payloads, or exception details.

## Abstention and evaluation

Every semantic provider requires an immutable `SemanticRetrievalPolicy` bound to namespace,
embedding-profile digest, policy version, and a minimum score in `[0,1]`. Filtering occurs only
after SQL authorization filtering. The policy digest, rather than its threshold, enters evaluation
reproducibility metadata. The threshold never enters public results or model messages.

Threshold candidates are the distinct calibration result scores plus the two boundary values,
ordered ascending. Only calibration cases may select a threshold. A candidate is eligible only
with zero security violations and calibration expected-empty accuracy 1.0; ties choose the highest
threshold after maximizing the declared nonzero quality metrics lexicographically. Holdout cases
are then evaluated once. The selected value is test-only and is not transferable across model
revision, profile, transform, corpus, language mix, or authorization distribution.

Hybrid retrieval, lexical fallback, approximate indexes, reranking, production routing, external
telemetry, production data, and production threshold approval remain out of scope. A production
decision still requires privacy/retention review, representative bilingual calibration and blind
holdout evaluation, operational capacity testing, and explicit human approval.
