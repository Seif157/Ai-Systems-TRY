# Catalog-driven Markdown source adapter

The adapter is a controlled bridge from reviewed Markdown to the immutable
`KnowledgeDocumentDraft` contract. It performs no discovery, upload handling, retrieval,
embedding, indexing, networking, or publication.

## Approval and catalog

Catalog review is the approval boundary. Strict TOML uses `catalog_version = 1` and explicit
`[[entries]]`. Each entry supplies its relative path, raw SHA-256, identity/version, ownership,
scope, classification, effective dates, and approval metadata. Unknown or missing fields,
duplicate paths/document IDs/scope values, invalid governance, and unsupported versions fail
closed. Front matter is removed and cannot override catalog governance. Approval metadata is a
trusted input, not proof of authentic approval.

## File safety

The service supplies one trusted root, resolved once. Paths use relative POSIX syntax, end in
`.md`, and cannot be absolute, contain backslashes or `..`, or be supplied by public/model input.
The adapter never scans or recursively discovers files. Before resolution it performs `lstat`-style
inspection of every relative component, including the final file, so resolution cannot erase link
evidence. It rejects intermediate and final symbolic links on every platform. On Windows it also
rejects junctions and every object carrying `FILE_ATTRIBUTE_REPARSE_POINT`, including unknown
reparse types rather than allowlisting familiar tags. Inspection and permission errors fail closed.

After component inspection, the resolved final path must still remain below the resolved root. The
adapter rejects non-regular/missing files and files over 1 MiB before opening. It opens the approved
source exactly once in binary mode, compares available `lstat` identity with `fstat` identity from
that handle, requires the handle itself to be regular and non-reparse, then reads at most 1 MiB plus
one byte. Hashing and strict UTF-8 decoding use bytes from that same validated handle. A replacement,
identity/type mismatch, or growth beyond the limit fails closed.

Raw bytes are SHA-256 hashed and constant-time compared with the catalog before parsing. Decoding
is strict UTF-8 and consumes a UTF-8 BOM deterministically. Nulls and unsafe controls fail closed.
Errors, drafts, prepared bundles, citations, and public output contain no filesystem paths.
These controls substantially reduce path-substitution and time-of-check/time-of-use exposure, but
portable Python filesystem APIs cannot eliminate every platform/kernel-level TOCTOU possibility.

## Token extraction

`markdown-it-py` 4.x uses a fixed CommonMark configuration: linkify and typographic rewriting are
disabled, nesting is bounded, no HTML is rendered, and the built-in table rule is enabled. The
adapter consumes tokens and loads no plugins.

Supported content includes headings, paragraphs, ordered/unordered lists, blockquotes, tables,
inline code, fenced/indented code, horizontal-rule boundaries, image alt text, and link labels.
Link destinations, image paths, reference destinations, raw HTML, and front matter are excluded.
Code and prose remain untrusted text: nothing is executed, fetched, included, imported, or
regex-filtered for prompt injection. Unsupported meaningful token structures fail closed.

Sections preserve order and heading ancestry. Preamble and heading-less content receive
deterministic sections. Ordinal section keys make duplicate headings stable and unique. Empty
headings, blocks, and sections are forbidden; parents without direct content appear in child paths.

## Provenance and boundaries

Path-free internal provenance records catalog version, raw hash, parser name/major version, and
adapter contract version. Step 10 fingerprints that provenance, so parser behavior changes cannot
silently reuse chunks.

`docs/database/hr` is internal engineering material and is not employee-facing RAG content. PDF,
DOCX, HTML, crawling, database exports, includes, and arbitrary uploads remain unsupported. Future
customer-policy integration requires a controlled tenant source, approval/retention controls, and
isolated publication design.

The primary Linux CI job enforces tests, coverage, Ruff, formatting, and mypy. A separate Python
3.12 Windows job runs the locked environment and complete pytest suite. Privilege-dependent real
link tests may skip, while platform-neutral inspection-decision tests always exercise symlink,
junction, and generic-reparse rejection.
