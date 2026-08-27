CREATE SCHEMA erp_ai_audit;
REVOKE ALL ON SCHEMA erp_ai_audit FROM PUBLIC;
CREATE TABLE erp_ai_audit.database_identity (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    database_kind varchar(16) NOT NULL CHECK (database_kind = 'customer'),
    database_identity varchar(100) NOT NULL,
    customer_environment_id varchar(100) NOT NULL
);
CREATE TABLE erp_ai_audit.contract_metadata (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    contract_version varchar(20) NOT NULL,
    contract_sha256 char(64) NOT NULL CHECK (contract_sha256 ~ '^[0-9a-f]{64}$')
);
CREATE TABLE erp_ai_audit.agent_events (
    request_id varchar(100) PRIMARY KEY,
    customer_environment_id varchar(100) NOT NULL,
    user_id varchar(100) NOT NULL,
    purpose varchar(100) NOT NULL,
    action varchar(100) NOT NULL,
    outcome varchar(16) NOT NULL,
    internal_reason varchar(200) NOT NULL,
    event_digest char(64) NOT NULL CHECK (event_digest ~ '^[0-9a-f]{64}$'),
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE erp_ai_audit.tool_events (
    request_id varchar(100) NOT NULL,
    customer_environment_id varchar(100) NOT NULL,
    user_id varchar(100) NOT NULL,
    tool_name varchar(100) NOT NULL,
    tool_version varchar(32) NOT NULL,
    audit_action varchar(100) NOT NULL,
    data_classification varchar(32) NOT NULL,
    outcome varchar(16) NOT NULL,
    internal_reason varchar(200) NOT NULL,
    purpose varchar(100) NOT NULL,
    event_digest char(64) NOT NULL CHECK (event_digest ~ '^[0-9a-f]{64}$'),
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (request_id, tool_name, tool_version, audit_action)
);
ALTER TABLE erp_ai_audit.agent_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE erp_ai_audit.agent_events FORCE ROW LEVEL SECURITY;
ALTER TABLE erp_ai_audit.tool_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE erp_ai_audit.tool_events FORCE ROW LEVEL SECURITY;
CREATE POLICY agent_customer_insert ON erp_ai_audit.agent_events FOR INSERT
WITH CHECK (
    customer_environment_id = nullif(current_setting('erp_ai_audit.customer_environment_id', true), '')
    AND customer_environment_id = (
        SELECT identity.customer_environment_id FROM erp_ai_audit.database_identity identity
        WHERE identity.singleton AND identity.database_kind = 'customer'
    )
);
CREATE POLICY agent_customer_digest ON erp_ai_audit.agent_events FOR SELECT
USING (
    customer_environment_id = nullif(current_setting('erp_ai_audit.customer_environment_id', true), '')
    AND customer_environment_id = (
        SELECT identity.customer_environment_id FROM erp_ai_audit.database_identity identity
        WHERE identity.singleton AND identity.database_kind = 'customer'
    )
);
CREATE POLICY tool_customer_insert ON erp_ai_audit.tool_events FOR INSERT
WITH CHECK (
    customer_environment_id = nullif(current_setting('erp_ai_audit.customer_environment_id', true), '')
    AND customer_environment_id = (
        SELECT identity.customer_environment_id FROM erp_ai_audit.database_identity identity
        WHERE identity.singleton AND identity.database_kind = 'customer'
    )
);
CREATE POLICY tool_customer_digest ON erp_ai_audit.tool_events FOR SELECT
USING (
    customer_environment_id = nullif(current_setting('erp_ai_audit.customer_environment_id', true), '')
    AND customer_environment_id = (
        SELECT identity.customer_environment_id FROM erp_ai_audit.database_identity identity
        WHERE identity.singleton AND identity.database_kind = 'customer'
    )
);
CREATE FUNCTION erp_ai_audit.agent_event_idempotency() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, erp_ai_audit AS $$
DECLARE existing erp_ai_audit.agent_events%ROWTYPE;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended(NEW.request_id, 230123));
    SELECT * INTO existing FROM erp_ai_audit.agent_events
    WHERE request_id = NEW.request_id;
    IF NOT FOUND THEN RETURN NEW; END IF;
    IF (existing.request_id, existing.customer_environment_id, existing.user_id,
        existing.purpose, existing.action, existing.outcome, existing.internal_reason,
        existing.event_digest) IS NOT DISTINCT FROM
       (NEW.request_id, NEW.customer_environment_id, NEW.user_id, NEW.purpose,
        NEW.action, NEW.outcome, NEW.internal_reason, NEW.event_digest)
    THEN RETURN NULL; END IF;
    RAISE EXCEPTION USING ERRCODE = 'P2301', MESSAGE = 'audit logical slot conflict';
END $$;
CREATE TRIGGER agent_events_idempotency BEFORE INSERT ON erp_ai_audit.agent_events
FOR EACH ROW EXECUTE FUNCTION erp_ai_audit.agent_event_idempotency();
CREATE FUNCTION erp_ai_audit.tool_event_idempotency() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, erp_ai_audit AS $$
DECLARE existing erp_ai_audit.tool_events%ROWTYPE;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended(
        NEW.request_id || chr(31) || NEW.tool_name || chr(31) || NEW.tool_version || chr(31) || NEW.audit_action,
        230223));
    SELECT * INTO existing FROM erp_ai_audit.tool_events
    WHERE request_id = NEW.request_id AND tool_name = NEW.tool_name
    AND tool_version = NEW.tool_version AND audit_action = NEW.audit_action;
    IF NOT FOUND THEN RETURN NEW; END IF;
    IF (existing.request_id, existing.customer_environment_id, existing.user_id,
        existing.tool_name, existing.tool_version, existing.audit_action,
        existing.data_classification, existing.outcome, existing.internal_reason,
        existing.purpose, existing.event_digest) IS NOT DISTINCT FROM
       (NEW.request_id, NEW.customer_environment_id, NEW.user_id, NEW.tool_name,
        NEW.tool_version, NEW.audit_action, NEW.data_classification, NEW.outcome,
        NEW.internal_reason, NEW.purpose, NEW.event_digest)
    THEN RETURN NULL; END IF;
    RAISE EXCEPTION USING ERRCODE = 'P2301', MESSAGE = 'audit logical slot conflict';
END $$;
CREATE TRIGGER tool_events_idempotency BEFORE INSERT ON erp_ai_audit.tool_events
FOR EACH ROW EXECUTE FUNCTION erp_ai_audit.tool_event_idempotency();
CREATE FUNCTION erp_ai_audit.reject_event_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN RAISE EXCEPTION 'audit events are immutable'; END $$;
CREATE TRIGGER agent_events_immutable BEFORE UPDATE OR DELETE ON erp_ai_audit.agent_events
FOR EACH ROW EXECUTE FUNCTION erp_ai_audit.reject_event_mutation();
CREATE TRIGGER tool_events_immutable BEFORE UPDATE OR DELETE ON erp_ai_audit.tool_events
FOR EACH ROW EXECUTE FUNCTION erp_ai_audit.reject_event_mutation();
REVOKE ALL ON FUNCTION erp_ai_audit.agent_event_idempotency() FROM PUBLIC;
REVOKE ALL ON FUNCTION erp_ai_audit.tool_event_idempotency() FROM PUBLIC;
REVOKE ALL ON FUNCTION erp_ai_audit.reject_event_mutation() FROM PUBLIC;
