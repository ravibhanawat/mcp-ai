-- ============================================================
-- SAP AI Agent — PostgreSQL Database Schema
-- Enterprise-grade tables matching all 6 SAP modules
-- Run: psql -U sap_agent -d sap_agent -f schema.sql
-- ============================================================

-- ── Trigger function for auto-updating updated_at ─────────────────────────────
CREATE OR REPLACE FUNCTION _set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ── Supporting lookups ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS plants (
    plant_id    VARCHAR(10)  PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    city        VARCHAR(80)  NOT NULL,
    country     VARCHAR(60)  NOT NULL,
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);

-- ── FI/CO ─────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS vendors (
    vendor_id       VARCHAR(10)  PRIMARY KEY,
    name            VARCHAR(120) NOT NULL,
    city            VARCHAR(80),
    country         VARCHAR(60),
    payment_terms   VARCHAR(20),
    bank_account    VARCHAR(30),
    bank_name       VARCHAR(100),
    tax_id          VARCHAR(30),
    currency        CHAR(3)       DEFAULT 'INR',
    status          VARCHAR(10)   DEFAULT 'ACTIVE',
    created_at      TIMESTAMPTZ   DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS gl_accounts (
    gl_account   VARCHAR(10)   PRIMARY KEY,
    name         VARCHAR(120)  NOT NULL,
    account_type VARCHAR(20)   NOT NULL,
    balance      DECIMAL(18,2) DEFAULT 0.00,
    currency     CHAR(3)       DEFAULT 'INR',
    created_at   TIMESTAMPTZ   DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cost_centers (
    cost_center_id  VARCHAR(10)   PRIMARY KEY,
    name            VARCHAR(120)  NOT NULL,
    department      VARCHAR(80),
    budget          DECIMAL(18,2) DEFAULT 0.00,
    actual          DECIMAL(18,2) DEFAULT 0.00,
    currency        CHAR(3)       DEFAULT 'INR',
    fiscal_year     SMALLINT      DEFAULT 2024,
    created_at      TIMESTAMPTZ   DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS invoices (
    invoice_id    VARCHAR(15)   PRIMARY KEY,
    vendor_id     VARCHAR(10)   NOT NULL,
    amount        DECIMAL(18,2) NOT NULL,
    currency      CHAR(3)       DEFAULT 'INR',
    status        VARCHAR(20)   DEFAULT 'OPEN',
    due_date      DATE,
    po_id         VARCHAR(15),
    posting_date  DATE,
    gl_account    VARCHAR(10),
    created_at    TIMESTAMPTZ   DEFAULT NOW(),
    FOREIGN KEY (vendor_id) REFERENCES vendors(vendor_id)
);

-- ── MM ─────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS materials (
    material_id   VARCHAR(15)   PRIMARY KEY,
    description   VARCHAR(200)  NOT NULL,
    material_type VARCHAR(20),
    unit          VARCHAR(10)   DEFAULT 'EA',
    price         DECIMAL(18,2) DEFAULT 0.00,
    currency      CHAR(3)       DEFAULT 'INR',
    weight_kg     DECIMAL(10,3),
    category      VARCHAR(80),
    hsn_code      VARCHAR(15),
    created_at    TIMESTAMPTZ   DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS stock (
    stock_id      INTEGER       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    material_id   VARCHAR(15)   NOT NULL,
    plant         VARCHAR(10)   NOT NULL,
    unrestricted  DECIMAL(14,3) DEFAULT 0.000,
    reserved      DECIMAL(14,3) DEFAULT 0.000,
    in_transit    DECIMAL(14,3) DEFAULT 0.000,
    reorder_point DECIMAL(14,3) DEFAULT 0.000,
    updated_at    TIMESTAMPTZ   DEFAULT NOW(),
    CONSTRAINT uq_mat_plant UNIQUE (material_id, plant),
    FOREIGN KEY (material_id) REFERENCES materials(material_id),
    FOREIGN KEY (plant)       REFERENCES plants(plant_id)
);

CREATE TRIGGER trg_stock_updated_at
    BEFORE UPDATE ON stock
    FOR EACH ROW EXECUTE FUNCTION _set_updated_at();

CREATE TABLE IF NOT EXISTS purchase_orders (
    po_id         VARCHAR(15)   PRIMARY KEY,
    vendor_id     VARCHAR(10)   NOT NULL,
    material_id   VARCHAR(15)   NOT NULL,
    qty           DECIMAL(14,3) NOT NULL,
    unit          VARCHAR(10)   DEFAULT 'EA',
    price         DECIMAL(18,2) NOT NULL,
    currency      CHAR(3)       DEFAULT 'INR',
    status        VARCHAR(20)   DEFAULT 'OPEN',
    delivery_date DATE,
    plant         VARCHAR(10),
    created_at    TIMESTAMPTZ   DEFAULT NOW(),
    FOREIGN KEY (vendor_id)   REFERENCES vendors(vendor_id),
    FOREIGN KEY (material_id) REFERENCES materials(material_id)
);

-- ── SD ─────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS customers (
    customer_id   VARCHAR(10)   PRIMARY KEY,
    name          VARCHAR(120)  NOT NULL,
    city          VARCHAR(80),
    country       VARCHAR(60)   DEFAULT 'India',
    credit_limit  DECIMAL(18,2) DEFAULT 0.00,
    payment_terms VARCHAR(20),
    email         VARCHAR(120),
    phone         VARCHAR(20),
    currency      CHAR(3)       DEFAULT 'INR',
    status        VARCHAR(10)   DEFAULT 'ACTIVE',
    gst_number    VARCHAR(20),
    created_at    TIMESTAMPTZ   DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sales_orders (
    order_id      VARCHAR(15)   PRIMARY KEY,
    customer_id   VARCHAR(10)   NOT NULL,
    material_id   VARCHAR(15)   NOT NULL,
    qty           DECIMAL(14,3) NOT NULL,
    price         DECIMAL(18,2) NOT NULL,
    currency      CHAR(3)       DEFAULT 'INR',
    status        VARCHAR(20)   DEFAULT 'OPEN',
    delivery_date DATE,
    plant         VARCHAR(10),
    created_at    TIMESTAMPTZ   DEFAULT NOW(),
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
    FOREIGN KEY (material_id) REFERENCES materials(material_id)
);

CREATE TABLE IF NOT EXISTS deliveries (
    delivery_id    VARCHAR(15)  PRIMARY KEY,
    sales_order_id VARCHAR(15)  NOT NULL,
    status         VARCHAR(20)  DEFAULT 'PENDING',
    ship_date      DATE,
    carrier        VARCHAR(80),
    tracking_no    VARCHAR(50),
    created_at     TIMESTAMPTZ  DEFAULT NOW(),
    FOREIGN KEY (sales_order_id) REFERENCES sales_orders(order_id)
);

-- ── HR ─────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS employees (
    emp_id      VARCHAR(10)  PRIMARY KEY,
    name        VARCHAR(120) NOT NULL,
    department  VARCHAR(80),
    position    VARCHAR(80),
    grade       VARCHAR(10),
    join_date   DATE,
    manager_id  VARCHAR(10),
    email       VARCHAR(120),
    phone       VARCHAR(20),
    status      VARCHAR(10)  DEFAULT 'ACTIVE',
    created_at  TIMESTAMPTZ  DEFAULT NOW(),
    FOREIGN KEY (manager_id) REFERENCES employees(emp_id)
);

CREATE TABLE IF NOT EXISTS leave_balances (
    lb_id           INTEGER      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    emp_id          VARCHAR(10)  NOT NULL,
    fiscal_year     SMALLINT     DEFAULT 2024,
    annual_entitled SMALLINT     DEFAULT 21,
    annual_used     DECIMAL(5,1) DEFAULT 0.0,
    sick_entitled   SMALLINT     DEFAULT 12,
    sick_used       DECIMAL(5,1) DEFAULT 0.0,
    casual_entitled SMALLINT     DEFAULT 8,
    casual_used     DECIMAL(5,1) DEFAULT 0.0,
    CONSTRAINT uq_emp_year UNIQUE (emp_id, fiscal_year),
    FOREIGN KEY (emp_id) REFERENCES employees(emp_id)
);

CREATE TABLE IF NOT EXISTS payroll (
    payroll_id  INTEGER       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    emp_id      VARCHAR(10)   NOT NULL,
    pay_month   SMALLINT      NOT NULL,
    pay_year    SMALLINT      NOT NULL,
    basic       DECIMAL(12,2) DEFAULT 0.00,
    hra         DECIMAL(12,2) DEFAULT 0.00,
    allowances  DECIMAL(12,2) DEFAULT 0.00,
    deductions  DECIMAL(12,2) DEFAULT 0.00,
    net         DECIMAL(12,2) DEFAULT 0.00,
    currency    CHAR(3)       DEFAULT 'INR',
    processed_on DATE,
    CONSTRAINT uq_emp_month UNIQUE (emp_id, pay_month, pay_year),
    FOREIGN KEY (emp_id) REFERENCES employees(emp_id)
);

-- ── PP ─────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS work_centers (
    wc_id         VARCHAR(10)   PRIMARY KEY,
    name          VARCHAR(120)  NOT NULL,
    plant         VARCHAR(10),
    capacity      DECIMAL(10,2) DEFAULT 0.00,
    capacity_unit VARCHAR(10)   DEFAULT 'HR',
    status        VARCHAR(15)   DEFAULT 'ACTIVE',
    FOREIGN KEY (plant) REFERENCES plants(plant_id)
);

CREATE TABLE IF NOT EXISTS production_orders (
    order_id       VARCHAR(15)   PRIMARY KEY,
    material_id    VARCHAR(15)   NOT NULL,
    qty            DECIMAL(14,3) NOT NULL,
    unit           VARCHAR(10)   DEFAULT 'EA',
    plant          VARCHAR(10),
    work_center_id VARCHAR(10),
    status         VARCHAR(30)   DEFAULT 'CREATED',
    planned_start  DATE,
    planned_end    DATE,
    created_at     TIMESTAMPTZ   DEFAULT NOW(),
    FOREIGN KEY (material_id)    REFERENCES materials(material_id),
    FOREIGN KEY (work_center_id) REFERENCES work_centers(wc_id)
);

CREATE TABLE IF NOT EXISTS bom (
    bom_id             INTEGER       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    parent_material_id VARCHAR(15)   NOT NULL,
    component_id       VARCHAR(15)   NOT NULL,
    qty                DECIMAL(14,3) NOT NULL,
    unit               VARCHAR(10)   DEFAULT 'EA',
    FOREIGN KEY (parent_material_id) REFERENCES materials(material_id),
    FOREIGN KEY (component_id)       REFERENCES materials(material_id)
);

-- ── ABAP ───────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS abap_programs (
    program_name VARCHAR(40)  PRIMARY KEY,
    description  VARCHAR(200),
    program_type VARCHAR(20)  DEFAULT 'REPORT',
    package      VARCHAR(30),
    created_by   VARCHAR(20),
    created_on   DATE,
    line_count   INTEGER      DEFAULT 0,
    status       VARCHAR(10)  DEFAULT 'ACTIVE',
    last_changed DATE
);

CREATE TABLE IF NOT EXISTS function_modules (
    fm_name        VARCHAR(60)  PRIMARY KEY,
    description    VARCHAR(200),
    function_group VARCHAR(30),
    package        VARCHAR(30),
    parameters     TEXT,
    created_by     VARCHAR(20),
    status         VARCHAR(10)  DEFAULT 'ACTIVE'
);

CREATE TABLE IF NOT EXISTS transport_requests (
    tr_id       VARCHAR(15)  PRIMARY KEY,
    description VARCHAR(200),
    tr_type     VARCHAR(30),
    status      VARCHAR(20)  DEFAULT 'MODIFIABLE',
    owner       VARCHAR(20),
    created_on  DATE,
    released_on DATE,
    target      VARCHAR(20),
    objects     TEXT
);

-- ── Activity / Audit Logs ──────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS request_logs (
    id               BIGINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    timestamp        TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    request_id       VARCHAR(36)   NOT NULL,
    user_id          VARCHAR(50),
    user_roles       JSONB,
    client_ip        VARCHAR(50),
    method           VARCHAR(10),
    endpoint         VARCHAR(255)  NOT NULL,
    status_code      SMALLINT,
    status           VARCHAR(10)   DEFAULT 'ok',
    query_text       TEXT,
    tool_called      VARCHAR(100),
    tool_parameters  JSONB,
    sap_source       JSONB,
    response_summary VARCHAR(500),
    duration_ms      INTEGER,
    error_message    TEXT,
    log_source       VARCHAR(20)   DEFAULT 'middleware'
);

-- ── Chat History ───────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS conversations (
    id         INTEGER     GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id    VARCHAR(50) NOT NULL,
    session_id VARCHAR(100) NOT NULL,
    title      VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_user_session UNIQUE (user_id, session_id)
);

CREATE TRIGGER trg_conv_updated_at
    BEFORE UPDATE ON conversations
    FOR EACH ROW EXECUTE FUNCTION _set_updated_at();

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER     GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    conversation_id INTEGER     NOT NULL,
    role            VARCHAR(10) NOT NULL CHECK (role IN ('user', 'bot')),
    content         TEXT        NOT NULL,
    tool_called     VARCHAR(100),
    tool_result     JSONB,
    sap_source      JSONB,
    abap_check      JSONB,
    abap_code       JSONB,
    report          JSONB,
    status_steps    JSONB       DEFAULT '[]'::jsonb,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

-- Migration: add status_steps to existing installations
ALTER TABLE messages ADD COLUMN IF NOT EXISTS status_steps JSONB DEFAULT '[]'::jsonb;

-- ── Indexes ─────────────────────────────────────────────────────────────────────

-- Standard indexes
CREATE INDEX IF NOT EXISTS idx_rl_ts        ON request_logs(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_rl_user      ON request_logs(user_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_rl_endpoint  ON request_logs(endpoint, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_rl_status    ON request_logs(status, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_rl_request   ON request_logs(request_id);
CREATE INDEX IF NOT EXISTS idx_conv_user    ON conversations(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_msg_conv     ON messages(conversation_id, created_at ASC);

-- JSONB GIN indexes for fast audit log queries
CREATE INDEX IF NOT EXISTS idx_rl_roles_gin  ON request_logs USING GIN (user_roles);
CREATE INDEX IF NOT EXISTS idx_rl_params_gin ON request_logs USING GIN (tool_parameters);

-- Partial indexes (PostgreSQL advantage — index only the rows that matter most)
CREATE INDEX IF NOT EXISTS idx_invoices_open
    ON invoices(vendor_id, due_date)
    WHERE status = 'OPEN';

CREATE INDEX IF NOT EXISTS idx_po_open
    ON purchase_orders(vendor_id, delivery_date)
    WHERE status IN ('OPEN', 'PARTIAL');

CREATE INDEX IF NOT EXISTS idx_so_open
    ON sales_orders(customer_id, delivery_date)
    WHERE status = 'OPEN';

CREATE INDEX IF NOT EXISTS idx_employees_active
    ON employees(department, name)
    WHERE status = 'ACTIVE';

CREATE INDEX IF NOT EXISTS idx_stock_reorder
    ON stock(material_id, plant)
    WHERE (unrestricted - reserved) < reorder_point;
