CREATE TABLE erp_ai_knowledge.embedding_profiles (
    customer_environment_id text NOT NULL,
    profile_sha256 text NOT NULL CHECK (profile_sha256 ~ '^[0-9a-f]{64}$'),
    profile_id text NOT NULL CHECK (profile_id ~ '^[a-z][a-z0-9_]{0,63}$'),
    contract_version integer NOT NULL CHECK (contract_version = 1),
    provider_id text NOT NULL,
    model_id text NOT NULL,
    model_revision text NOT NULL,
    dimensions integer NOT NULL CHECK (dimensions BETWEEN 1 AND 4096),
    distance_metric text NOT NULL CHECK (distance_metric = 'cosine'),
    storage_representation text NOT NULL CHECK (storage_representation = 'float32'),
    input_normalization_version integer NOT NULL CHECK (input_normalization_version > 0),
    allowed_data_classifications text[] NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (customer_environment_id, profile_sha256),
    UNIQUE (customer_environment_id, profile_id, profile_sha256)
);

CREATE TABLE erp_ai_knowledge.embedding_sets (
    customer_environment_id text NOT NULL,
    namespace text NOT NULL,
    generation_id uuid NOT NULL,
    generation_digest text NOT NULL CHECK (generation_digest ~ '^[0-9a-f]{64}$'),
    profile_sha256 text NOT NULL,
    embedding_set_sha256 text NOT NULL CHECK (embedding_set_sha256 ~ '^[0-9a-f]{64}$'),
    embedding_count integer NOT NULL CHECK (embedding_count > 0),
    status text NOT NULL CHECK (status IN ('building', 'ready')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    ready_at timestamptz,
    PRIMARY KEY (customer_environment_id, namespace, generation_id, profile_sha256),
    FOREIGN KEY (customer_environment_id, namespace, generation_id)
        REFERENCES erp_ai_knowledge.generations(customer_environment_id, namespace, generation_id),
    FOREIGN KEY (customer_environment_id, profile_sha256)
        REFERENCES erp_ai_knowledge.embedding_profiles(customer_environment_id, profile_sha256),
    CHECK ((status = 'building' AND ready_at IS NULL) OR
           (status = 'ready' AND ready_at IS NOT NULL))
);

CREATE TABLE erp_ai_knowledge.chunk_embeddings (
    customer_environment_id text NOT NULL,
    namespace text NOT NULL,
    generation_id uuid NOT NULL,
    profile_sha256 text NOT NULL,
    chunk_id text NOT NULL,
    content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    vector_sha256 text NOT NULL CHECK (vector_sha256 ~ '^[0-9a-f]{64}$'),
    embedding vector NOT NULL,
    PRIMARY KEY (customer_environment_id, namespace, generation_id, profile_sha256, chunk_id),
    FOREIGN KEY (customer_environment_id, namespace, generation_id, profile_sha256)
        REFERENCES erp_ai_knowledge.embedding_sets
        (customer_environment_id, namespace, generation_id, profile_sha256),
    FOREIGN KEY (customer_environment_id, generation_id, chunk_id)
        REFERENCES erp_ai_knowledge.chunks(customer_environment_id, generation_id, chunk_id)
);

CREATE TABLE erp_ai_knowledge.embedding_operations (
    customer_environment_id text NOT NULL,
    operation_id text NOT NULL,
    namespace text NOT NULL,
    generation_id uuid NOT NULL,
    profile_sha256 text NOT NULL,
    embedding_set_sha256 text NOT NULL CHECK (embedding_set_sha256 ~ '^[0-9a-f]{64}$'),
    result jsonb NOT NULL,
    completed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (customer_environment_id, operation_id)
);

CREATE TABLE erp_ai_knowledge.embedding_audit_outbox (
    customer_environment_id text NOT NULL,
    outbox_id uuid NOT NULL,
    operation_id text NOT NULL,
    request_id text NOT NULL,
    actor_id text NOT NULL,
    namespace text NOT NULL,
    generation_id uuid NOT NULL,
    generation_digest text NOT NULL CHECK (generation_digest ~ '^[0-9a-f]{64}$'),
    embedding_set_sha256 text NOT NULL CHECK (embedding_set_sha256 ~ '^[0-9a-f]{64}$'),
    embedding_count integer NOT NULL CHECK (embedding_count > 0),
    action text NOT NULL CHECK (action = 'knowledge.embeddings.materialize'),
    outcome text NOT NULL CHECK (outcome = 'succeeded'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (customer_environment_id, outbox_id),
    UNIQUE (customer_environment_id, operation_id)
);

CREATE OR REPLACE FUNCTION erp_ai_knowledge.validate_chunk_embedding()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE expected_dimensions integer;
DECLARE expected_content_hash text;
BEGIN
    SELECT dimensions INTO expected_dimensions
      FROM erp_ai_knowledge.embedding_profiles
     WHERE customer_environment_id = NEW.customer_environment_id
       AND profile_sha256 = NEW.profile_sha256;
    SELECT content_sha256 INTO expected_content_hash
      FROM erp_ai_knowledge.chunks
     WHERE customer_environment_id = NEW.customer_environment_id
       AND generation_id = NEW.generation_id AND chunk_id = NEW.chunk_id
       AND namespace = NEW.namespace;
    IF expected_dimensions IS NULL OR public.vector_dims(NEW.embedding) <> expected_dimensions OR
       expected_content_hash IS NULL OR expected_content_hash <> NEW.content_sha256 THEN
        RAISE EXCEPTION 'invalid chunk embedding';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER chunk_embeddings_validate BEFORE INSERT ON erp_ai_knowledge.chunk_embeddings
FOR EACH ROW EXECUTE FUNCTION erp_ai_knowledge.validate_chunk_embedding();

CREATE OR REPLACE FUNCTION erp_ai_knowledge.reject_embedding_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'embedding content is immutable';
END;
$$;
CREATE TRIGGER embedding_profiles_immutable BEFORE UPDATE OR DELETE
ON erp_ai_knowledge.embedding_profiles FOR EACH ROW
EXECUTE FUNCTION erp_ai_knowledge.reject_embedding_mutation();
CREATE TRIGGER chunk_embeddings_immutable BEFORE UPDATE OR DELETE
ON erp_ai_knowledge.chunk_embeddings FOR EACH ROW
EXECUTE FUNCTION erp_ai_knowledge.reject_embedding_mutation();
CREATE OR REPLACE FUNCTION erp_ai_knowledge.reject_ready_embedding_set_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND OLD.status = 'building' AND NEW.status = 'ready'
       AND NEW.ready_at IS NOT NULL
       AND (to_jsonb(OLD) - 'status' - 'ready_at') =
           (to_jsonb(NEW) - 'status' - 'ready_at') THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'embedding set is immutable';
END;
$$;
CREATE TRIGGER embedding_sets_ready_immutable BEFORE UPDATE OR DELETE
ON erp_ai_knowledge.embedding_sets FOR EACH ROW
EXECUTE FUNCTION erp_ai_knowledge.reject_ready_embedding_set_mutation();

ALTER TABLE erp_ai_knowledge.embedding_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE erp_ai_knowledge.embedding_profiles FORCE ROW LEVEL SECURITY;
ALTER TABLE erp_ai_knowledge.embedding_sets ENABLE ROW LEVEL SECURITY;
ALTER TABLE erp_ai_knowledge.embedding_sets FORCE ROW LEVEL SECURITY;
ALTER TABLE erp_ai_knowledge.chunk_embeddings ENABLE ROW LEVEL SECURITY;
ALTER TABLE erp_ai_knowledge.chunk_embeddings FORCE ROW LEVEL SECURITY;
ALTER TABLE erp_ai_knowledge.embedding_operations ENABLE ROW LEVEL SECURITY;
ALTER TABLE erp_ai_knowledge.embedding_operations FORCE ROW LEVEL SECURITY;
ALTER TABLE erp_ai_knowledge.embedding_audit_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE erp_ai_knowledge.embedding_audit_outbox FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_embedding_profiles ON erp_ai_knowledge.embedding_profiles
USING (customer_environment_id = erp_ai_knowledge.runtime_customer_id())
WITH CHECK (customer_environment_id = erp_ai_knowledge.runtime_customer_id());
CREATE POLICY tenant_embedding_sets ON erp_ai_knowledge.embedding_sets
USING (customer_environment_id = erp_ai_knowledge.runtime_customer_id())
WITH CHECK (customer_environment_id = erp_ai_knowledge.runtime_customer_id());
CREATE POLICY tenant_chunk_embeddings ON erp_ai_knowledge.chunk_embeddings
USING (customer_environment_id = erp_ai_knowledge.runtime_customer_id())
WITH CHECK (customer_environment_id = erp_ai_knowledge.runtime_customer_id());
CREATE POLICY tenant_embedding_operations ON erp_ai_knowledge.embedding_operations
USING (customer_environment_id = erp_ai_knowledge.runtime_customer_id())
WITH CHECK (customer_environment_id = erp_ai_knowledge.runtime_customer_id());
CREATE POLICY tenant_embedding_outbox ON erp_ai_knowledge.embedding_audit_outbox
USING (customer_environment_id = erp_ai_knowledge.runtime_customer_id())
WITH CHECK (customer_environment_id = erp_ai_knowledge.runtime_customer_id());

REVOKE ALL ON erp_ai_knowledge.embedding_profiles,
    erp_ai_knowledge.embedding_sets, erp_ai_knowledge.chunk_embeddings,
    erp_ai_knowledge.embedding_operations, erp_ai_knowledge.embedding_audit_outbox FROM PUBLIC;
REVOKE ALL ON FUNCTION erp_ai_knowledge.validate_chunk_embedding() FROM PUBLIC;
REVOKE ALL ON FUNCTION erp_ai_knowledge.reject_embedding_mutation() FROM PUBLIC;
REVOKE ALL ON FUNCTION erp_ai_knowledge.reject_ready_embedding_set_mutation() FROM PUBLIC;
