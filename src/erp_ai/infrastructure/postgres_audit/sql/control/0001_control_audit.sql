CREATE SCHEMA erp_ai_audit;
REVOKE ALL ON SCHEMA erp_ai_audit FROM PUBLIC;
CREATE TABLE erp_ai_audit.database_identity (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    database_kind varchar(16) NOT NULL CHECK (database_kind = 'control'),
    database_identity varchar(100) NOT NULL,
    customer_environment_id varchar(100) NULL CHECK (customer_environment_id IS NULL)
);
CREATE TABLE erp_ai_audit.contract_metadata (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    contract_version varchar(20) NOT NULL,
    contract_sha256 char(64) NOT NULL CHECK (contract_sha256 ~ '^[0-9a-f]{64}$')
);
CREATE TABLE erp_ai_audit.application_events (
    request_id varchar(100) PRIMARY KEY,
    stage varchar(32) NOT NULL,
    outcome varchar(16) NOT NULL,
    internal_reason varchar(200) NOT NULL,
    event_digest char(64) NOT NULL CHECK (event_digest ~ '^[0-9a-f]{64}$'),
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE FUNCTION erp_ai_audit.application_event_idempotency() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, erp_ai_audit AS $$
DECLARE existing erp_ai_audit.application_events%ROWTYPE;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended(NEW.request_id, 230023));
    SELECT * INTO existing FROM erp_ai_audit.application_events
    WHERE request_id = NEW.request_id;
    IF NOT FOUND THEN RETURN NEW; END IF;
    IF (existing.request_id, existing.stage, existing.outcome, existing.internal_reason,
        existing.event_digest) IS NOT DISTINCT FROM
       (NEW.request_id, NEW.stage, NEW.outcome, NEW.internal_reason, NEW.event_digest)
    THEN RETURN NULL; END IF;
    RAISE EXCEPTION USING ERRCODE = 'P2301', MESSAGE = 'audit logical slot conflict';
END $$;
CREATE TRIGGER application_events_idempotency BEFORE INSERT ON erp_ai_audit.application_events
FOR EACH ROW EXECUTE FUNCTION erp_ai_audit.application_event_idempotency();
CREATE FUNCTION erp_ai_audit.reject_event_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN RAISE EXCEPTION 'audit events are immutable'; END $$;
CREATE TRIGGER application_events_immutable BEFORE UPDATE OR DELETE ON erp_ai_audit.application_events
FOR EACH ROW EXECUTE FUNCTION erp_ai_audit.reject_event_mutation();
REVOKE ALL ON FUNCTION erp_ai_audit.application_event_idempotency() FROM PUBLIC;
REVOKE ALL ON FUNCTION erp_ai_audit.reject_event_mutation() FROM PUBLIC;
