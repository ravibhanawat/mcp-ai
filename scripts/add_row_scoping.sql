-- Row-scoping migration — OPT-IN.
--
-- Adds the columns core/scoping.py needs to restrict rows to their owner and,
-- for single-database multi-company deployments, to a tenant.
--
-- Run only when you have decided the ownership rule for your business. The
-- columns are nullable so this is safe to apply before backfilling, but note
-- that with RECORD_SCOPING=owner a NULL owner_id means the row matches nobody
-- except roles in UNSCOPED_ROLES. Backfill before enabling.
--
--   psql -U sap_agent -d sap_agent -f scripts/add_row_scoping.sql

BEGIN;

ALTER TABLE customers    ADD COLUMN IF NOT EXISTS owner_id  VARCHAR(64);
ALTER TABLE sales_orders ADD COLUMN IF NOT EXISTS owner_id  VARCHAR(64);
ALTER TABLE vendors      ADD COLUMN IF NOT EXISTS owner_id  VARCHAR(64);
ALTER TABLE invoices     ADD COLUMN IF NOT EXISTS owner_id  VARCHAR(64);
ALTER TABLE deliveries   ADD COLUMN IF NOT EXISTS owner_id  VARCHAR(64);

CREATE INDEX IF NOT EXISTS idx_customers_owner    ON customers(owner_id);
CREATE INDEX IF NOT EXISTS idx_sales_orders_owner ON sales_orders(owner_id);
CREATE INDEX IF NOT EXISTS idx_vendors_owner      ON vendors(owner_id);
CREATE INDEX IF NOT EXISTS idx_invoices_owner     ON invoices(owner_id);
CREATE INDEX IF NOT EXISTS idx_deliveries_owner   ON deliveries(owner_id);

-- Only for TENANCY_MODEL=column. Database-per-company (the default, and the
-- model SAP Business One uses) needs none of this.
ALTER TABLE customers    ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(64);
ALTER TABLE sales_orders ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(64);
ALTER TABLE vendors      ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(64);
ALTER TABLE invoices     ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(64);
ALTER TABLE deliveries   ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(64);

CREATE INDEX IF NOT EXISTS idx_customers_tenant    ON customers(tenant_id);
CREATE INDEX IF NOT EXISTS idx_sales_orders_tenant ON sales_orders(tenant_id);
CREATE INDEX IF NOT EXISTS idx_vendors_tenant      ON vendors(tenant_id);
CREATE INDEX IF NOT EXISTS idx_invoices_tenant     ON invoices(tenant_id);
CREATE INDEX IF NOT EXISTS idx_deliveries_tenant   ON deliveries(tenant_id);

COMMIT;
