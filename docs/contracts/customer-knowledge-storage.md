# Customer knowledge storage

Knowledge storage is one dedicated PostgreSQL/pgvector database per customer. It is not an
ERP database and shares neither connections nor credentials with Laravel, application
audit, or customer agent/tool audit storage. Runtime receives only a non-owner,
non-superuser, non-`BYPASSRLS` reader identity without database/schema creation or data
mutation privileges.

The reader can select only the eight required knowledge relations and the `migration_name`
and `sha256` columns of migration metadata. It cannot read migration timestamps, use
sequences, invoke mutation functions, inherit another role, create temporary objects, or
write any knowledge relation. RLS is enabled and forced on all tenant relations, including
the singleton database identity. Startup compares exact policy, ownership, grant, function,
index, extension, and relation signatures rather than trusting a database-reported digest.

The relational schema retains database identity, immutable generations, active publication
identity, documents, chunks, governance scope, effective dates, embedding profiles, ready
embedding sets, and exact vectors. Retrieval accepts only an active generation with a
complete ready embedding set matching the configured model profile. RLS and the
transaction-local trusted customer scope remain defense in depth even though every database
is customer-specific.

Offline administration is separate from runtime. An approved ingestion system must
authenticate administrators, use allowlisted customer routes, accept only governed source
types, remove active prompt-injection content under an approved policy, chunk and hash
deterministically, embed using the exact approved revision, validate source ownership and
citations, and publish an immutable generation atomically. Replacement, retention, legal
hold, deletion, backup, restore, re-embedding, monitoring, and disaster recovery remain
operational responsibilities. No public upload endpoint or crawler is provided.

Migration `0004_force_database_identity_rls.sql` is additive; migrations 0001–0003 remain
byte-for-byte frozen. Existing databases must be upgraded through the administrative
migration boundary and then rerun the idempotent runtime-grant provisioning operation before
the new reader starts. Runtime startup never applies migrations or repairs privileges.
