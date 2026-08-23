CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS erp_ai_knowledge;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

CREATE TABLE IF NOT EXISTS erp_ai_knowledge.schema_migrations (
    migration_name text PRIMARY KEY,
    sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    applied_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS erp_ai_knowledge.database_identity (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    customer_environment_id text NOT NULL CHECK (length(customer_environment_id) BETWEEN 1 AND 128),
    provisioned_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    schema_contract_version integer NOT NULL CHECK (schema_contract_version = 1)
);

CREATE TABLE IF NOT EXISTS erp_ai_knowledge.generations (
    customer_environment_id text NOT NULL,
    namespace text NOT NULL CHECK (namespace ~ '^[a-z][a-z0-9_]{0,63}$'),
    generation_id uuid NOT NULL,
    generation_digest text NOT NULL CHECK (generation_digest ~ '^[0-9a-f]{64}$'),
    publication_contract_version integer NOT NULL CHECK (publication_contract_version = 1),
    document_count integer NOT NULL CHECK (document_count > 0),
    chunk_count integer NOT NULL CHECK (chunk_count > 0),
    total_normalized_bytes bigint NOT NULL CHECK (total_normalized_bytes > 0),
    status text NOT NULL CHECK (status IN ('candidate', 'active', 'retired')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (customer_environment_id, generation_id),
    UNIQUE (customer_environment_id, namespace, generation_id)
);

CREATE TABLE IF NOT EXISTS erp_ai_knowledge.active_generations (
    customer_environment_id text NOT NULL,
    namespace text NOT NULL,
    generation_id uuid NOT NULL,
    generation_digest text NOT NULL CHECK (generation_digest ~ '^[0-9a-f]{64}$'),
    publication_contract_version integer NOT NULL CHECK (publication_contract_version = 1),
    PRIMARY KEY (customer_environment_id, namespace),
    FOREIGN KEY (customer_environment_id, namespace, generation_id)
        REFERENCES erp_ai_knowledge.generations(customer_environment_id, namespace, generation_id)
);

CREATE TABLE IF NOT EXISTS erp_ai_knowledge.documents (
    customer_environment_id text NOT NULL,
    generation_id uuid NOT NULL,
    document_id uuid NOT NULL,
    document_version varchar(64) NOT NULL CHECK (document_version ~ '^(0|[1-9][0-9]*)[.](0|[1-9][0-9]*)[.](0|[1-9][0-9]*)$'),
    namespace text NOT NULL,
    source_type text NOT NULL CHECK (source_type IN ('product_documentation', 'customer_policy')),
    document_customer_environment_id text,
    normalized_content_sha256 text NOT NULL CHECK (normalized_content_sha256 ~ '^[0-9a-f]{64}$'),
    governance_sha256 text NOT NULL CHECK (governance_sha256 ~ '^[0-9a-f]{64}$'),
    document_fingerprint text NOT NULL CHECK (document_fingerprint ~ '^[0-9a-f]{64}$'),
    source_provenance_sha256 text NOT NULL CHECK (source_provenance_sha256 ~ '^[0-9a-f]{64}$'),
    PRIMARY KEY (customer_environment_id, generation_id, document_id),
    FOREIGN KEY (customer_environment_id, generation_id)
        REFERENCES erp_ai_knowledge.generations(customer_environment_id, generation_id)
);

CREATE TABLE IF NOT EXISTS erp_ai_knowledge.chunks (
    customer_environment_id text NOT NULL,
    generation_id uuid NOT NULL,
    document_id uuid NOT NULL,
    chunk_id text NOT NULL,
    citation_id text NOT NULL,
    document_version varchar(64) NOT NULL CHECK (document_version ~ '^(0|[1-9][0-9]*)[.](0|[1-9][0-9]*)[.](0|[1-9][0-9]*)$'),
    chunk_ordinal integer NOT NULL CHECK (chunk_ordinal >= 0),
    namespace text NOT NULL,
    source_type text NOT NULL CHECK (source_type IN ('product_documentation', 'customer_policy')),
    document_customer_environment_id text,
    required_modules_all text[] NOT NULL,
    required_permissions_all text[] NOT NULL,
    allowed_purposes text[] NOT NULL CHECK (cardinality(allowed_purposes) > 0),
    legal_entity_ids text[] NOT NULL,
    data_classification text NOT NULL CHECK (data_classification IN ('public', 'internal', 'restricted', 'highly_restricted')),
    language text NOT NULL,
    title text NOT NULL CHECK (length(btrim(title)) > 0),
    section text NOT NULL CHECK (length(btrim(section)) > 0),
    effective_from timestamptz NOT NULL,
    effective_to timestamptz,
    content text NOT NULL CHECK (length(btrim(content)) > 0),
    content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    search_vector tsvector GENERATED ALWAYS AS
        (to_tsvector('simple', title || ' ' || section || ' ' || content)) STORED,
    PRIMARY KEY (customer_environment_id, generation_id, chunk_id),
    UNIQUE (customer_environment_id, generation_id, citation_id),
    UNIQUE (customer_environment_id, generation_id, document_id, chunk_ordinal),
    FOREIGN KEY (customer_environment_id, generation_id, document_id)
        REFERENCES erp_ai_knowledge.documents(customer_environment_id, generation_id, document_id),
    CHECK (effective_to IS NULL OR effective_to > effective_from)
);
CREATE INDEX IF NOT EXISTS chunks_search_vector_gin
    ON erp_ai_knowledge.chunks USING gin (search_vector);

CREATE TABLE IF NOT EXISTS erp_ai_knowledge.operations (
    customer_environment_id text NOT NULL,
    operation_id text NOT NULL,
    namespace text NOT NULL,
    operation_type text NOT NULL CHECK (operation_type IN ('publish', 'rollback')),
    operation_digest text NOT NULL CHECK (operation_digest ~ '^[0-9a-f]{64}$'),
    result jsonb NOT NULL,
    completed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (customer_environment_id, operation_id)
);

CREATE TABLE IF NOT EXISTS erp_ai_knowledge.publication_audit_outbox (
    customer_environment_id text NOT NULL,
    outbox_id uuid NOT NULL,
    operation_id text NOT NULL,
    request_id text NOT NULL,
    actor_id text NOT NULL,
    namespace text NOT NULL,
    action text NOT NULL CHECK (action IN ('knowledge.publish', 'knowledge.rollback')),
    previous_generation_id uuid,
    activated_generation_id uuid NOT NULL,
    generation_digest text NOT NULL CHECK (generation_digest ~ '^[0-9a-f]{64}$'),
    outcome text NOT NULL CHECK (outcome = 'succeeded'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (customer_environment_id, outbox_id),
    UNIQUE (customer_environment_id, operation_id)
);

CREATE OR REPLACE FUNCTION erp_ai_knowledge.reject_immutable_generation_content()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'generation content is immutable';
END;
$$;
DROP TRIGGER IF EXISTS documents_immutable ON erp_ai_knowledge.documents;
CREATE TRIGGER documents_immutable BEFORE UPDATE OR DELETE ON erp_ai_knowledge.documents
FOR EACH ROW EXECUTE FUNCTION erp_ai_knowledge.reject_immutable_generation_content();
DROP TRIGGER IF EXISTS chunks_immutable ON erp_ai_knowledge.chunks;
CREATE TRIGGER chunks_immutable BEFORE UPDATE OR DELETE ON erp_ai_knowledge.chunks
FOR EACH ROW EXECUTE FUNCTION erp_ai_knowledge.reject_immutable_generation_content();
