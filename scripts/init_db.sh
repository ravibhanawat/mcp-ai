#!/usr/bin/env bash
# ============================================================
# SAP AI Agent — PostgreSQL Database Initialisation
# Usage: bash scripts/init_db.sh [options]
#
# Options:
#   --host HOST       PG host (default: localhost)
#   --port PORT       PG port (default: 5432)
#   --user USER       DB user to create (default: sap_agent)
#   --pass PASS       DB password      (default: sap_agent)
#   --db   DB         Database name    (default: sap_agent)
#   --superuser SU    Superuser for initial setup (default: postgres)
#   --no-seed         Skip seed data
#   --drop            Drop & recreate the database (DESTRUCTIVE)
# ============================================================
set -euo pipefail

# ── Defaults ─────────────────────────────────────────────────
PG_HOST="${DB_HOST:-localhost}"
PG_PORT="${DB_PORT:-5432}"
DB_USER="${DB_USER:-sap_agent}"
DB_PASS="${DB_PASSWORD:-sap_agent}"
DB_NAME="${DB_NAME:-sap_agent}"
SUPERUSER="${PG_SUPERUSER:-postgres}"
SKIP_SEED=false
DROP_DB=false

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SCHEMA_FILE="$PROJECT_DIR/db/schema.sql"
SEED_FILE="$PROJECT_DIR/db/seed.sql"

# ── Colours ───────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ── Argument parsing ──────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case $1 in
    --host)      PG_HOST="$2";    shift 2 ;;
    --port)      PG_PORT="$2";    shift 2 ;;
    --user)      DB_USER="$2";    shift 2 ;;
    --pass)      DB_PASS="$2";    shift 2 ;;
    --db)        DB_NAME="$2";    shift 2 ;;
    --superuser) SUPERUSER="$2";  shift 2 ;;
    --no-seed)   SKIP_SEED=true;  shift   ;;
    --drop)      DROP_DB=true;    shift   ;;
    *) warn "Unknown option: $1"; shift   ;;
  esac
done

# ── Pre-flight checks ─────────────────────────────────────────
echo ""
echo -e "${BOLD}═══════════════════════════════════════════════${NC}"
echo -e "${BOLD}   SAP AI Agent — PostgreSQL Init Script${NC}"
echo -e "${BOLD}═══════════════════════════════════════════════${NC}"
echo ""

command -v psql >/dev/null 2>&1 || error "psql not found. Install PostgreSQL client: brew install postgresql"

[[ -f "$SCHEMA_FILE" ]] || error "Schema file not found: $SCHEMA_FILE"
[[ -f "$SEED_FILE"   ]] || error "Seed file not found: $SEED_FILE"

info "Target database : ${BOLD}$DB_NAME${NC} on $PG_HOST:$PG_PORT"
info "DB user         : ${BOLD}$DB_USER${NC}"
info "Superuser       : $SUPERUSER"
info "Schema file     : $SCHEMA_FILE"
info "Seed data       : $([ "$SKIP_SEED" = true ] && echo 'SKIPPED' || echo "$SEED_FILE")"
echo ""

# ── Helper: run psql as superuser ─────────────────────────────
su_psql() {
  PGPASSWORD="" psql -h "$PG_HOST" -p "$PG_PORT" -U "$SUPERUSER" "$@"
}

# ── Helper: run psql as sap_agent user ───────────────────────
app_psql() {
  PGPASSWORD="$DB_PASS" psql -h "$PG_HOST" -p "$PG_PORT" -U "$DB_USER" -d "$DB_NAME" "$@"
}

# ── 1. Verify superuser connectivity ─────────────────────────
info "Verifying superuser connection..."
if ! PGPASSWORD="" psql -h "$PG_HOST" -p "$PG_PORT" -U "$SUPERUSER" -c "SELECT 1" -d postgres >/dev/null 2>&1; then
  warn "Cannot connect as '$SUPERUSER'. Trying current OS user..."
  SUPERUSER="$(whoami)"
  if ! psql -h "$PG_HOST" -p "$PG_PORT" -U "$SUPERUSER" -c "SELECT 1" -d postgres >/dev/null 2>&1; then
    error "Cannot connect to PostgreSQL at $PG_HOST:$PG_PORT.\n  Is PostgreSQL running?  Try: brew services start postgresql@16"
  fi
fi
success "Superuser connection OK"

# ── 2. Optional drop ──────────────────────────────────────────
if [[ "$DROP_DB" == "true" ]]; then
  warn "Dropping database '$DB_NAME'..."
  su_psql -d postgres -c "DROP DATABASE IF EXISTS $DB_NAME;" 2>/dev/null || true
  success "Database dropped"
fi

# ── 3. Create role if not exists ─────────────────────────────
info "Ensuring role '$DB_USER' exists..."
ROLE_EXISTS=$(su_psql -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" 2>/dev/null || echo "")
if [[ -z "$ROLE_EXISTS" ]]; then
  su_psql -d postgres -c "CREATE ROLE $DB_USER WITH LOGIN PASSWORD '$DB_PASS';" >/dev/null
  success "Role '$DB_USER' created"
else
  # Update password in case it changed
  su_psql -d postgres -c "ALTER ROLE $DB_USER WITH PASSWORD '$DB_PASS';" >/dev/null
  success "Role '$DB_USER' already exists (password updated)"
fi

# ── 4. Create database if not exists ─────────────────────────
info "Ensuring database '$DB_NAME' exists..."
DB_EXISTS=$(su_psql -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" 2>/dev/null || echo "")
if [[ -z "$DB_EXISTS" ]]; then
  su_psql -d postgres -c "CREATE DATABASE $DB_NAME OWNER $DB_USER ENCODING 'UTF8';" >/dev/null
  success "Database '$DB_NAME' created"
else
  success "Database '$DB_NAME' already exists"
fi

# Grant privileges
su_psql -d "$DB_NAME" -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;" >/dev/null
su_psql -d "$DB_NAME" -c "GRANT ALL ON SCHEMA public TO $DB_USER;" >/dev/null

# ── 5. Apply schema ───────────────────────────────────────────
info "Applying schema..."
if PGPASSWORD="$DB_PASS" psql -h "$PG_HOST" -p "$PG_PORT" -U "$DB_USER" -d "$DB_NAME" \
    -v ON_ERROR_STOP=1 -f "$SCHEMA_FILE" >/dev/null 2>&1; then
  success "Schema applied"
else
  # Re-run without suppression to show the error
  PGPASSWORD="$DB_PASS" psql -h "$PG_HOST" -p "$PG_PORT" -U "$DB_USER" -d "$DB_NAME" \
    -v ON_ERROR_STOP=1 -f "$SCHEMA_FILE" || error "Schema failed — see error above"
fi

# ── 6. Load seed data ─────────────────────────────────────────
if [[ "$SKIP_SEED" == "false" ]]; then
  info "Loading seed data (Bharat Precision Industries Ltd)..."
  if PGPASSWORD="$DB_PASS" psql -h "$PG_HOST" -p "$PG_PORT" -U "$DB_USER" -d "$DB_NAME" \
      -v ON_ERROR_STOP=1 -f "$SEED_FILE" >/dev/null 2>&1; then
    success "Seed data loaded"
  else
    PGPASSWORD="$DB_PASS" psql -h "$PG_HOST" -p "$PG_PORT" -U "$DB_USER" -d "$DB_NAME" \
      -v ON_ERROR_STOP=1 -f "$SEED_FILE" || error "Seed failed — see error above"
  fi
fi

# ── 7. Verification ───────────────────────────────────────────
echo ""
echo -e "${BOLD}── Table row counts ──────────────────────────────${NC}"

VERIFY_SQL="
SELECT
  'plants'             AS table_name, COUNT(*) AS rows FROM plants
UNION ALL SELECT 'vendors',           COUNT(*) FROM vendors
UNION ALL SELECT 'gl_accounts',       COUNT(*) FROM gl_accounts
UNION ALL SELECT 'cost_centers',      COUNT(*) FROM cost_centers
UNION ALL SELECT 'materials',         COUNT(*) FROM materials
UNION ALL SELECT 'stock',             COUNT(*) FROM stock
UNION ALL SELECT 'purchase_orders',   COUNT(*) FROM purchase_orders
UNION ALL SELECT 'invoices',          COUNT(*) FROM invoices
UNION ALL SELECT 'customers',         COUNT(*) FROM customers
UNION ALL SELECT 'sales_orders',      COUNT(*) FROM sales_orders
UNION ALL SELECT 'deliveries',        COUNT(*) FROM deliveries
UNION ALL SELECT 'employees',         COUNT(*) FROM employees
UNION ALL SELECT 'leave_balances',    COUNT(*) FROM leave_balances
UNION ALL SELECT 'payroll',           COUNT(*) FROM payroll
UNION ALL SELECT 'work_centers',      COUNT(*) FROM work_centers
UNION ALL SELECT 'production_orders', COUNT(*) FROM production_orders
UNION ALL SELECT 'bom',               COUNT(*) FROM bom
UNION ALL SELECT 'abap_programs',     COUNT(*) FROM abap_programs
UNION ALL SELECT 'function_modules',  COUNT(*) FROM function_modules
UNION ALL SELECT 'transport_requests',COUNT(*) FROM transport_requests
ORDER BY table_name;
"

PGPASSWORD="$DB_PASS" psql -h "$PG_HOST" -p "$PG_PORT" -U "$DB_USER" -d "$DB_NAME" \
  -c "$VERIFY_SQL" 2>/dev/null || warn "Could not run verification query"

# ── 8. Partial index check ────────────────────────────────────
echo ""
echo -e "${BOLD}── Partial index verification ────────────────────${NC}"
INDEX_SQL="
SELECT indexname, tablename
FROM pg_indexes
WHERE indexname IN ('idx_invoices_open','idx_po_open','idx_so_open',
                    'idx_employees_active','idx_stock_reorder',
                    'idx_rl_roles_gin','idx_rl_params_gin')
ORDER BY tablename, indexname;"

PGPASSWORD="$DB_PASS" psql -h "$PG_HOST" -p "$PG_PORT" -U "$DB_USER" -d "$DB_NAME" \
  -c "$INDEX_SQL" 2>/dev/null || true

# ── 9. Write .env hint ───────────────────────────────────────
echo ""
echo -e "${BOLD}── Environment variables ─────────────────────────${NC}"
echo -e "  Add these to your ${BOLD}.env${NC} or export before running the API server:"
echo ""
echo -e "  ${YELLOW}export DB_HOST=$PG_HOST${NC}"
echo -e "  ${YELLOW}export DB_PORT=$PG_PORT${NC}"
echo -e "  ${YELLOW}export DB_USER=$DB_USER${NC}"
echo -e "  ${YELLOW}export DB_PASSWORD=$DB_PASS${NC}"
echo -e "  ${YELLOW}export DB_NAME=$DB_NAME${NC}"
echo ""
echo -e "${GREEN}${BOLD}✓ Initialisation complete.${NC} Start the API server with:"
echo -e "  ${BOLD}uvicorn api.server:app --reload --port 8000${NC}"
echo ""
