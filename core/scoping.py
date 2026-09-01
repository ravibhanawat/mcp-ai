"""
Tenant and record-level row scoping.

Module RBAC decides *which tables* a role may read. This module decides *which
rows within them*, which is the other half of SAP authorization:

  TENANT SCOPING  — a user bound to company A must never see company B's rows.
    Two deployment models are supported:
      "database"  (default, recommended, and the model SAP Business One itself
                  uses): each company is a separate database, so isolation is
                  enforced by the connection, not by a WHERE clause. Nothing to
                  filter — a query cannot reach another company's data.
      "column"    single database with a tenant_id discriminator on every
                  business table. Every query is filtered by the caller's tenant.

  RECORD SCOPING  — "show me all customers" must mean *my* customers when the
    role is scoped to its own records (a salesperson, a branch). Requires an
    owner column on the table; scoping is skipped for tables that have none, and
    `unscoped_tables()` reports those so the gap is visible rather than silent.

Both are configured, never inferred: a security boundary that turns itself on
based on whether a column happens to exist is a boundary you cannot audit.

Configuration (environment):
    TENANCY_MODEL   database | column        (default: database)
    RECORD_SCOPING  off | owner              (default: off)
"""
from __future__ import annotations

import contextvars
import logging
import os
from typing import Any

_logger = logging.getLogger("core.scoping")

# ── Configuration ────────────────────────────────────────────────────────────
TENANCY_DATABASE = "database"
TENANCY_COLUMN   = "column"

SCOPING_OFF   = "off"
SCOPING_OWNER = "owner"


def tenancy_model() -> str:
    return os.environ.get("TENANCY_MODEL", TENANCY_DATABASE).strip().lower()


def record_scoping() -> str:
    return os.environ.get("RECORD_SCOPING", SCOPING_OFF).strip().lower()


# Business tables that carry customer data, and the column naming the owner of
# each row. A table absent from this map is never record-scoped.
OWNER_COLUMNS: dict[str, str] = {
    "customers":     "owner_id",
    "sales_orders":  "owner_id",
    "vendors":       "owner_id",
    "invoices":      "owner_id",
    "deliveries":    "owner_id",
}

TENANT_COLUMN = "tenant_id"

# Roles that see every record within the modules they hold. Everyone else is
# scoped to rows they own when RECORD_SCOPING=owner.
UNSCOPED_ROLES: frozenset[str] = frozenset({"admin"})


# ── Caller context ───────────────────────────────────────────────────────────
_tenant: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "scope_tenant", default=None)
_owner: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "scope_owner", default=None)
_roles: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar(
    "scope_roles", default=())


class scope_context:
    """Bind the caller's tenant, identity and roles for a request.

        with scope_context(tenant_id="ACME", owner_id="alice", roles=["sd_analyst"]):
            ...
    """

    def __init__(self, *, tenant_id: str | None = None,
                 owner_id: str | None = None, roles: list[str] | None = None):
        self._t, self._o, self._r = tenant_id, owner_id, tuple(roles or ())

    def __enter__(self):
        self._tok = (_tenant.set(self._t), _owner.set(self._o), _roles.set(self._r))
        return self

    def __exit__(self, *exc):
        _tenant.reset(self._tok[0]); _owner.reset(self._tok[1]); _roles.reset(self._tok[2])
        return False


def current_tenant() -> str | None:
    return _tenant.get()


def sees_all_records() -> bool:
    """True if the current roles bypass record scoping."""
    return bool(set(_roles.get()) & UNSCOPED_ROLES)


# ── Predicate building ───────────────────────────────────────────────────────

def row_predicate(table: str) -> tuple[str, list[Any]]:
    """Return (sql_fragment, params) restricting `table` to the caller's rows.

    Returns ("", []) when no restriction applies. Callers append the fragment to
    their WHERE clause with AND.
    """
    clauses: list[str] = []
    params:  list[Any] = []

    if tenancy_model() == TENANCY_COLUMN:
        tenant = current_tenant()
        if tenant is None:
            # Fail closed: a column-tenancy deployment with no tenant bound must
            # not fall back to returning every company's rows.
            return "1=0", []
        clauses.append(f"{table}.{TENANT_COLUMN} = %s")
        params.append(tenant)

    if record_scoping() == SCOPING_OWNER and not sees_all_records():
        owner_col = OWNER_COLUMNS.get(table)
        owner = _owner.get()
        if owner_col and owner is not None:
            clauses.append(f"{table}.{owner_col} = %s")
            params.append(owner)

    return (" AND ".join(clauses), params)


def unscoped_tables() -> list[str]:
    """Tables that record scoping is enabled for but cannot enforce.

    A table is unenforceable when it is in OWNER_COLUMNS but the column is not
    present in the live schema. Reported at startup so the gap is visible.
    """
    if record_scoping() != SCOPING_OWNER:
        return []
    try:
        from db.connection import query_all
        rows = query_all(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public'")
    except Exception:
        return sorted(OWNER_COLUMNS)
    present = {(r["table_name"], r["column_name"]) for r in rows}
    return sorted(t for t, col in OWNER_COLUMNS.items() if (t, col) not in present)


def startup_report() -> dict[str, Any]:
    """Configuration summary logged at startup so the posture is never implicit."""
    model, scoping = tenancy_model(), record_scoping()
    gaps = unscoped_tables()
    report = {
        "tenancy_model":   model,
        "record_scoping":  scoping,
        "unenforceable":   gaps,
    }
    if model == TENANCY_DATABASE:
        _logger.info(
            "Tenant isolation: database-per-company. Cross-company access is "
            "prevented by the connection, not by query filters.")
    else:
        _logger.info("Tenant isolation: tenant_id column filter on every query.")
    if scoping == SCOPING_OFF:
        _logger.info(
            "Record scoping: OFF — every role sees all rows in the modules it "
            "holds. Set RECORD_SCOPING=owner to scope rows to their owner.")
    elif gaps:
        _logger.warning(
            "Record scoping is ON but these tables have no owner column and "
            "therefore return all rows: %s. Run scripts/add_row_scoping.sql.",
            ", ".join(gaps))
    return report
