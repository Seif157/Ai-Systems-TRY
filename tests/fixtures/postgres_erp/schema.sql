CREATE SCHEMA erp;
CREATE SCHEMA ai_read;

CREATE TABLE erp.legal_entities (
    legal_entity_id uuid PRIMARY KEY,
    legal_name varchar(250) NOT NULL
);
CREATE TABLE erp.organization_branches (
    branch_id uuid PRIMARY KEY,
    legal_entity_id uuid NOT NULL REFERENCES erp.legal_entities,
    branch_name varchar(200) NOT NULL,
    UNIQUE (branch_id, legal_entity_id)
);
CREATE TABLE erp.branch_departments (
    dept_id uuid PRIMARY KEY,
    branch_id uuid NOT NULL,
    legal_entity_id uuid NOT NULL,
    dept_name varchar(200) NOT NULL,
    FOREIGN KEY (branch_id,legal_entity_id)
        REFERENCES erp.organization_branches(branch_id,legal_entity_id),
    UNIQUE (dept_id,legal_entity_id)
);
CREATE TABLE erp.positions (
    position_id uuid PRIMARY KEY,
    legal_entity_id uuid NOT NULL REFERENCES erp.legal_entities,
    position_title varchar(200) NOT NULL,
    UNIQUE (position_id,legal_entity_id)
);
CREATE TABLE erp.employees (
    employee_id uuid PRIMARY KEY,
    legal_entity_id uuid NOT NULL REFERENCES erp.legal_entities,
    employee_number varchar(20) NOT NULL,
    display_name varchar(200) NOT NULL,
    email_work varchar(200) NOT NULL,
    position_id uuid,
    dept_id uuid,
    branch_id uuid,
    manager_id uuid,
    employment_status varchar(20) NOT NULL,
    hire_date date NOT NULL,
    profile_freshness_at timestamptz NOT NULL,
    updated_at timestamptz,
    UNIQUE (employee_id,legal_entity_id),
    FOREIGN KEY (position_id,legal_entity_id) REFERENCES erp.positions(position_id,legal_entity_id),
    FOREIGN KEY (dept_id,legal_entity_id) REFERENCES erp.branch_departments(dept_id,legal_entity_id),
    FOREIGN KEY (branch_id,legal_entity_id)
        REFERENCES erp.organization_branches(branch_id,legal_entity_id),
    FOREIGN KEY (manager_id) REFERENCES erp.employees(employee_id)
);
CREATE TABLE erp.leave_types (
    leave_type_id uuid PRIMARY KEY,
    legal_entity_id uuid NOT NULL REFERENCES erp.legal_entities,
    leave_code varchar(20) NOT NULL,
    leave_name varchar(100) NOT NULL,
    leave_name_local varchar(100) NOT NULL,
    UNIQUE (leave_type_id,legal_entity_id)
);
CREATE TABLE erp.leave_balances (
    balance_id uuid PRIMARY KEY,
    employee_id uuid NOT NULL,
    legal_entity_id uuid NOT NULL,
    leave_type_id uuid NOT NULL,
    fiscal_year smallint NOT NULL,
    opening_balance numeric(7,2) NOT NULL,
    accrued_ytd numeric(7,2) NOT NULL,
    used_ytd numeric(7,2) NOT NULL,
    pending_ytd numeric(7,2) NOT NULL,
    available_days numeric(7,2) NOT NULL,
    calculated_at timestamptz NOT NULL,
    source_watermark varchar(128) NOT NULL CHECK (source_watermark=btrim(source_watermark)
        AND length(source_watermark) BETWEEN 1 AND 128),
    calculation_version varchar(64) NOT NULL CHECK
        (calculation_version ~ '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$'),
    UNIQUE(employee_id,leave_type_id,fiscal_year),
    FOREIGN KEY (employee_id,legal_entity_id) REFERENCES erp.employees(employee_id,legal_entity_id),
    FOREIGN KEY (leave_type_id,legal_entity_id)
        REFERENCES erp.leave_types(leave_type_id,legal_entity_id)
);
CREATE TABLE erp.leave_requests (
    request_id uuid PRIMARY KEY,
    employee_id uuid NOT NULL,
    legal_entity_id uuid NOT NULL,
    leave_type_id uuid NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    working_days numeric(5,2) NOT NULL,
    is_half_day boolean NOT NULL,
    half_day_period varchar(15),
    status varchar(20) NOT NULL,
    submitted_at timestamptz NOT NULL,
    updated_at timestamptz,
    working_days_calculation_version varchar(64) NOT NULL CHECK
        (working_days_calculation_version ~
         '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$'),
    FOREIGN KEY (employee_id,legal_entity_id) REFERENCES erp.employees(employee_id,legal_entity_id),
    FOREIGN KEY (leave_type_id,legal_entity_id)
        REFERENCES erp.leave_types(leave_type_id,legal_entity_id)
);
CREATE TABLE erp.workflow_status_history (
    history_id uuid PRIMARY KEY,
    entity_type varchar(80) NOT NULL,
    entity_id uuid NOT NULL REFERENCES erp.leave_requests(request_id),
    from_status varchar(40),
    to_status varchar(40) NOT NULL,
    changed_at timestamptz NOT NULL,
    reason_code varchar(50)
);

GRANT USAGE ON SCHEMA erp TO erp_ai_test_view_owner;
GRANT SELECT ON ALL TABLES IN SCHEMA erp TO erp_ai_test_view_owner;

CREATE VIEW ai_read.hr_employee_profile_v1 WITH (security_barrier=true) AS
SELECT employee.employee_id,employee.legal_entity_id,employee.employee_number,
employee.display_name,employee.email_work AS work_email,position.position_title AS job_title,
department.dept_name AS department_name,branch.branch_name,entity.legal_name AS legal_entity_name,
employee.employment_status,employee.hire_date,manager.display_name AS manager_display_name,
employee.profile_freshness_at AS freshness_at
FROM erp.employees employee
JOIN erp.legal_entities entity USING (legal_entity_id)
LEFT JOIN erp.positions position ON position.position_id=employee.position_id
    AND position.legal_entity_id=employee.legal_entity_id
LEFT JOIN erp.branch_departments department ON department.dept_id=employee.dept_id
    AND department.legal_entity_id=employee.legal_entity_id
LEFT JOIN erp.organization_branches branch ON branch.branch_id=employee.branch_id
    AND branch.legal_entity_id=employee.legal_entity_id
LEFT JOIN erp.employees manager ON manager.employee_id=employee.manager_id
    AND manager.legal_entity_id=employee.legal_entity_id;

CREATE VIEW ai_read.leave_balances_v1 WITH (security_barrier=true) AS
SELECT balance.employee_id,balance.legal_entity_id,balance.leave_type_id,
leave_type.leave_code AS leave_type_code,leave_type.leave_name AS leave_type_name,
leave_type.leave_name_local AS leave_type_name_local,balance.fiscal_year,
balance.opening_balance AS opening_days,balance.accrued_ytd AS accrued_days,
balance.used_ytd AS used_days,balance.pending_ytd AS pending_days,balance.available_days,
balance.calculated_at,balance.source_watermark,balance.calculation_version
FROM erp.leave_balances balance JOIN erp.leave_types leave_type
ON leave_type.leave_type_id=balance.leave_type_id
AND leave_type.legal_entity_id=balance.legal_entity_id;

CREATE VIEW ai_read.leave_requests_v1 WITH (security_barrier=true) AS
SELECT request.request_id,request.employee_id,request.legal_entity_id,request.leave_type_id,
leave_type.leave_code AS leave_type_code,leave_type.leave_name AS leave_type_name,
leave_type.leave_name_local AS leave_type_name_local,request.start_date,request.end_date,
request.working_days,request.is_half_day,request.half_day_period,request.status,
request.submitted_at,request.updated_at,request.working_days_calculation_version
FROM erp.leave_requests request JOIN erp.leave_types leave_type
ON leave_type.leave_type_id=request.leave_type_id
AND leave_type.legal_entity_id=request.legal_entity_id
WHERE request.status <> 'draft';

CREATE VIEW ai_read.leave_request_history_v1 WITH (security_barrier=true) AS
SELECT history.history_id,request.request_id,request.employee_id,request.legal_entity_id,
history.entity_type,history.from_status,history.to_status,history.changed_at,history.reason_code
FROM erp.workflow_status_history history JOIN erp.leave_requests request
ON request.request_id=history.entity_id WHERE history.entity_type='leave_request';

CREATE VIEW ai_read.contract_metadata_v1 WITH (security_barrier=true) AS
SELECT '1.0.0'::varchar(64) AS contract_version,
'077528e247774f3584de47187b97975535d938f562cdf6ad59c61ce9a506aec5'::char(64)
AS contract_sha256;

ALTER VIEW ai_read.hr_employee_profile_v1 OWNER TO erp_ai_test_view_owner;
ALTER VIEW ai_read.leave_balances_v1 OWNER TO erp_ai_test_view_owner;
ALTER VIEW ai_read.leave_requests_v1 OWNER TO erp_ai_test_view_owner;
ALTER VIEW ai_read.leave_request_history_v1 OWNER TO erp_ai_test_view_owner;
ALTER VIEW ai_read.contract_metadata_v1 OWNER TO erp_ai_test_view_owner;
REVOKE ALL ON SCHEMA ai_read FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA ai_read FROM PUBLIC;
GRANT USAGE ON SCHEMA ai_read TO __READER_ROLE__;
GRANT SELECT ON ALL TABLES IN SCHEMA ai_read TO __READER_ROLE__;
