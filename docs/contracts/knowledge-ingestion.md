# Knowledge ingestion preparation contract

This package prepares already-normalized, explicitly approved knowledge documents for a future
index writer. It does not discover files, generate embeddings, contact a provider, or mutate an
index. The separate [Markdown source adapter](markdown-source-adapter.md) reads only explicit
catalog entries and supplies validated drafts to this package.

## Accepted scope

Only approved product documentation and approved customer policies are accepted. Live employee,
leave, payroll, attendance, database export, arbitrary SQL, and unapproved upload data are
excluded. Live structured ERP information continues through typed ERP tools. A future stable
reference-data exporter requires its own reviewed typed contract.

Each immutable draft carries an exact SemVer, HR namespace, source ownership, optional tenant,
language, inherited module/permission/purpose/legal-entity scope, supported classification,
effective dates, approval evidence, and ordered immutable sections. Per-section authorization is
unsupported; content with different governance must be split into separate documents. Access is
never inferred from titles or text. Declared Leave knowledge requires both `hr_core` and `leave`.

## Normalization and chunking

Text is normalized to Unicode NFC and LF newlines, trimmed, and checked for null or unsafe control
characters. Arabic and English case/content are preserved. Possible prompt-injection text is not
rewritten or removed; prepared and retrieved content remains untrusted data.

The deterministic chunker preserves document and section order, prefers supplied block boundaries,
splits oversized blocks only at Unicode whitespace, and rejects indivisible oversized tokens.
Overlap is deterministic and section-local. It never crosses a section or authorization boundary.
Ordinals are zero-based and stable for identical normalized input and policy.

Default limits are 1 MiB normalized document text, 500 sections, 5,000 blocks, 2,000 chunks, 16 KiB
per normalized block, 2,000 characters and 8 KiB per chunk, with a 200-character overlap target.
Violations reject the entire preparation; content is never silently dropped.

## Fingerprints, identifiers, and versions

Canonical compact UTF-8 JSON and standard-library SHA-256 produce separate normalized-content and
governance hashes plus a combined document fingerprint. Governance includes version, namespace,
tenant scope, modules, permissions, purposes, legal entities, classification, effective dates, and
approval metadata. Optional path-free source provenance records the catalog version, raw hash,
parser name/major version, and adapter contract version. Content, governance, or parsing-contract
changes therefore change the combined fingerprint.

Chunk and citation identifiers derive from the fingerprint and ordinal. They expose no customer
identifier, path, filename, or content. Deterministic citation IDs are opaque references—not
secrets, credentials, or authorization proof.

An identical ID/version/fingerprint is idempotent. Reusing a version with changed content or
governance conflicts; older versions fail; a greater SemVer records the existing version as the
one superseded. First preparation cannot claim an unknown predecessor because supersession is
derived only from an injected validated existing manifest. No deletion or replacement occurs.

Approved source adapters own parsing and approval provenance. The separate
[index-publication contract](knowledge-index-publication.md) now owns customer-scoped immutable
generations, deterministic manifests, atomic activation/rollback, snapshots, and a transactional
audit outbox. A future production repository owns their durable implementation and deletion. None
of those responsibilities exists in this preparation step.
