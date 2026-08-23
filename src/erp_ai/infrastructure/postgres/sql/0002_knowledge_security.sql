ALTER TABLE erp_ai_knowledge.database_identity ENABLE ROW LEVEL SECURITY;
ALTER TABLE erp_ai_knowledge.generations ENABLE ROW LEVEL SECURITY;
ALTER TABLE erp_ai_knowledge.generations FORCE ROW LEVEL SECURITY;
ALTER TABLE erp_ai_knowledge.active_generations ENABLE ROW LEVEL SECURITY;
ALTER TABLE erp_ai_knowledge.active_generations FORCE ROW LEVEL SECURITY;
ALTER TABLE erp_ai_knowledge.documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE erp_ai_knowledge.documents FORCE ROW LEVEL SECURITY;
ALTER TABLE erp_ai_knowledge.chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE erp_ai_knowledge.chunks FORCE ROW LEVEL SECURITY;
ALTER TABLE erp_ai_knowledge.operations ENABLE ROW LEVEL SECURITY;
ALTER TABLE erp_ai_knowledge.operations FORCE ROW LEVEL SECURITY;
ALTER TABLE erp_ai_knowledge.publication_audit_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE erp_ai_knowledge.publication_audit_outbox FORCE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION erp_ai_knowledge.runtime_customer_id()
RETURNS text LANGUAGE sql STABLE AS $$
    SELECT nullif(current_setting('erp_ai.customer_environment_id', true), '')
$$;

DROP POLICY IF EXISTS tenant_identity ON erp_ai_knowledge.database_identity;
CREATE POLICY tenant_identity ON erp_ai_knowledge.database_identity
USING (customer_environment_id = erp_ai_knowledge.runtime_customer_id());
DROP POLICY IF EXISTS tenant_generations ON erp_ai_knowledge.generations;
CREATE POLICY tenant_generations ON erp_ai_knowledge.generations
USING (customer_environment_id = erp_ai_knowledge.runtime_customer_id())
WITH CHECK (customer_environment_id = erp_ai_knowledge.runtime_customer_id());
DROP POLICY IF EXISTS tenant_active_generations ON erp_ai_knowledge.active_generations;
CREATE POLICY tenant_active_generations ON erp_ai_knowledge.active_generations
USING (customer_environment_id = erp_ai_knowledge.runtime_customer_id())
WITH CHECK (customer_environment_id = erp_ai_knowledge.runtime_customer_id());
DROP POLICY IF EXISTS tenant_documents ON erp_ai_knowledge.documents;
CREATE POLICY tenant_documents ON erp_ai_knowledge.documents
USING (customer_environment_id = erp_ai_knowledge.runtime_customer_id())
WITH CHECK (customer_environment_id = erp_ai_knowledge.runtime_customer_id());
DROP POLICY IF EXISTS tenant_chunks ON erp_ai_knowledge.chunks;
CREATE POLICY tenant_chunks ON erp_ai_knowledge.chunks
USING (customer_environment_id = erp_ai_knowledge.runtime_customer_id())
WITH CHECK (customer_environment_id = erp_ai_knowledge.runtime_customer_id());
DROP POLICY IF EXISTS tenant_operations ON erp_ai_knowledge.operations;
CREATE POLICY tenant_operations ON erp_ai_knowledge.operations
USING (customer_environment_id = erp_ai_knowledge.runtime_customer_id())
WITH CHECK (customer_environment_id = erp_ai_knowledge.runtime_customer_id());
DROP POLICY IF EXISTS tenant_outbox ON erp_ai_knowledge.publication_audit_outbox;
CREATE POLICY tenant_outbox ON erp_ai_knowledge.publication_audit_outbox
USING (customer_environment_id = erp_ai_knowledge.runtime_customer_id())
WITH CHECK (customer_environment_id = erp_ai_knowledge.runtime_customer_id());

REVOKE ALL ON SCHEMA erp_ai_knowledge FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA erp_ai_knowledge FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA erp_ai_knowledge FROM PUBLIC;
