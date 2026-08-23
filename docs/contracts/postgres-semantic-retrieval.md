# PostgreSQL exact semantic retrieval

Server wiring selects lexical or semantic retrieval; public/model requests cannot choose a mode.
The lexical provider remains unchanged and there is no automatic fallback or hybrid weighting.

The semantic provider embeds the authorized raw query through the configured provider-neutral
profile, then opens one read-only repeatable-read transaction. It searches only the active
publication generation and only a complete ready set with the exact profile digest. An older
generation is never an implicit fallback.

Fixed parameterized SQL applies customer, namespace, source ownership, enabled modules,
permissions, purpose, legal entities, effective dates, profile classifications, and the existing
maximum `restricted` release boundary before exact cosine ranking. Results order by cosine
relevance descending and chunk ID ascending. Cosine similarity is mapped monotonically from
`[-1, 1]` to the existing `[0, 1]` relevance contract.

Public matches and citations preserve the existing schema and exact document SemVer. They expose
no vector, distance, embedding profile, provider, model, or storage metadata. Query text, vectors,
provider output, and exceptions remain absent from audits and public failures.

The current deterministic test provider proves mechanics and isolation only. It makes no claim
about Arabic, English, or multilingual semantic quality. Production provider selection, privacy,
retention, timeout, retry, rate-limit, and quality evaluation remain separate approvals.
