# SAP Write Approval Layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put every SAP write — sales orders, production orders, leave, receipts (park and post), broker POs — behind a deterministic policy engine and a human approver, without the LLM being able to route around it.

**Architecture:** A new `core/approvals/` package hooks into `tools/tool_registry.execute_tool()`, the one choke point every caller already shares. A resolver does read-only lookups to establish the amount (which is *not* in the tool parameters), a pure policy engine picks the approver chain from a JSON config the model never sees, and a separate executor calls SAP only after approval, claiming the row atomically so it cannot double-execute.

**Tech Stack:** Python 3.11+, FastAPI, psycopg3 (`db.connection`), PostgreSQL, `unittest` + `unittest.mock.patch` run under pytest, React 19 + zustand (already dependencies).

**Spec:** `docs/superpowers/specs/2026-09-03-approval-layer-design.md`

## Global Constraints

- **No new Python dependencies.** Everything uses the stdlib plus what is already in `requirements.txt`. `requests` is the HTTP client for outbound webhooks.
- **No new frontend dependencies.** Components are built from scratch. `zustand` is already a dependency and already used by `frontend/src/stores/chat-store.js`.
- **Tests are `unittest.TestCase` classes** in `tests/`, run by pytest (`pytest.ini` sets `testpaths = tests`, `timeout = 60`). No live database: patch the module-level DB helpers, following `tests/test_ai_admin_api.py`.
- **JSONB parameters are passed as JSON strings** via a local `_j()` helper, matching `db/activity_log.py:37`. Do not introduce `psycopg.types.json.Json`.
- **Migrations are a flat list of idempotent DDL statements** applied at startup and wrapped in try/except, matching `ai/schema.py:run_ai_migrations` and `db/activity_log.py:run_migrations`. A database that is down must not stop the server from starting.
- **Money is `DECIMAL(18,2)`, currency defaults to `INR`.** Never use float for a stored amount; convert to `float` only at the JSON boundary.
- **Thresholds live in `core/approvals/policy_rules.json` only.** They must never appear in a system prompt or be reachable from a tool.
- **Any FastAPI test that installs `app.dependency_overrides` must define `tearDownModule()` to clear them** — the app object is process-global and leaking overrides breaks later test modules. See the comment at `tests/test_ai_admin_api.py:29`.
- **Commit after every task.** Conventional-commit prefixes (`feat:`, `fix:`, `test:`, `docs:`).

---

## File Structure

**New — `core/approvals/`**

| File | Responsibility |
|---|---|
| `__init__.py` | Empty. Package marker. |
| `schema.py` | The three tables' DDL + `run_approval_migrations()`. |
| `store.py` | Every SQL statement against the three tables. The only module that writes them. |
| `events.py` | One place a state change is recorded: writes the audit row, fans out to registered sinks. |
| `policy_rules.json` | Thresholds, chains, SLAs. Data, not code. |
| `policy.py` | Pure `(action, measures, risk_flags) → Decision`. No I/O. |
| `resolvers.py` | Per-action read-only lookups → `Draft`. |
| `gate.py` | `intercept()` / `record_auto()` / `preview()` / `bypass()`. Called from `execute_tool()`. |
| `executor.py` | Atomic claim, revalidate, execute, extract document number. |
| `webhooks.py` | HMAC sign/verify, target URL check, outbound emit + delivery retry. |
| `escalation.py` | The 60-second sweeper: escalate, retry deliveries, expire. |

**New — API and frontend**

| File | Responsibility |
|---|---|
| `api/routes_approvals.py` | JWT-authenticated inbox: list, detail, approve, reject, edit, stats. |
| `api/routes_approval_webhooks.py` | HMAC-authenticated inbound: decision, SAP document status. |
| `frontend/src/stores/approvals-store.js` | zustand store: list, filters, detail, actions. |
| `frontend/src/components/approvals/ApprovalsView.jsx` | Inbox shell with scope tabs. |
| `frontend/src/components/approvals/ApprovalCard.jsx` | One row: summary, amount, risk chips, SLA age. |
| `frontend/src/components/approvals/ApprovalDetail.jsx` | Payload, context, event trail, approve/reject/edit. |

**Modified**

| File | Change |
|---|---|
| `core/authorization.py` | Public `current_actor()` / `current_roles()` / `enforcement_on()`; `execution_context` gains `roles`; `confirmation_required()` payload gains `draft`. |
| `tools/tool_registry.py:791` | `execute_tool()` calls `gate.intercept()` and `gate.record_auto()`. |
| `api/server.py` | Mount two routers; pass `roles` into `execution_context` (chat) and `_roles.set(...)` (stream); start the sweeper in `lifespan`. |
| `auth/rbac.py` | Five approver roles. |
| `agent/sap_agent.py` | Three sentences in the system prompt. |
| `db/schema.sql` | The three tables, for fresh installs. |
| `frontend/src/App.jsx` | Approvals nav entry + badge. |
| `frontend/src/components/chat/MessageRow.jsx` | Render `APPROVAL_REQUIRED`. |
| `frontend/src/lib/api.js` | Approvals API calls. |

---

## Phase 1 — Core

The gate works end to end at the end of this phase: writes are resolved, evaluated, auto-executed or queued, and approved requests execute exactly once. There is no UI and no webhook yet; approvals are exercised through the store in tests.

### Task 1: Approval tables and startup migration

**Files:**
- Create: `core/approvals/__init__.py` (empty)
- Create: `core/approvals/schema.py`
- Modify: `db/schema.sql` (append the same DDL for fresh installs)
- Test: `tests/test_approvals_schema.py`

**Interfaces:**
- Consumes: `db.connection.get_db`
- Produces: `APPROVAL_MIGRATION_SQL: list[str]`, `APPROVAL_TABLES: tuple[str, ...]`, `run_approval_migrations() -> None`

- [ ] **Step 1: Write the failing test**

```python
"""DDL shape and the must-not-crash-startup contract for approval migrations."""
import unittest
from unittest.mock import MagicMock, patch


class TestMigrationSql(unittest.TestCase):

    def test_every_statement_is_idempotent(self):
        from core.approvals.schema import APPROVAL_MIGRATION_SQL
        for ddl in APPROVAL_MIGRATION_SQL:
            self.assertIn("IF NOT EXISTS", ddl,
                          f"non-idempotent DDL would fail on second boot: {ddl[:60]}")

    def test_all_three_tables_are_created(self):
        from core.approvals.schema import APPROVAL_MIGRATION_SQL, APPROVAL_TABLES
        joined = " ".join(APPROVAL_MIGRATION_SQL)
        for table in APPROVAL_TABLES:
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", joined)

    def test_event_idempotency_is_enforced_by_a_unique_index(self):
        # This index is what makes a retried decision webhook a no-op rather
        # than a second decision. Losing it silently allows double-approval.
        from core.approvals.schema import APPROVAL_MIGRATION_SQL
        joined = " ".join(APPROVAL_MIGRATION_SQL)
        self.assertIn("CREATE UNIQUE INDEX IF NOT EXISTS uq_appr_event_idem", joined)
        self.assertIn("approval_events(request_id, idempotency_key)", joined)


class TestRunMigrations(unittest.TestCase):

    def test_executes_every_statement(self):
        from core.approvals import schema
        cur = MagicMock()
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cur
        ctx = MagicMock()
        ctx.__enter__.return_value = conn
        with patch("db.connection.get_db", return_value=ctx):
            schema.run_approval_migrations()
        self.assertEqual(len(schema.APPROVAL_MIGRATION_SQL), cur.execute.call_count)

    def test_a_dead_database_does_not_raise(self):
        # Startup must survive an unavailable database, per ai/schema.py.
        from core.approvals import schema
        with patch("db.connection.get_db", side_effect=RuntimeError("no db")):
            schema.run_approval_migrations()   # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_approvals_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.approvals'`

- [ ] **Step 3: Write the implementation**

Create `core/approvals/__init__.py` as an empty file, then `core/approvals/schema.py`:

```python
"""
DDL for the approval layer.

Follows ai/schema.py and db/activity_log.py: a flat list of idempotent
statements applied at startup, wrapped so a database that is not up cannot
stop the server from starting.

Two shapes differ from the obvious sketch and are worth explaining:

  * `approval_chain` holds the whole ordered chain rather than a single
    approver role, because two actions need more than one signature —
    initiate_broker_po already advertises release_levels: 2 in its own return
    value. `approver_role` is a denormalised copy of the current entry so the
    inbox query stays a plain indexed lookup.

  * The unique index on approval_events(request_id, idempotency_key) is what
    makes a retried inbound decision webhook a no-op. Without it, a receiver
    that retries on timeout approves the same request twice.
"""
from __future__ import annotations

import logging

_logger = logging.getLogger("core.approvals.schema")

APPROVAL_TABLES: tuple[str, ...] = (
    "approval_requests",
    "approval_events",
    "approval_deliveries",
)

APPROVAL_MIGRATION_SQL: list[str] = [
    """CREATE TABLE IF NOT EXISTS approval_requests (
        request_id       VARCHAR(24)   PRIMARY KEY,
        action           VARCHAR(64)   NOT NULL,
        entity_type      VARCHAR(32)   NOT NULL,
        payload          JSONB         NOT NULL,
        context          JSONB         NOT NULL DEFAULT '{}'::jsonb,
        measures         JSONB         NOT NULL DEFAULT '{}'::jsonb,
        amount           DECIMAL(18,2),
        currency         CHAR(3)       DEFAULT 'INR',
        summary          TEXT          NOT NULL,
        risk_flags       JSONB         NOT NULL DEFAULT '[]'::jsonb,
        requested_by     VARCHAR(64)   NOT NULL,
        requester_roles  JSONB         NOT NULL DEFAULT '[]'::jsonb,
        approval_chain   JSONB         NOT NULL DEFAULT '[]'::jsonb,
        chain_index      SMALLINT      NOT NULL DEFAULT 0,
        approver_role    VARCHAR(48),
        status           VARCHAR(16)   NOT NULL,
        decided_by       VARCHAR(64),
        decided_at       TIMESTAMPTZ,
        decision_comment TEXT,
        sap_doc_number   VARCHAR(32),
        sap_doc_field    VARCHAR(32),
        sap_doc_status   VARCHAR(20),
        error            TEXT,
        idempotency_key  VARCHAR(64)   NOT NULL UNIQUE,
        sla_due_at       TIMESTAMPTZ,
        expires_at       TIMESTAMPTZ,
        session_id       VARCHAR(128),
        supersedes       VARCHAR(24),
        superseded_by    VARCHAR(24),
        created_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
        updated_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_appr_inbox   ON approval_requests(status, approver_role, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_appr_mine    ON approval_requests(requested_by, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_appr_sla     ON approval_requests(status, sla_due_at)",
    "CREATE INDEX IF NOT EXISTS idx_appr_expiry  ON approval_requests(status, expires_at)",
    "CREATE INDEX IF NOT EXISTS idx_appr_payload ON approval_requests USING GIN (payload)",

    """CREATE TABLE IF NOT EXISTS approval_events (
        event_id        INTEGER      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        request_id      VARCHAR(24)  NOT NULL REFERENCES approval_requests(request_id) ON DELETE CASCADE,
        event           VARCHAR(32)  NOT NULL,
        actor           VARCHAR(64),
        comment         TEXT,
        payload_before  JSONB,
        payload_after   JSONB,
        idempotency_key VARCHAR(64),
        created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_appr_ev_req ON approval_events(request_id, created_at ASC)",
    # Partial: many events legitimately carry no caller-supplied key.
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_appr_event_idem
       ON approval_events(request_id, idempotency_key)
       WHERE idempotency_key IS NOT NULL""",

    """CREATE TABLE IF NOT EXISTS approval_deliveries (
        delivery_id     INTEGER      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        request_id      VARCHAR(24)  NOT NULL,
        event           VARCHAR(32)  NOT NULL,
        url             TEXT         NOT NULL,
        body            TEXT         NOT NULL,
        attempts        SMALLINT     NOT NULL DEFAULT 0,
        next_attempt_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        status          VARCHAR(12)  NOT NULL DEFAULT 'pending',
        response_code   SMALLINT,
        last_error      TEXT,
        created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_appr_deliv_due ON approval_deliveries(status, next_attempt_at)",
]


def run_approval_migrations() -> None:
    """Create the approval tables if absent. Called at server startup."""
    try:
        from db.connection import get_db
        with get_db() as conn:
            with conn.cursor() as cur:
                for ddl in APPROVAL_MIGRATION_SQL:
                    cur.execute(ddl)
        _logger.info("Approval migrations applied.")
    except Exception as exc:
        _logger.warning("Approval migration failed (DB may not be available): %s", exc)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_approvals_schema.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Mirror the DDL into `db/schema.sql`**

Append the three `CREATE TABLE` statements and their indexes to the end of `db/schema.sql`, under a section header matching the file's existing style:

```sql
-- ── Approval layer ────────────────────────────────────────────────────────────
```

This file is the fresh-install path (`psql -f schema.sql`); `schema.py` is the running-server path. Both must agree.

- [ ] **Step 6: Commit**

```bash
git add core/approvals/__init__.py core/approvals/schema.py db/schema.sql tests/test_approvals_schema.py
git commit -m "feat(approvals): approval_requests, approval_events, approval_deliveries tables"
```

---

### Task 2: Approval store

**Files:**
- Create: `core/approvals/store.py`
- Test: `tests/test_approvals_store.py`

**Interfaces:**
- Consumes: `db.connection.query_one`, `query_all`, `execute`
- Produces:
  - `new_request_id() -> str` — `"apr_" + 16 hex`
  - `create_request(**kw) -> dict`
  - `get_request(request_id: str) -> dict | None`
  - `list_requests(*, scope_roles: list[str] | None = None, requested_by: str | None = None, status: str | None = None, action: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]`
  - `count_by_status(*, scope_roles=None, requested_by=None) -> dict[str, int]`
  - `claim_for_execution(request_id: str) -> dict | None` — atomic
  - `mark_executed(request_id, *, sap_doc_number, sap_doc_field) -> None`
  - `mark_failed(request_id, *, error) -> None`
  - `advance_or_approve(request_id, *, decided_by, comment) -> dict | None`
  - `reject(request_id, *, decided_by, comment) -> dict | None`
  - `mark_superseded(request_id, *, superseded_by) -> None`
  - `add_event(request_id, *, event, actor=None, comment=None, payload_before=None, payload_after=None, idempotency_key=None) -> bool`
  - `list_events(request_id) -> list[dict]`
  - `due_for_escalation() -> list[dict]`, `due_for_expiry() -> list[dict]`

- [ ] **Step 1: Write the failing test**

```python
"""Store tests. No live database: the three db.connection helpers are patched
where store.py imported them."""
import unittest
from unittest.mock import patch

BASE = dict(
    action="create_sales_order", entity_type="sales_order",
    payload={"customer_id": "C001", "material_id": "M001", "qty": 10},
    context={"customer_name": "Acme"}, measures={"amount": 420000.0},
    amount=420000.0, currency="INR", summary="Sales order for Acme — INR 4,20,000",
    risk_flags=["over_credit_limit"], requested_by="ravi", requester_roles=["sd_analyst"],
    approval_chain=[{"role": "sales_manager", "escalate_to": "cfo", "sla_hours": 8}],
    status="pending", session_id="s1",
)


class TestRequestId(unittest.TestCase):

    def test_shape_and_uniqueness(self):
        from core.approvals.store import new_request_id
        a, b = new_request_id(), new_request_id()
        self.assertTrue(a.startswith("apr_"))
        self.assertEqual(20, len(a))          # "apr_" + 16 hex
        self.assertNotEqual(a, b)


class TestCreate(unittest.TestCase):

    def test_first_chain_entry_becomes_approver_role(self):
        from core.approvals import store
        captured = {}

        def fake_query_one(sql, params=(), **kw):
            captured["sql"], captured["params"] = sql, params
            return {"request_id": "apr_x", "status": "pending"}

        with patch.object(store, "query_one", fake_query_one):
            store.create_request(**BASE)
        # approver_role is denormalised from approval_chain[0].role so the
        # inbox query is a plain indexed lookup.
        self.assertIn("sales_manager", captured["params"])

    def test_auto_tier_has_no_approver_role_and_no_sla(self):
        from core.approvals import store
        captured = {}

        def fake_query_one(sql, params=(), **kw):
            captured["params"] = params
            return {"request_id": "apr_x", "status": "executed"}

        auto = {**BASE, "approval_chain": [], "status": "executed"}
        with patch.object(store, "query_one", fake_query_one):
            store.create_request(**auto)
        self.assertIn(None, captured["params"])


class TestAtomicClaim(unittest.TestCase):

    def test_claim_only_succeeds_from_approved(self):
        # The guard against double execution is the WHERE clause, not a read.
        from core.approvals import store
        seen = {}

        def fake_query_one(sql, params=(), **kw):
            seen["sql"] = " ".join(sql.split())
            return {"request_id": "apr_x", "status": "executing"}

        with patch.object(store, "query_one", fake_query_one):
            row = store.claim_for_execution("apr_x")
        self.assertIsNotNone(row)
        self.assertIn("SET status = 'executing'", seen["sql"])
        self.assertIn("WHERE request_id = %s AND status = 'approved'", seen["sql"])
        self.assertIn("RETURNING", seen["sql"])

    def test_claim_returns_none_when_already_claimed(self):
        from core.approvals import store
        with patch.object(store, "query_one", return_value=None):
            self.assertIsNone(store.claim_for_execution("apr_x"))


class TestChainAdvance(unittest.TestCase):

    def test_intermediate_approval_advances_index_and_stays_pending(self):
        from core.approvals import store
        row = {
            "request_id": "apr_x", "status": "pending", "chain_index": 0,
            "approval_chain": [{"role": "finance_manager", "sla_hours": 8},
                               {"role": "cfo", "sla_hours": 24}],
        }
        captured = {}

        def fake_query_one(sql, params=(), **kw):
            if "SELECT" in sql.upper().split("SET")[0] and "UPDATE" not in sql.upper():
                return row
            captured["params"] = params
            return {**row, "chain_index": 1, "approver_role": "cfo"}

        with patch.object(store, "query_one", fake_query_one):
            out = store.advance_or_approve("apr_x", decided_by="fm", comment="ok")
        self.assertEqual("pending", out["status"])
        self.assertEqual(1, out["chain_index"])
        self.assertEqual("cfo", out["approver_role"])

    def test_final_approval_sets_approved(self):
        from core.approvals import store
        row = {
            "request_id": "apr_x", "status": "pending", "chain_index": 1,
            "approval_chain": [{"role": "finance_manager", "sla_hours": 8},
                               {"role": "cfo", "sla_hours": 24}],
        }

        def fake_query_one(sql, params=(), **kw):
            if "UPDATE" not in sql.upper():
                return row
            return {**row, "status": "approved"}

        with patch.object(store, "query_one", fake_query_one):
            out = store.advance_or_approve("apr_x", decided_by="cfo", comment="ok")
        self.assertEqual("approved", out["status"])


class TestEventIdempotency(unittest.TestCase):

    def test_duplicate_key_returns_false_instead_of_raising(self):
        # A retried webhook must be a no-op, not a 500.
        import psycopg
        from core.approvals import store
        with patch.object(store, "execute",
                          side_effect=psycopg.errors.UniqueViolation("dup")):
            self.assertFalse(
                store.add_event("apr_x", event="approved", idempotency_key="k1"))

    def test_new_event_returns_true(self):
        from core.approvals import store
        with patch.object(store, "execute", return_value=1):
            self.assertTrue(
                store.add_event("apr_x", event="approved", idempotency_key="k2"))


class TestInboxScoping(unittest.TestCase):

    def test_scope_roles_filters_on_approver_role(self):
        from core.approvals import store
        captured = {}

        def fake_query_all(sql, params=(), **kw):
            captured["sql"], captured["params"] = " ".join(sql.split()), params
            return []

        with patch.object(store, "query_all", fake_query_all):
            store.list_requests(scope_roles=["sales_manager", "cfo"], status="pending")
        self.assertIn("approver_role = ANY(%s)", captured["sql"])
        self.assertIn(["sales_manager", "cfo"], captured["params"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_approvals_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.approvals.store'`

- [ ] **Step 3: Write the implementation**

```python
"""
Every SQL statement against the approval tables. Nothing else writes them.

Two things here are load-bearing and must not be "simplified":

  * claim_for_execution() is an UPDATE ... WHERE status = 'approved' RETURNING.
    The guard against executing a request twice is that WHERE clause, evaluated
    by PostgreSQL under row lock. Reading the status and then acting on it is
    the race that double-posts a receipt.

  * add_event() converts a unique-violation into False rather than letting it
    raise. That is what makes a retried inbound decision webhook a no-op.

JSONB columns are written as JSON strings via _j(), matching the convention in
db/activity_log.py.
"""
from __future__ import annotations

import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import psycopg

from db.connection import execute, query_all, query_one

_logger = logging.getLogger("core.approvals.store")

_COLUMNS = """request_id, action, entity_type, payload, context, measures, amount,
    currency, summary, risk_flags, requested_by, requester_roles, approval_chain,
    chain_index, approver_role, status, decided_by, decided_at, decision_comment,
    sap_doc_number, sap_doc_field, sap_doc_status, error, idempotency_key,
    sla_due_at, expires_at, session_id, supersedes, superseded_by,
    created_at, updated_at"""


class _SafeEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        if isinstance(o, (datetime,)):
            return o.isoformat()
        return str(o)


def _j(obj: Any) -> str | None:
    """Serialise for a JSONB column. Mirrors db/activity_log.py."""
    if obj is None:
        return None
    return json.dumps(obj, cls=_SafeEncoder)


def new_request_id() -> str:
    return "apr_" + secrets.token_hex(8)


def create_request(
    *, action: str, entity_type: str, payload: dict, context: dict,
    measures: dict, amount: float | None, currency: str, summary: str,
    risk_flags: list[str], requested_by: str, requester_roles: list[str],
    approval_chain: list[dict], status: str, session_id: str | None = None,
    supersedes: str | None = None, sap_doc_number: str | None = None,
    sap_doc_field: str | None = None, hard_ttl_hours: int = 72,
) -> dict | None:
    """Insert one request. Returns the stored row."""
    now = datetime.now(timezone.utc)
    first = approval_chain[0] if approval_chain else None
    approver_role = first["role"] if first else None
    sla_due_at = (now + timedelta(hours=int(first.get("sla_hours", 24)))) if first else None
    expires_at = (now + timedelta(hours=hard_ttl_hours)) if first else None
    return query_one(
        f"""INSERT INTO approval_requests
            (request_id, action, entity_type, payload, context, measures, amount,
             currency, summary, risk_flags, requested_by, requester_roles,
             approval_chain, chain_index, approver_role, status, idempotency_key,
             sla_due_at, expires_at, session_id, supersedes, sap_doc_number, sap_doc_field)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING {_COLUMNS}""",
        (new_request_id(), action, entity_type, _j(payload), _j(context), _j(measures),
         amount, currency, summary, _j(risk_flags), requested_by, _j(requester_roles),
         _j(approval_chain), approver_role, status, uuid.uuid4().hex,
         sla_due_at, expires_at, session_id, supersedes, sap_doc_number, sap_doc_field),
    )


def get_request(request_id: str) -> dict | None:
    return query_one(
        f"SELECT {_COLUMNS} FROM approval_requests WHERE request_id = %s", (request_id,))


def list_requests(*, scope_roles: list[str] | None = None,
                  requested_by: str | None = None, status: str | None = None,
                  action: str | None = None, limit: int = 50,
                  offset: int = 0) -> list[dict]:
    clauses, params = [], []
    if scope_roles is not None:
        clauses.append("approver_role = ANY(%s)"); params.append(list(scope_roles))
    if requested_by:
        clauses.append("requested_by = %s"); params.append(requested_by)
    if status:
        clauses.append("status = %s"); params.append(status)
    if action:
        clauses.append("action = %s"); params.append(action)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.extend([limit, offset])
    return query_all(
        f"""SELECT {_COLUMNS} FROM approval_requests {where}
            ORDER BY created_at DESC LIMIT %s OFFSET %s""",
        tuple(params),
    )


def count_by_status(*, scope_roles: list[str] | None = None,
                    requested_by: str | None = None) -> dict[str, int]:
    clauses, params = [], []
    if scope_roles is not None:
        clauses.append("approver_role = ANY(%s)"); params.append(list(scope_roles))
    if requested_by:
        clauses.append("requested_by = %s"); params.append(requested_by)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = query_all(
        f"SELECT status, COUNT(*) AS n FROM approval_requests {where} GROUP BY status",
        tuple(params),
    )
    return {r["status"]: int(r["n"]) for r in rows}


def claim_for_execution(request_id: str) -> dict | None:
    """Atomically take ownership of an approved request. None if not ours."""
    return query_one(
        f"""UPDATE approval_requests
            SET status = 'executing', updated_at = NOW()
            WHERE request_id = %s AND status = 'approved'
            RETURNING {_COLUMNS}""",
        (request_id,),
    )


def mark_executed(request_id: str, *, sap_doc_number: str | None,
                  sap_doc_field: str | None) -> None:
    execute(
        """UPDATE approval_requests
           SET status = 'executed', sap_doc_number = %s, sap_doc_field = %s,
               error = NULL, updated_at = NOW()
           WHERE request_id = %s""",
        (sap_doc_number, sap_doc_field, request_id),
    )


def mark_failed(request_id: str, *, error: str) -> None:
    execute(
        """UPDATE approval_requests
           SET status = 'failed', error = %s, updated_at = NOW()
           WHERE request_id = %s""",
        (error[:2000], request_id),
    )


def advance_or_approve(request_id: str, *, decided_by: str,
                       comment: str | None) -> dict | None:
    """Record one signature. Advances the chain, or approves if it was the last."""
    row = get_request(request_id)
    if row is None or row["status"] != "pending":
        return None
    chain = row["approval_chain"] or []
    nxt = row["chain_index"] + 1
    if nxt < len(chain):
        entry = chain[nxt]
        sla = datetime.now(timezone.utc) + timedelta(hours=int(entry.get("sla_hours", 24)))
        return query_one(
            f"""UPDATE approval_requests
                SET chain_index = %s, approver_role = %s, sla_due_at = %s,
                    decided_by = %s, decision_comment = %s, updated_at = NOW()
                WHERE request_id = %s AND status = 'pending'
                RETURNING {_COLUMNS}""",
            (nxt, entry["role"], sla, decided_by, comment, request_id),
        )
    return query_one(
        f"""UPDATE approval_requests
            SET status = 'approved', decided_by = %s, decided_at = NOW(),
                decision_comment = %s, updated_at = NOW()
            WHERE request_id = %s AND status = 'pending'
            RETURNING {_COLUMNS}""",
        (decided_by, comment, request_id),
    )


def reject(request_id: str, *, decided_by: str, comment: str) -> dict | None:
    return query_one(
        f"""UPDATE approval_requests
            SET status = 'rejected', decided_by = %s, decided_at = NOW(),
                decision_comment = %s, updated_at = NOW()
            WHERE request_id = %s AND status = 'pending'
            RETURNING {_COLUMNS}""",
        (decided_by, comment, request_id),
    )


def mark_superseded(request_id: str, *, superseded_by: str) -> None:
    execute(
        """UPDATE approval_requests
           SET status = 'superseded', superseded_by = %s, updated_at = NOW()
           WHERE request_id = %s AND status = 'pending'""",
        (superseded_by, request_id),
    )


def add_event(request_id: str, *, event: str, actor: str | None = None,
              comment: str | None = None, payload_before: dict | None = None,
              payload_after: dict | None = None,
              idempotency_key: str | None = None) -> bool:
    """Append to the trail. False means this exact event was already recorded."""
    try:
        execute(
            """INSERT INTO approval_events
               (request_id, event, actor, comment, payload_before, payload_after,
                idempotency_key)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (request_id, event, actor, comment, _j(payload_before),
             _j(payload_after), idempotency_key),
        )
        return True
    except psycopg.errors.UniqueViolation:
        _logger.info("Duplicate approval event ignored (%s / %s)", request_id, idempotency_key)
        return False


def list_events(request_id: str) -> list[dict]:
    return query_all(
        """SELECT event_id, event, actor, comment, payload_before, payload_after,
                  created_at
           FROM approval_events WHERE request_id = %s ORDER BY created_at ASC""",
        (request_id,),
    )


def due_for_escalation() -> list[dict]:
    return query_all(
        f"""SELECT {_COLUMNS} FROM approval_requests
            WHERE status = 'pending' AND sla_due_at IS NOT NULL AND sla_due_at < NOW()""")


def due_for_expiry() -> list[dict]:
    return query_all(
        f"""SELECT {_COLUMNS} FROM approval_requests
            WHERE status = 'pending' AND expires_at IS NOT NULL AND expires_at < NOW()""")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_approvals_store.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add core/approvals/store.py tests/test_approvals_store.py
git commit -m "feat(approvals): store with atomic execution claim and idempotent events"
```

---
### Task 3: Policy engine

Pure functions over pure data. This is the component whose behaviour must be
exhaustively testable, which is why it does no I/O at all — not even reading the
config file, which is loaded once and cached.

**Files:**
- Create: `core/approvals/policy_rules.json`
- Create: `core/approvals/policy.py`
- Test: `tests/test_approvals_policy.py`

**Interfaces:**
- Consumes: nothing (stdlib only)
- Produces:
  - `ChainEntry` dataclass — `role: str`, `escalate_to: str | None`, `sla_hours: int`
  - `Decision` dataclass — `auto: bool`, `chain: tuple[ChainEntry, ...]`, `entity_type: str`, `tier_index: int`
  - `evaluate(action: str, measures: dict[str, float], risk_flags: list[str]) -> Decision | None` (None = action not governed)
  - `is_governed(action: str) -> bool`
  - `chain_as_dicts(chain) -> list[dict]`
  - `hard_ttl_hours() -> int`, `allow_self_approval() -> bool`, `amount_tolerance_pct() -> float`
  - `reload_rules() -> None` (tests only)

- [ ] **Step 1: Write the failing test**

```python
"""Table-driven tests over the pure policy engine — boundaries especially.
An off-by-one here silently auto-approves money."""
import unittest


class TestTierSelection(unittest.TestCase):

    def setUp(self):
        from core.approvals import policy
        policy.reload_rules()
        self.policy = policy

    def _chain(self, action, measures, flags=()):
        d = self.policy.evaluate(action, measures, list(flags))
        return d, [e.role for e in d.chain]

    def test_sales_order_below_threshold_is_auto(self):
        d, roles = self._chain("create_sales_order", {"amount": 49999})
        self.assertTrue(d.auto)
        self.assertEqual([], roles)

    def test_sales_order_exactly_at_threshold_is_auto(self):
        # max is inclusive: 50,000 is "less than or equal", not the next tier.
        d, roles = self._chain("create_sales_order", {"amount": 50000})
        self.assertTrue(d.auto)

    def test_one_rupee_over_threshold_needs_a_manager(self):
        d, roles = self._chain("create_sales_order", {"amount": 50001})
        self.assertFalse(d.auto)
        self.assertEqual(["sales_manager"], roles)

    def test_top_tier_needs_two_signatures(self):
        d, roles = self._chain("create_sales_order", {"amount": 5000001})
        self.assertEqual(["sales_manager", "cfo"], roles)

    def test_leave_keys_on_days_not_amount(self):
        d, roles = self._chain("apply_leave", {"days": 2})
        self.assertTrue(d.auto)
        d, roles = self._chain("apply_leave", {"days": 4})
        self.assertEqual(["hr_approver"], roles)

    def test_broker_po_always_needs_two_levels(self):
        # Matches release_levels: 2 that modules/sd.py already returns.
        d, roles = self._chain("initiate_broker_po", {"amount": 1})
        self.assertFalse(d.auto)
        self.assertEqual(["finance_manager", "cfo"], roles)

    def test_receipts_have_no_auto_tier(self):
        for action in ("park_customer_receipt", "post_customer_receipt"):
            d, roles = self._chain(action, {"amount": 1})
            self.assertFalse(d.auto, f"{action} must not auto-approve")


class TestRiskEscalation(unittest.TestCase):

    def setUp(self):
        from core.approvals import policy
        policy.reload_rules()
        self.policy = policy

    def test_over_credit_limit_appends_cfo_to_an_auto_order(self):
        # A small order against an exhausted credit limit is not routine.
        d = self.policy.evaluate("create_sales_order", {"amount": 1000},
                                 ["over_credit_limit"])
        self.assertFalse(d.auto)
        self.assertIn("cfo", [e.role for e in d.chain])

    def test_risk_flag_does_not_duplicate_an_existing_role(self):
        d = self.policy.evaluate("create_sales_order", {"amount": 6000000},
                                 ["over_credit_limit"])
        roles = [e.role for e in d.chain]
        self.assertEqual(len(roles), len(set(roles)))


class TestFailSafe(unittest.TestCase):

    def setUp(self):
        from core.approvals import policy
        policy.reload_rules()
        self.policy = policy

    def test_unknown_action_is_not_governed(self):
        self.assertIsNone(self.policy.evaluate("get_customer_info", {}, []))
        self.assertFalse(self.policy.is_governed("get_customer_info"))

    def test_missing_measure_falls_to_the_strictest_tier(self):
        # If we could not resolve the amount we must not auto-approve.
        d = self.policy.evaluate("create_sales_order", {}, [])
        self.assertFalse(d.auto)
        self.assertEqual(["sales_manager", "cfo"], [e.role for e in d.chain])

    def test_every_governed_action_is_a_known_write_tool(self):
        from core.authorization import WRITE_TOOLS
        from core.approvals import policy
        for action in policy.governed_actions():
            self.assertIn(action, WRITE_TOOLS,
                          f"{action} is in policy_rules.json but is not a write tool")

    def test_every_write_tool_has_a_policy(self):
        # A write tool with no rule would fall through the gate ungoverned.
        from core.authorization import WRITE_TOOLS
        from core.approvals import policy
        for tool in WRITE_TOOLS:
            self.assertTrue(policy.is_governed(tool), f"{tool} has no approval policy")


class TestGlobals(unittest.TestCase):

    def test_self_approval_is_off_by_default(self):
        from core.approvals import policy
        policy.reload_rules()
        self.assertFalse(policy.allow_self_approval())

    def test_amount_tolerance_defaults_to_zero(self):
        from core.approvals import policy
        policy.reload_rules()
        self.assertEqual(0.0, policy.amount_tolerance_pct())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_approvals_policy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.approvals.policy'`

- [ ] **Step 3: Write `core/approvals/policy_rules.json`**

```json
{
  "version": 1,
  "currency": "INR",
  "allow_self_approval": false,
  "hard_ttl_hours": 72,
  "revalidation": {
    "amount_tolerance_pct": 0.0
  },
  "actions": {
    "create_sales_order": {
      "entity_type": "sales_order",
      "measure": "amount",
      "tiers": [
        { "max": 50000, "chain": [] },
        { "max": 500000, "chain": [
          { "role": "sales_manager", "escalate_to": "cfo", "sla_hours": 8 }
        ] },
        { "max": null, "chain": [
          { "role": "sales_manager", "escalate_to": "cfo", "sla_hours": 8 },
          { "role": "cfo", "sla_hours": 24 }
        ] }
      ],
      "risk_escalations": { "over_credit_limit": ["cfo"] }
    },

    "create_production_order": {
      "entity_type": "production_order",
      "measure": "amount",
      "tiers": [
        { "max": 100000, "chain": [] },
        { "max": 1000000, "chain": [
          { "role": "plant_manager", "escalate_to": "cfo", "sla_hours": 12 }
        ] },
        { "max": null, "chain": [
          { "role": "plant_manager", "escalate_to": "cfo", "sla_hours": 12 },
          { "role": "cfo", "sla_hours": 24 }
        ] }
      ],
      "risk_escalations": {}
    },

    "apply_leave": {
      "entity_type": "leave",
      "measure": "days",
      "tiers": [
        { "max": 3, "chain": [] },
        { "max": 10, "chain": [
          { "role": "hr_approver", "sla_hours": 24 }
        ] },
        { "max": null, "chain": [
          { "role": "hr_approver", "sla_hours": 24 },
          { "role": "cfo", "sla_hours": 48 }
        ] }
      ],
      "risk_escalations": {}
    },

    "park_customer_receipt": {
      "entity_type": "receipt",
      "measure": "amount",
      "tiers": [
        { "max": 500000, "chain": [
          { "role": "finance_manager", "escalate_to": "cfo", "sla_hours": 8 }
        ] },
        { "max": null, "chain": [
          { "role": "finance_manager", "escalate_to": "cfo", "sla_hours": 8 },
          { "role": "cfo", "sla_hours": 24 }
        ] }
      ],
      "risk_escalations": { "excess_basic": ["cfo"], "excess_tds": ["cfo"] }
    },

    "post_customer_receipt": {
      "entity_type": "receipt",
      "measure": "amount",
      "tiers": [
        { "max": 500000, "chain": [
          { "role": "finance_manager", "escalate_to": "cfo", "sla_hours": 8 }
        ] },
        { "max": null, "chain": [
          { "role": "finance_manager", "escalate_to": "cfo", "sla_hours": 8 },
          { "role": "cfo", "sla_hours": 24 }
        ] }
      ],
      "risk_escalations": { "large_excess": ["cfo"] }
    },

    "initiate_broker_po": {
      "entity_type": "broker_po",
      "measure": "amount",
      "tiers": [
        { "max": null, "chain": [
          { "role": "finance_manager", "escalate_to": "cfo", "sla_hours": 8 },
          { "role": "cfo", "sla_hours": 24 }
        ] }
      ],
      "risk_escalations": {}
    }
  }
}
```

- [ ] **Step 4: Write `core/approvals/policy.py`**

```python
"""
The approval policy engine: deterministic, pure, and never reachable by the
model.

Thresholds live in policy_rules.json, not in a system prompt, so they cannot be
argued around by a persuasive user or a prompt injection. The engine has no I/O
beyond loading that file once, which is what makes it exhaustively testable.

Fail-safe direction matters: an action whose measure could not be resolved
falls to the STRICTEST tier, never the most permissive. A missing amount means
"we do not know how much money this is", and the answer to that is a human, not
an auto-approval.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

_logger = logging.getLogger("core.approvals.policy")

_DEFAULT_PATH = Path(__file__).with_name("policy_rules.json")
_rules: dict | None = None


@dataclass(frozen=True)
class ChainEntry:
    role: str
    escalate_to: str | None
    sla_hours: int


@dataclass(frozen=True)
class Decision:
    auto: bool
    chain: tuple[ChainEntry, ...]
    entity_type: str
    tier_index: int


def _load() -> dict:
    global _rules
    if _rules is None:
        path = Path(os.environ.get("APPROVALS_POLICY_PATH") or _DEFAULT_PATH)
        with open(path, encoding="utf-8") as fh:
            _rules = json.load(fh)
        _logger.info("Approval policy loaded from %s (version %s)",
                     path, _rules.get("version"))
    return _rules


def reload_rules() -> None:
    """Drop the cached rules. Tests, and an operator edit followed by restart."""
    global _rules
    _rules = None


def governed_actions() -> list[str]:
    return list(_load().get("actions", {}).keys())


def is_governed(action: str) -> bool:
    return action in _load().get("actions", {})


def hard_ttl_hours() -> int:
    return int(_load().get("hard_ttl_hours", 72))


def allow_self_approval() -> bool:
    return bool(_load().get("allow_self_approval", False))


def amount_tolerance_pct() -> float:
    return float(_load().get("revalidation", {}).get("amount_tolerance_pct", 0.0))


def _entry(raw: dict) -> ChainEntry:
    return ChainEntry(
        role=raw["role"],
        escalate_to=raw.get("escalate_to"),
        sla_hours=int(raw.get("sla_hours", 24)),
    )


def chain_as_dicts(chain: tuple[ChainEntry, ...] | list[ChainEntry]) -> list[dict]:
    """Shape stored in approval_requests.approval_chain."""
    return [{"role": e.role, "escalate_to": e.escalate_to, "sla_hours": e.sla_hours}
            for e in chain]


def evaluate(action: str, measures: dict, risk_flags: list[str]) -> Decision | None:
    """Pick the approver chain. None when the action is not governed at all."""
    rule = _load().get("actions", {}).get(action)
    if rule is None:
        return None

    tiers = rule["tiers"]
    measure_name = rule["measure"]
    value = measures.get(measure_name)

    if value is None:
        # Unresolvable measure → strictest tier. Never the permissive one.
        tier_index = len(tiers) - 1
    else:
        tier_index = len(tiers) - 1
        for i, tier in enumerate(tiers):
            cap = tier.get("max")
            if cap is None or float(value) <= float(cap):
                tier_index = i
                break

    chain = [_entry(e) for e in tiers[tier_index]["chain"]]

    # Risk flags append approvers regardless of amount, and can turn an
    # otherwise-auto action into one needing a signature.
    seen = {e.role for e in chain}
    for flag in risk_flags:
        for role in rule.get("risk_escalations", {}).get(flag, []):
            if role not in seen:
                chain.append(ChainEntry(role=role, escalate_to=None, sla_hours=24))
                seen.add(role)

    return Decision(
        auto=not chain,
        chain=tuple(chain),
        entity_type=rule["entity_type"],
        tier_index=tier_index,
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_approvals_policy.py -v`
Expected: PASS (15 tests)

- [ ] **Step 6: Commit**

```bash
git add core/approvals/policy.py core/approvals/policy_rules.json tests/test_approvals_policy.py
git commit -m "feat(approvals): deterministic policy engine with fail-safe tier selection"
```

---
### Task 4: Resolvers

The component the original requirement was missing. `create_sales_order` takes
`(customer_id, material_id, qty, delivery_days)` — the value comes from
`materials.price × qty` inside `modules/sd.py:110`. Without resolving that by
read-only lookup first, no threshold rule can ever fire.

**Files:**
- Create: `core/approvals/resolvers.py`
- Test: `tests/test_approvals_resolvers.py`

**Interfaces:**
- Consumes: `db.connection.query_one`, `query_all`; `modules.receipt.calculate_receipt_allocation`
- Produces:
  - `Draft` dataclass — `entity_type`, `measures: dict`, `context: dict`, `risk_flags: list[str]`, `blocking: list[str]`, `summary: str`, `amount: float | None`, `currency: str`
  - `resolve(action: str, parameters: dict) -> Draft | None` (None = not governed)
  - `inr(value: float) -> str` — Indian-grouped money formatting for summaries

- [ ] **Step 1: Write the failing test**

```python
"""Resolver tests. Every SAP lookup is patched; these assert the arithmetic and
the blocking rules, which are what stand between an approver and a request that
cannot possibly execute."""
import unittest
from unittest.mock import patch


class TestSalesOrderResolver(unittest.TestCase):

    def test_amount_is_price_times_qty(self):
        # The whole reason resolvers exist: qty is in the payload, price is not.
        from core.approvals import resolvers
        rows = {
            "customers": {"customer_id": "C001", "name": "Acme", "credit_limit": 1000000,
                          "currency": "INR", "status": "ACTIVE"},
            "materials": {"material_id": "M001", "description": "Widget",
                          "price": 4200, "currency": "INR"},
        }
        with patch.object(resolvers, "query_one", side_effect=[rows["customers"], rows["materials"], {"n": 5}]):
            draft = resolvers.resolve("create_sales_order",
                                      {"customer_id": "C001", "material_id": "M001", "qty": 100})
        self.assertEqual(420000.0, draft.measures["amount"])
        self.assertEqual(420000.0, draft.amount)
        self.assertEqual("sales_order", draft.entity_type)
        self.assertIn("Acme", draft.summary)

    def test_over_credit_limit_is_flagged_not_blocked(self):
        # An order above the credit limit is a business decision for a human,
        # not an error — it must reach an approver, not be refused.
        from core.approvals import resolvers
        with patch.object(resolvers, "query_one", side_effect=[
            {"customer_id": "C001", "name": "Acme", "credit_limit": 100000,
             "currency": "INR", "status": "ACTIVE"},
            {"material_id": "M001", "description": "Widget", "price": 4200, "currency": "INR"},
            {"n": 5},
        ]):
            draft = resolvers.resolve("create_sales_order",
                                      {"customer_id": "C001", "material_id": "M001", "qty": 100})
        self.assertIn("over_credit_limit", draft.risk_flags)
        self.assertEqual([], draft.blocking)

    def test_missing_customer_blocks(self):
        from core.approvals import resolvers
        with patch.object(resolvers, "query_one", side_effect=[None]):
            draft = resolvers.resolve("create_sales_order",
                                      {"customer_id": "NOPE", "material_id": "M001", "qty": 1})
        self.assertTrue(draft.blocking)
        self.assertIn("NOPE", draft.blocking[0])

    def test_first_order_flags_new_customer(self):
        from core.approvals import resolvers
        with patch.object(resolvers, "query_one", side_effect=[
            {"customer_id": "C009", "name": "Newco", "credit_limit": 9999999,
             "currency": "INR", "status": "ACTIVE"},
            {"material_id": "M001", "description": "Widget", "price": 10, "currency": "INR"},
            {"n": 0},
        ]):
            draft = resolvers.resolve("create_sales_order",
                                      {"customer_id": "C009", "material_id": "M001", "qty": 1})
        self.assertIn("new_customer", draft.risk_flags)


class TestLeaveResolver(unittest.TestCase):

    def test_days_is_the_measure(self):
        from core.approvals import resolvers
        with patch.object(resolvers, "query_one", side_effect=[
            {"emp_id": "E001", "name": "Asha"},
            {"lb_id": 1, "annual_entitled": 21, "annual_used": 4.0},
        ]):
            draft = resolvers.resolve("apply_leave",
                                      {"emp_id": "E001", "leave_type": "annual", "days": 5})
        self.assertEqual(5, draft.measures["days"])
        self.assertIsNone(draft.amount)
        self.assertEqual(17.0, draft.context["balance"])

    def test_more_days_than_balance_blocks(self):
        # apply_leave would return ERROR anyway; blocking here keeps the queue
        # free of requests that cannot succeed.
        from core.approvals import resolvers
        with patch.object(resolvers, "query_one", side_effect=[
            {"emp_id": "E001", "name": "Asha"},
            {"lb_id": 1, "annual_entitled": 21, "annual_used": 20.0},
        ]):
            draft = resolvers.resolve("apply_leave",
                                      {"emp_id": "E001", "leave_type": "annual", "days": 5})
        self.assertTrue(draft.blocking)

    def test_invalid_leave_type_blocks(self):
        from core.approvals import resolvers
        with patch.object(resolvers, "query_one", side_effect=[{"emp_id": "E001", "name": "Asha"}]):
            draft = resolvers.resolve("apply_leave",
                                      {"emp_id": "E001", "leave_type": "sabbatical", "days": 5})
        self.assertTrue(draft.blocking)


class TestBrokerPoResolver(unittest.TestCase):

    def test_below_20_percent_collection_blocks(self):
        # modules/sd.py refuses this outright; never queue it for a human.
        from core.approvals import resolvers
        with patch.object(resolvers, "query_one", return_value={
            "broker_id": "BR001", "unit_number": "T1-304", "payout_amount": 250000,
            "collected_pct": 12.5, "po_status": "NOT_CREATED", "sale_value": 5000000,
            "broker_name": "Ravi Realty", "customer_name": "Acme",
        }):
            draft = resolvers.resolve("initiate_broker_po",
                                      {"broker_id": "BR001", "unit_number": "T1-304"})
        self.assertTrue(draft.blocking)
        self.assertIn("20", draft.blocking[0])

    def test_existing_po_blocks(self):
        from core.approvals import resolvers
        with patch.object(resolvers, "query_one", return_value={
            "broker_id": "BR001", "unit_number": "T1-304", "payout_amount": 250000,
            "collected_pct": 55.0, "po_status": "CREATED", "sale_value": 5000000,
            "broker_name": "Ravi Realty", "customer_name": "Acme",
        }):
            draft = resolvers.resolve("initiate_broker_po",
                                      {"broker_id": "BR001", "unit_number": "T1-304"})
        self.assertTrue(draft.blocking)

    def test_payout_amount_is_the_measure(self):
        from core.approvals import resolvers
        with patch.object(resolvers, "query_one", return_value={
            "broker_id": "BR001", "unit_number": "T1-304", "payout_amount": 250000,
            "collected_pct": 55.0, "po_status": "NOT_CREATED", "sale_value": 5000000,
            "broker_name": "Ravi Realty", "customer_name": "Acme",
        }):
            draft = resolvers.resolve("initiate_broker_po",
                                      {"broker_id": "BR001", "unit_number": "T1-304"})
        self.assertEqual(250000.0, draft.measures["amount"])
        self.assertEqual([], draft.blocking)


class TestPostReceiptResolver(unittest.TestCase):

    def test_amount_comes_from_the_parked_row(self):
        from core.approvals import resolvers
        with patch.object(resolvers, "query_one", return_value={
            "park_ref": "PRK00000001", "amount": 750000, "status": "PARKED",
            "payment_mode": "CHEQUE", "customer_id": "C001", "unit_number": "T1-304",
            "excess_basic": 0, "excess_tds": 0,
        }):
            draft = resolvers.resolve("post_customer_receipt", {"park_reference": "PRK00000001"})
        self.assertEqual(750000.0, draft.measures["amount"])

    def test_already_posted_blocks(self):
        from core.approvals import resolvers
        with patch.object(resolvers, "query_one", return_value={
            "park_ref": "PRK00000001", "amount": 750000, "status": "POSTED",
            "payment_mode": "CHEQUE", "customer_id": "C001", "unit_number": "T1-304",
            "excess_basic": 0, "excess_tds": 0,
        }):
            draft = resolvers.resolve("post_customer_receipt", {"park_reference": "PRK00000001"})
        self.assertTrue(draft.blocking)


class TestProductionOrderResolver(unittest.TestCase):

    def test_work_center_under_maintenance_blocks(self):
        from core.approvals import resolvers
        with patch.object(resolvers, "query_one", side_effect=[
            {"material_id": "M001", "description": "Widget", "price": 100,
             "currency": "INR", "unit": "EA"},
            {"wc_id": "WC001", "name": "Line 1", "status": "MAINTENANCE"},
        ]):
            draft = resolvers.resolve("create_production_order",
                                      {"material_id": "M001", "qty": 10, "work_center": "WC001"})
        self.assertTrue(draft.blocking)


class TestNotGoverned(unittest.TestCase):

    def test_read_tool_returns_none(self):
        from core.approvals import resolvers
        self.assertIsNone(resolvers.resolve("get_customer_info", {"customer_id": "C001"}))


class TestMoneyFormatting(unittest.TestCase):

    def test_indian_grouping(self):
        from core.approvals.resolvers import inr
        self.assertEqual("1,00,000", inr(100000))
        self.assertEqual("4,20,000", inr(420000))
        self.assertEqual("1,23,45,678", inr(12345678))
        self.assertEqual("999", inr(999))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_approvals_resolvers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.approvals.resolvers'`

- [ ] **Step 3: Write the implementation**

```python
"""
Read-only lookups that turn a tool call into something a policy engine and a
human can both judge.

This exists because the money is not in the parameters. create_sales_order
receives (customer_id, material_id, qty, delivery_days) and computes value from
materials.price internally; initiate_broker_po receives (broker_id, unit_number)
and reads payout_amount off the booking. A threshold rule cannot be evaluated
from the payload alone, so it is evaluated here first.

Blocking versus flagging is the other job, and the distinction is deliberate:

  * BLOCKING means the write is guaranteed to fail — the customer does not
    exist, the receipt is already posted, collection is below the 20% floor
    that modules/sd.py enforces. These never become approval requests; the
    caller gets an ordinary ERROR. An approver should never be asked to sign
    something that cannot execute.

  * FLAGGING means the write will succeed but somebody senior should look —
    over the credit limit, a brand-new customer, an excess receipt. These reach
    the queue with the flag attached, and policy may add approvers for it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from db.connection import query_one

_logger = logging.getLogger("core.approvals.resolvers")


@dataclass(frozen=True)
class Draft:
    entity_type: str
    measures: dict = field(default_factory=dict)
    context: dict = field(default_factory=dict)
    risk_flags: list = field(default_factory=list)
    blocking: list = field(default_factory=list)
    summary: str = ""
    amount: float | None = None
    currency: str = "INR"


def inr(value) -> str:
    """Indian digit grouping: 12345678 -> '1,23,45,678'."""
    n = int(round(float(value)))
    sign, s = ("-" if n < 0 else ""), str(abs(n))
    if len(s) <= 3:
        return sign + s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return sign + ",".join(parts) + "," + tail


# ── Per-action resolvers ─────────────────────────────────────────────────────

def _sales_order(p: dict) -> Draft:
    cust = query_one(
        "SELECT customer_id, name, credit_limit, currency, status FROM customers "
        "WHERE customer_id = %s", (str(p.get("customer_id", "")).upper(),))
    if not cust or cust.get("status") != "ACTIVE":
        return Draft("sales_order",
                     blocking=[f"Customer {p.get('customer_id')} not found or inactive"])
    mat = query_one(
        "SELECT material_id, description, price, currency FROM materials "
        "WHERE material_id = %s", (str(p.get("material_id", "")).upper(),))
    if not mat:
        return Draft("sales_order",
                     blocking=[f"Material {p.get('material_id')} not found"])

    qty = float(p.get("qty") or 0)
    price = float(mat["price"])
    amount = round(qty * price, 2)
    limit = float(cust.get("credit_limit") or 0)

    prior = query_one("SELECT COUNT(*) AS n FROM sales_orders WHERE customer_id = %s",
                      (cust["customer_id"],)) or {"n": 0}

    flags = []
    if limit and amount > limit:
        flags.append("over_credit_limit")
    if int(prior.get("n") or 0) == 0:
        flags.append("new_customer")

    return Draft(
        entity_type="sales_order",
        measures={"amount": amount, "qty": qty},
        context={"customer_name": cust["name"], "material": mat["description"],
                 "unit_price": price, "credit_limit": limit,
                 "prior_orders": int(prior.get("n") or 0)},
        risk_flags=flags,
        summary=(f"Sales order — {qty:g} × {mat['description']} for {cust['name']} "
                 f"= {mat['currency']} {inr(amount)}"),
        amount=amount,
        currency=mat.get("currency") or "INR",
    )


def _production_order(p: dict) -> Draft:
    mat = query_one(
        "SELECT material_id, description, price, currency, unit FROM materials "
        "WHERE material_id = %s", (str(p.get("material_id", "")).upper(),))
    if not mat:
        return Draft("production_order",
                     blocking=[f"Material {p.get('material_id')} not found"])
    wc_id = str(p.get("work_center", "WC001")).upper()
    wc = query_one("SELECT wc_id, name, status FROM work_centers WHERE wc_id = %s", (wc_id,))
    if not wc:
        return Draft("production_order", blocking=[f"Work Center {wc_id} not found"])
    if wc["status"] == "MAINTENANCE":
        return Draft("production_order",
                     blocking=[f"Work Center {wc_id} is under maintenance"])

    qty = float(p.get("qty") or 0)
    amount = round(qty * float(mat["price"]), 2)
    return Draft(
        entity_type="production_order",
        measures={"amount": amount, "qty": qty},
        context={"material": mat["description"], "work_center_name": wc["name"],
                 "plant": p.get("plant", "1000"), "unit": mat["unit"]},
        summary=(f"Production order — {qty:g} {mat['unit']} of {mat['description']} "
                 f"at {wc['name']} (std value {mat['currency']} {inr(amount)})"),
        amount=amount,
        currency=mat.get("currency") or "INR",
    )


_LEAVE_COLUMNS = {
    "annual": ("annual_entitled", "annual_used"),
    "sick":   ("sick_entitled", "sick_used"),
    "casual": ("casual_entitled", "casual_used"),
}


def _leave(p: dict) -> Draft:
    emp = query_one(
        "SELECT emp_id, name FROM employees WHERE emp_id = %s AND status = 'ACTIVE'",
        (str(p.get("emp_id", "")).upper(),))
    if not emp:
        return Draft("leave", blocking=[f"Employee {p.get('emp_id')} not found or inactive"])

    lt = str(p.get("leave_type", "")).lower()
    if lt not in _LEAVE_COLUMNS:
        return Draft("leave", blocking=["Invalid leave type. Use: annual, sick, casual"])

    entitled_col, used_col = _LEAVE_COLUMNS[lt]
    lb = query_one(
        f"SELECT lb_id, {entitled_col}, {used_col} FROM leave_balances "
        f"WHERE emp_id = %s ORDER BY fiscal_year DESC LIMIT 1",
        (emp["emp_id"],))
    if not lb:
        return Draft("leave", blocking=[f"No leave balance record for {emp['emp_id']}"])

    balance = float(lb[entitled_col]) - float(lb[used_col])
    days = float(p.get("days") or 0)
    if days > balance:
        return Draft("leave", blocking=[
            f"Insufficient {lt} leave. Available: {balance} days, requested: {days}"])

    flags = ["exceeds_half_balance"] if balance and days > balance / 2 else []
    return Draft(
        entity_type="leave",
        measures={"days": days},
        context={"employee_name": emp["name"], "leave_type": lt,
                 "balance": balance, "remaining_after": balance - days},
        risk_flags=flags,
        summary=(f"Leave — {days:g} days {lt} for {emp['name']} "
                 f"({balance:g} available, {balance - days:g} after)"),
        amount=None,
    )


def _park_receipt(p: dict) -> Draft:
    cust = query_one(
        "SELECT name FROM re_customers WHERE customer_id = %s AND unit_number = %s",
        (str(p.get("customer_id", "")).upper(), str(p.get("unit_number", "")).upper()))
    if not cust:
        return Draft("receipt", blocking=[
            f"Customer {p.get('customer_id')} / unit {p.get('unit_number')} not found"])

    amount = float(p.get("amount") or 0)
    # Reuse the real allocation logic rather than reimplementing it; it is a
    # pure read and is the same code post-execution will run.
    from modules.receipt import calculate_receipt_allocation
    alloc = calculate_receipt_allocation(
        p.get("customer_id"), p.get("unit_number"), p.get("payment_mode"), amount)
    if alloc.get("status") == "ERROR":
        return Draft("receipt", blocking=[alloc.get("message", "Allocation failed")])
    if not alloc.get("posting_ready"):
        return Draft("receipt", blocking=["No outstanding items to allocate against"])

    flags = []
    if float(alloc.get("excess_basic") or 0) > 0:
        flags.append("excess_basic")
    if float(alloc.get("excess_tds") or 0) > 0:
        flags.append("excess_tds")

    return Draft(
        entity_type="receipt",
        measures={"amount": amount},
        context={"customer_name": cust["name"], "unit_number": p.get("unit_number"),
                 "payment_mode": p.get("payment_mode"),
                 "allocation": alloc.get("allocation", []),
                 "excess_basic": float(alloc.get("excess_basic") or 0),
                 "excess_tds": float(alloc.get("excess_tds") or 0)},
        risk_flags=flags,
        summary=(f"Park receipt — INR {inr(amount)} from {cust['name']} "
                 f"({p.get('payment_mode')}) against unit {p.get('unit_number')}"),
        amount=amount,
    )


def _post_receipt(p: dict) -> Draft:
    ref = str(p.get("park_reference", "")).upper()
    r = query_one(
        "SELECT park_ref, customer_id, unit_number, payment_mode, amount, status, "
        "excess_basic, excess_tds FROM customer_receipts WHERE park_ref = %s", (ref,))
    if not r:
        return Draft("receipt", blocking=[f"Park reference {ref} not found"])
    if r["status"] != "PARKED":
        return Draft("receipt", blocking=[f"Receipt {ref} is already {r['status']}"])

    amount = float(r["amount"])
    excess = float(r.get("excess_basic") or 0) + float(r.get("excess_tds") or 0)
    flags = ["large_excess"] if amount and excess > amount * 0.05 else []

    return Draft(
        entity_type="receipt",
        measures={"amount": amount},
        context={"park_reference": r["park_ref"], "customer_id": r["customer_id"],
                 "unit_number": r["unit_number"], "payment_mode": r["payment_mode"],
                 "excess_total": excess},
        risk_flags=flags,
        summary=(f"Post receipt {r['park_ref']} to FI — INR {inr(amount)} "
                 f"({r['payment_mode']}) for unit {r['unit_number']}"),
        amount=amount,
    )


def _broker_po(p: dict) -> Draft:
    b = query_one(
        """SELECT rbb.broker_id, rbb.unit_number, rbb.payout_amount, rbb.collected_pct,
                  rbb.po_status, rbb.sale_value, rb.name AS broker_name,
                  rc.name AS customer_name
           FROM re_broker_bookings rbb
           JOIN re_brokers rb ON rbb.broker_id = rb.broker_id
           JOIN re_customers rc ON rbb.customer_id = rc.customer_id
           WHERE rbb.broker_id = %s AND rbb.unit_number = %s""",
        (str(p.get("broker_id", "")).upper(), str(p.get("unit_number", "")).upper()))
    if not b:
        return Draft("broker_po", blocking=[
            f"Booking not found for broker {p.get('broker_id')} / unit {p.get('unit_number')}"])

    collected = float(b.get("collected_pct") or 0)
    if collected < 20.0:
        return Draft("broker_po", blocking=[
            f"Only {collected}% collected. Minimum 20% required before a broker PO."])
    if b["po_status"] != "NOT_CREATED":
        return Draft("broker_po", blocking=[f"PO already {b['po_status']} for this booking"])

    amount = float(b.get("payout_amount") or 0)
    flags = ["low_collection_margin"] if collected < 25.0 else []
    return Draft(
        entity_type="broker_po",
        measures={"amount": amount},
        context={"broker_name": b["broker_name"], "customer_name": b["customer_name"],
                 "unit_number": b["unit_number"], "collected_pct": collected,
                 "sale_value": float(b.get("sale_value") or 0)},
        risk_flags=flags,
        summary=(f"Broker PO — INR {inr(amount)} to {b['broker_name']} for unit "
                 f"{b['unit_number']} ({collected}% collected)"),
        amount=amount,
    )


_RESOLVERS = {
    "create_sales_order":      _sales_order,
    "create_production_order": _production_order,
    "apply_leave":             _leave,
    "park_customer_receipt":   _park_receipt,
    "post_customer_receipt":   _post_receipt,
    "initiate_broker_po":      _broker_po,
}


def resolve(action: str, parameters: dict) -> Draft | None:
    """Resolve a write into a judgeable draft. None when not a governed action.

    A resolver that raises is treated as unresolvable rather than allowed
    through: the caller sees blocking, and policy would in any case fall to the
    strictest tier on a missing measure.
    """
    fn = _RESOLVERS.get(action)
    if fn is None:
        return None
    try:
        return fn(parameters or {})
    except Exception as exc:
        _logger.exception("Resolver for %s failed", action)
        return Draft(entity_type=action,
                     blocking=[f"Could not validate this request: {exc}"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_approvals_resolvers.py -v`
Expected: PASS (15 tests)

- [ ] **Step 5: Commit**

```bash
git add core/approvals/resolvers.py tests/test_approvals_resolvers.py
git commit -m "feat(approvals): resolve amount and risk from SAP before the write"
```

---
### Task 5: Event dispatcher, execution-context accessors, and the gate

`events.py` exists so Phase 1 does not have to import a module Phase 2 has not
written yet. It always writes the audit row, and calls any sink registered with
it — the webhook emitter registers itself in Task 8, from `api/server.py`
startup, explicitly rather than as an import side effect.

**Files:**
- Create: `core/approvals/events.py`
- Create: `core/approvals/gate.py`
- Modify: `core/authorization.py` (add `_roles` context var and three public accessors; `execution_context` gains `roles`)
- Test: `tests/test_approvals_gate.py`

**Interfaces:**
- Consumes: `core.approvals.store`, `policy`, `resolvers`; `core.authorization.current_actor/current_roles/enforcement_on`
- Produces:
  - `events.emit(event: str, row: dict, *, actor=None, comment=None, payload_before=None, payload_after=None, idempotency_key=None) -> bool`
  - `events.register_sink(fn) -> None`, `events.clear_sinks() -> None`
  - `gate.bypass()` — context manager setting the executor bypass
  - `gate.intercept(tool_name: str, parameters: dict) -> dict | None`
  - `gate.record_auto(tool_name: str, parameters: dict, result: dict) -> None`
  - `gate.preview(tool_name: str, parameters: dict) -> dict | None`
  - `gate.DOC_FIELDS: dict[str, str]`, `gate.extract_doc_number(action, result) -> tuple[str | None, str | None]`
  - `authorization.current_actor() -> str | None`, `current_roles() -> list[str]`, `enforcement_on() -> bool`

- [ ] **Step 1: Write the failing test**

```python
"""Gate tests — the security boundary. If any of these regress, a write can
reach SAP without a signature."""
import unittest
from unittest.mock import patch

import core.authorization as authz

SALES_PARAMS = {"customer_id": "C001", "material_id": "M001", "qty": 100}


def _draft(amount=420000.0, flags=(), blocking=()):
    from core.approvals.resolvers import Draft
    return Draft(entity_type="sales_order", measures={"amount": amount},
                 context={"customer_name": "Acme"}, risk_flags=list(flags),
                 blocking=list(blocking), summary="Sales order for Acme",
                 amount=amount, currency="INR")


class TestGateScope(unittest.TestCase):

    def test_read_tools_pass_straight_through(self):
        from core.approvals import gate
        with authz.execution_context(user_id="ravi", roles=["sd_analyst"], enforce=True):
            self.assertIsNone(gate.intercept("get_customer_info", {"customer_id": "C001"}))

    def test_enforcement_off_passes_through(self):
        # CLI and library callers have no user; they must not be blocked.
        from core.approvals import gate
        self.assertIsNone(gate.intercept("create_sales_order", SALES_PARAMS))

    def test_executor_bypass_passes_through(self):
        from core.approvals import gate
        with authz.execution_context(user_id="ravi", roles=["sd_analyst"], enforce=True):
            with gate.bypass():
                self.assertIsNone(gate.intercept("create_sales_order", SALES_PARAMS))


class TestGateDecisions(unittest.TestCase):

    def test_blocking_returns_error_and_writes_no_row(self):
        from core.approvals import gate
        with patch("core.approvals.gate.resolvers.resolve",
                   return_value=_draft(blocking=["Customer NOPE not found"])), \
             patch("core.approvals.gate.store.create_request") as create:
            with authz.execution_context(user_id="ravi", roles=["sd_analyst"], enforce=True):
                out = gate.intercept("create_sales_order", SALES_PARAMS)
        self.assertEqual("ERROR", out["status"])
        self.assertIn("NOPE", out["message"])
        create.assert_not_called()

    def test_auto_tier_returns_none_so_the_write_runs_inline(self):
        from core.approvals import gate
        with patch("core.approvals.gate.resolvers.resolve", return_value=_draft(amount=1000)):
            with authz.execution_context(user_id="ravi", roles=["sd_analyst"], enforce=True):
                self.assertIsNone(gate.intercept("create_sales_order", SALES_PARAMS))

    def test_pending_tier_creates_a_row_and_blocks_the_write(self):
        from core.approvals import gate
        row = {"request_id": "apr_1", "action": "create_sales_order", "status": "pending",
               "approver_role": "sales_manager", "summary": "Sales order for Acme",
               "amount": 420000.0, "currency": "INR", "risk_flags": [],
               "entity_type": "sales_order",
               "approval_chain": [{"role": "sales_manager", "sla_hours": 8}]}
        with patch("core.approvals.gate.resolvers.resolve", return_value=_draft()), \
             patch("core.approvals.gate.store.create_request", return_value=row) as create, \
             patch("core.approvals.gate.events.emit"):
            with authz.execution_context(user_id="ravi", roles=["sd_analyst"], enforce=True):
                out = gate.intercept("create_sales_order", SALES_PARAMS)
        self.assertEqual("APPROVAL_REQUIRED", out["status"])
        self.assertEqual("apr_1", out["request_id"])
        self.assertEqual("sales_manager", out["approval"]["approver_role"])
        self.assertEqual("pending", create.call_args.kwargs["status"])
        self.assertEqual("ravi", create.call_args.kwargs["requested_by"])

    def test_requester_identity_comes_from_the_context_not_the_payload(self):
        # A caller must not be able to name themselves in the parameters.
        from core.approvals import gate
        row = {"request_id": "apr_1", "status": "pending", "approver_role": "sales_manager",
               "summary": "", "amount": 1.0, "currency": "INR", "risk_flags": [],
               "action": "create_sales_order", "entity_type": "sales_order",
               "approval_chain": []}
        with patch("core.approvals.gate.resolvers.resolve", return_value=_draft()), \
             patch("core.approvals.gate.store.create_request", return_value=row) as create, \
             patch("core.approvals.gate.events.emit"):
            with authz.execution_context(user_id="ravi", roles=["sd_analyst"], enforce=True):
                gate.intercept("create_sales_order",
                               {**SALES_PARAMS, "requested_by": "someone_else"})
        self.assertEqual("ravi", create.call_args.kwargs["requested_by"])


class TestRecordAuto(unittest.TestCase):

    def test_successful_auto_write_is_recorded_as_executed(self):
        from core.approvals import gate
        with patch("core.approvals.gate.resolvers.resolve", return_value=_draft(amount=1000)):
            with authz.execution_context(user_id="ravi", roles=["sd_analyst"], enforce=True):
                gate.intercept("create_sales_order", SALES_PARAMS)
                with patch("core.approvals.gate.store.create_request",
                           return_value={"request_id": "apr_a"}) as create, \
                     patch("core.approvals.gate.events.emit"):
                    gate.record_auto("create_sales_order", SALES_PARAMS,
                                     {"status": "OK", "order_id": "SO123456"})
        self.assertEqual("executed", create.call_args.kwargs["status"])
        self.assertEqual("SO123456", create.call_args.kwargs["sap_doc_number"])
        self.assertEqual("order_id", create.call_args.kwargs["sap_doc_field"])

    def test_failed_auto_write_records_nothing(self):
        from core.approvals import gate
        with patch("core.approvals.gate.resolvers.resolve", return_value=_draft(amount=1000)):
            with authz.execution_context(user_id="ravi", roles=["sd_analyst"], enforce=True):
                gate.intercept("create_sales_order", SALES_PARAMS)
                with patch("core.approvals.gate.store.create_request") as create:
                    gate.record_auto("create_sales_order", SALES_PARAMS,
                                     {"status": "ERROR", "message": "nope"})
        create.assert_not_called()

    def test_record_auto_without_a_preceding_intercept_is_a_no_op(self):
        from core.approvals import gate
        with patch("core.approvals.gate.store.create_request") as create:
            gate.record_auto("create_sales_order", SALES_PARAMS,
                             {"status": "OK", "order_id": "SO1"})
        create.assert_not_called()


class TestDocumentNumberExtraction(unittest.TestCase):

    def test_every_write_tool_has_a_document_field(self):
        from core.approvals import gate
        from core.authorization import WRITE_TOOLS
        for tool in WRITE_TOOLS:
            self.assertIn(tool, gate.DOC_FIELDS)

    def test_extraction_per_action(self):
        from core.approvals.gate import extract_doc_number
        cases = [
            ("create_sales_order",      {"order_id": "SO1"},            ("SO1", "order_id")),
            ("create_production_order", {"order_id": "PRD1"},           ("PRD1", "order_id")),
            ("apply_leave",             {"application_id": "LA1"},      ("LA1", "application_id")),
            ("park_customer_receipt",   {"park_reference": "PRK1"},     ("PRK1", "park_reference")),
            ("post_customer_receipt",   {"fi_doc_no": "18000001"},      ("18000001", "fi_doc_no")),
            ("initiate_broker_po",      {"po_number": "4500000001"},    ("4500000001", "po_number")),
        ]
        for action, result, expected in cases:
            self.assertEqual(expected, extract_doc_number(action, result), action)


class TestPreview(unittest.TestCase):

    def test_preview_reports_amount_and_routing_without_writing(self):
        from core.approvals import gate
        with patch("core.approvals.gate.resolvers.resolve", return_value=_draft()), \
             patch("core.approvals.gate.store.create_request") as create:
            out = gate.preview("create_sales_order", SALES_PARAMS)
        self.assertEqual(420000.0, out["amount"])
        self.assertEqual(["sales_manager"], out["would_route_to"])
        self.assertFalse(out["auto"])
        create.assert_not_called()


class TestEventSinks(unittest.TestCase):

    def tearDown(self):
        from core.approvals import events
        events.clear_sinks()

    def test_a_failing_sink_does_not_break_the_decision(self):
        # A dead webhook receiver must never block an approval.
        from core.approvals import events
        events.register_sink(lambda event, row: (_ for _ in ()).throw(RuntimeError("down")))
        with patch("core.approvals.events.store.add_event", return_value=True):
            self.assertTrue(events.emit("approval.requested", {"request_id": "apr_1"}))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_approvals_gate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.approvals.gate'`

- [ ] **Step 3: Add the accessors to `core/authorization.py`**

After the existing `_enforce` context var declaration (around line 145), add:

```python
_roles: contextvars.ContextVar[list | None] = contextvars.ContextVar(
    "authz_roles", default=None)


def current_actor() -> str | None:
    """The user bound by execution_context, if any."""
    return _actor.get()


def current_roles() -> list[str]:
    """Roles bound by execution_context. Empty when none were bound."""
    return list(_roles.get() or [])


def enforcement_on() -> bool:
    """True when the caller entered an enforcing execution_context."""
    return _enforce.get()
```

Then extend `execution_context` to bind roles as well (replacing the existing
`__init__`, `__enter__` and `__exit__`):

```python
    def __init__(self, *, user_id: str | None,
                 confirm_token: str | None = None, enforce: bool = True,
                 roles: list[str] | None = None):
        self._user, self._token, self._on = user_id, confirm_token, enforce
        self._roles = roles

    def __enter__(self):
        self._t = (_actor.set(self._user), _confirm.set(self._token),
                   _enforce.set(self._on), _roles.set(self._roles))
        return self

    def __exit__(self, *exc):
        _actor.reset(self._t[0]); _confirm.reset(self._t[1])
        _enforce.reset(self._t[2]); _roles.reset(self._t[3])
        return False
```

`roles` is keyword-only with a default, so every existing call site keeps working.

- [ ] **Step 4: Write `core/approvals/events.py`**

```python
"""
One place where an approval state change is recorded.

Always writes the audit row. Sinks (the webhook emitter) are registered
explicitly at server startup rather than by import side effect, so importing
this module never opens a socket and tests never need to unpick one.

A sink that raises is logged and swallowed: a webhook receiver being down must
never block an approval decision or roll back an audit row.
"""
from __future__ import annotations

import logging
from typing import Callable

from core.approvals import store

_logger = logging.getLogger("core.approvals.events")

_SINKS: list[Callable[[str, dict], None]] = []


def register_sink(fn: Callable[[str, dict], None]) -> None:
    if fn not in _SINKS:
        _SINKS.append(fn)


def clear_sinks() -> None:
    _SINKS.clear()


def emit(event: str, row: dict, *, actor: str | None = None,
         comment: str | None = None, payload_before: dict | None = None,
         payload_after: dict | None = None,
         idempotency_key: str | None = None) -> bool:
    """Record a state change. False means this event was already recorded."""
    request_id = row.get("request_id")
    fresh = True
    if request_id:
        try:
            fresh = store.add_event(
                request_id, event=event, actor=actor, comment=comment,
                payload_before=payload_before, payload_after=payload_after,
                idempotency_key=idempotency_key)
        except Exception:
            _logger.exception("Failed to write approval event %s for %s", event, request_id)
    if not fresh:
        return False
    for sink in list(_SINKS):
        try:
            sink(event, row)
        except Exception:
            _logger.warning("Approval event sink failed for %s", event, exc_info=True)
    return True
```

- [ ] **Step 5: Write `core/approvals/gate.py`**

```python
"""
The interception point. Called from tools/tool_registry.execute_tool(), which
is the one path every caller shares — /chat, /chat/stream, MCP, the report
agent, auto-research.

Sitting here rather than in the API layer is deliberate and load-bearing: the
MCP tool handler at api/server.py:2065 calls execute_tool() directly, so a gate
in a route handler would leave it wide open. Sitting below the model is equally
deliberate — no prompt, however persuasive or injected, can route around code
the model does not execute.

Three ways out, in order:
  * not governed / not enforcing / executor bypass  -> None, proceed
  * resolver reported a blocking condition          -> ERROR, no row written
  * policy says auto                                -> None, proceed, then
                                                       record_auto() files the
                                                       audit row
  * otherwise                                       -> APPROVAL_REQUIRED
"""
from __future__ import annotations

import contextlib
import contextvars
import logging

from core import authorization
from core.approvals import events, policy, resolvers, store

_logger = logging.getLogger("core.approvals.gate")

# Set only inside executor.execute(); never reachable from a request handler.
_executing: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "approvals_executing", default=False)

# Carries an auto-tier draft from intercept() to record_auto() within one call.
_auto: contextvars.ContextVar[tuple | None] = contextvars.ContextVar(
    "approvals_auto_draft", default=None)

#: Where each action puts its SAP document number. These differ per tool and
#: the executor cannot guess: sales and production orders both use order_id,
#: leave uses application_id, parking uses park_reference, posting uses
#: fi_doc_no, and a broker PO uses po_number.
DOC_FIELDS: dict[str, str] = {
    "create_sales_order":      "order_id",
    "create_production_order": "order_id",
    "apply_leave":             "application_id",
    "park_customer_receipt":   "park_reference",
    "post_customer_receipt":   "fi_doc_no",
    "initiate_broker_po":      "po_number",
}


def extract_doc_number(action: str, result: dict) -> tuple[str | None, str | None]:
    """(document number, field it came from) for a successful write."""
    field = DOC_FIELDS.get(action)
    if not field or not isinstance(result, dict):
        return None, None
    value = result.get(field)
    return (str(value) if value is not None else None), field


@contextlib.contextmanager
def bypass():
    """Stand the gate down for the executor's own call into execute_tool()."""
    token = _executing.set(True)
    try:
        yield
    finally:
        _executing.reset(token)


def _decide(tool_name: str, parameters: dict):
    """(draft, decision) or (draft, None) when not governed."""
    draft = resolvers.resolve(tool_name, parameters)
    if draft is None:
        return None, None
    if draft.blocking:
        return draft, None
    return draft, policy.evaluate(tool_name, draft.measures, draft.risk_flags)


def preview(tool_name: str, parameters: dict) -> dict | None:
    """What the confirmation prompt shows: the money, and who will have to sign.

    Read-only. Writes nothing, so it is safe to call on every confirmation.
    """
    if not policy.is_governed(tool_name):
        return None
    draft, decision = _decide(tool_name, parameters)
    if draft is None:
        return None
    if draft.blocking:
        return {"blocking": list(draft.blocking)}
    return {
        "summary":         draft.summary,
        "amount":          draft.amount,
        "currency":        draft.currency,
        "risk_flags":      list(draft.risk_flags),
        "auto":            bool(decision and decision.auto),
        "would_route_to":  [e.role for e in decision.chain] if decision else [],
    }


def intercept(tool_name: str, parameters: dict) -> dict | None:
    """None means "carry on and execute". A dict is the caller's answer."""
    if _executing.get():
        return None
    if not policy.is_governed(tool_name):
        return None
    if not authorization.enforcement_on():
        return None

    draft, decision = _decide(tool_name, parameters)
    if draft is None:
        return None
    if draft.blocking:
        return {"status": "ERROR", "message": "; ".join(draft.blocking)}
    if decision is None:
        return None

    if decision.auto:
        _auto.set((tool_name, parameters, draft, decision))
        return None

    _auto.set(None)
    # Identity comes from the execution context, never from the payload.
    requested_by = authorization.current_actor() or "unknown"
    row = store.create_request(
        action=tool_name,
        entity_type=decision.entity_type,
        payload=parameters,
        context=draft.context,
        measures=draft.measures,
        amount=draft.amount,
        currency=draft.currency,
        summary=draft.summary,
        risk_flags=list(draft.risk_flags),
        requested_by=requested_by,
        requester_roles=authorization.current_roles(),
        approval_chain=policy.chain_as_dicts(decision.chain),
        status="pending",
        hard_ttl_hours=policy.hard_ttl_hours(),
    )
    if row is None:
        _logger.error("Could not persist approval request for %s", tool_name)
        return {"status": "ERROR",
                "message": "This action needs approval, but the approval request "
                           "could not be saved. Nothing was written to SAP."}

    events.emit("approval.requested", row, actor=requested_by)
    roles = [e.role for e in decision.chain]
    return {
        "status": "APPROVAL_REQUIRED",
        "message": (f"Submitted for approval as {row['request_id']}. "
                    f"Waiting on {roles[0]}. Nothing has been written to SAP yet."),
        "request_id": row["request_id"],
        "approval": {
            "request_id":    row["request_id"],
            "action":        tool_name,
            "entity_type":   decision.entity_type,
            "summary":       draft.summary,
            "amount":        draft.amount,
            "currency":      draft.currency,
            "risk_flags":    list(draft.risk_flags),
            "approver_role": roles[0],
            "chain":         roles,
            "status":        "pending",
        },
    }


def record_auto(tool_name: str, parameters: dict, result: dict) -> None:
    """File the audit row for a write that policy let through automatically.

    The auto tier does not go through the executor — the write already ran
    inline, so the chat can show the SAP document immediately — but every write
    still belongs in the trail.
    """
    stashed = _auto.get()
    if not stashed:
        return
    _auto.set(None)
    action, _params, draft, decision = stashed
    if action != tool_name:
        return
    if not isinstance(result, dict) or result.get("status") != "OK":
        return

    doc_number, doc_field = extract_doc_number(tool_name, result)
    try:
        row = store.create_request(
            action=tool_name,
            entity_type=decision.entity_type,
            payload=parameters,
            context=draft.context,
            measures=draft.measures,
            amount=draft.amount,
            currency=draft.currency,
            summary=draft.summary,
            risk_flags=list(draft.risk_flags),
            requested_by=authorization.current_actor() or "unknown",
            requester_roles=authorization.current_roles(),
            approval_chain=[],
            status="executed",
            sap_doc_number=doc_number,
            sap_doc_field=doc_field,
        )
        if row:
            events.emit("approval.executed", row)
    except Exception:
        # The SAP write already succeeded. Losing its audit row is bad, but
        # raising here would report a failure for something that happened.
        _logger.exception("Failed to record auto-approved %s", tool_name)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_approvals_gate.py -v`
Expected: PASS (14 tests)

- [ ] **Step 7: Run the full suite to check nothing regressed**

Run: `python -m pytest tests/ -q`
Expected: no new failures (`execution_context` gained a keyword-only argument with a default, so existing call sites are unaffected).

- [ ] **Step 8: Commit**

```bash
git add core/approvals/events.py core/approvals/gate.py core/authorization.py tests/test_approvals_gate.py
git commit -m "feat(approvals): gate below the model, with event dispatch and auto-tier recording"
```

---
### Task 6: Wire the gate into `execute_tool()` and the two chat paths

After this task the layer is live: every write from every caller is resolved,
evaluated and either executed or queued.

**Files:**
- Modify: `tools/tool_registry.py:791-816` (`execute_tool`)
- Modify: `core/authorization.py` (`confirmation_required` gains `draft`, and blocks the impossible)
- Modify: `api/server.py:950` (chat binds roles), `:1117-1120` and `:1349-1351` (stream binds and resets roles), `:1052-1078` (surface `APPROVAL_REQUIRED`)
- Test: `tests/test_approvals_wiring.py`

**Interfaces:**
- Consumes: `gate.intercept`, `gate.record_auto`, `gate.preview`
- Produces: `execute_tool` may now return `{"status": "APPROVAL_REQUIRED", ...}`; `confirmation_required` payloads may carry `draft`

- [ ] **Step 1: Write the failing test**

```python
"""The wiring, end to end through execute_tool. These are the tests that prove
no caller can reach a write without passing the gate.

Note the patch target: tool_registry.FUNCTION_MAP captured direct references to
the module functions at import time, so patching modules.sd.create_sales_order
would leave FUNCTION_MAP pointing at the real one and the test would pass while
writing to the database. Patch the dict entry."""
import unittest
from unittest.mock import MagicMock, patch

import core.authorization as authz

SALES_PARAMS = {"customer_id": "C001", "material_id": "M001", "qty": 100}


def _draft(amount=420000.0, blocking=()):
    from core.approvals.resolvers import Draft
    return Draft(entity_type="sales_order", measures={"amount": amount},
                 context={}, risk_flags=[], blocking=list(blocking),
                 summary="Sales order for Acme", amount=amount, currency="INR")


class TestExecuteToolGating(unittest.TestCase):

    def test_unconfirmed_write_still_asks_for_confirmation(self):
        from tools.tool_registry import execute_tool
        with patch("core.approvals.gate.resolvers.resolve", return_value=_draft()):
            with authz.execution_context(user_id="ravi", roles=["sd_analyst"], enforce=True):
                out = execute_tool("create_sales_order", SALES_PARAMS)
        self.assertEqual("CONFIRMATION_REQUIRED", out["status"])

    def test_confirmation_payload_carries_the_resolved_amount_and_routing(self):
        # The requester sees the money and who will sign BEFORE confirming.
        from tools.tool_registry import execute_tool
        with patch("core.approvals.gate.resolvers.resolve", return_value=_draft()):
            with authz.execution_context(user_id="ravi", roles=["sd_analyst"], enforce=True):
                out = execute_tool("create_sales_order", SALES_PARAMS)
        self.assertEqual(420000.0, out["draft"]["amount"])
        self.assertEqual(["sales_manager"], out["draft"]["would_route_to"])

    def test_confirmed_write_over_threshold_is_queued_not_executed(self):
        from tools.tool_registry import execute_tool
        from core.authorization import issue_token
        sap_stub = MagicMock()
        token, _ = issue_token("ravi", "create_sales_order", SALES_PARAMS)
        row = {"request_id": "apr_1", "status": "pending", "approver_role": "sales_manager",
               "action": "create_sales_order", "entity_type": "sales_order",
               "summary": "s", "amount": 420000.0, "currency": "INR", "risk_flags": [],
               "approval_chain": [{"role": "sales_manager", "sla_hours": 8}]}
        with patch("core.approvals.gate.resolvers.resolve", return_value=_draft()), \
             patch("core.approvals.gate.store.create_request", return_value=row), \
             patch("core.approvals.gate.events.emit"), \
             patch.dict("tools.tool_registry.FUNCTION_MAP",
                        {"create_sales_order": sap_stub}):
            with authz.execution_context(user_id="ravi", roles=["sd_analyst"],
                                         confirm_token=token, enforce=True):
                out = execute_tool("create_sales_order", SALES_PARAMS)
        self.assertEqual("APPROVAL_REQUIRED", out["status"])
        sap_stub.assert_not_called()     # nothing reached SAP

    def test_confirmed_write_under_threshold_executes_and_is_recorded(self):
        from tools.tool_registry import execute_tool
        from core.authorization import issue_token
        sap_stub = MagicMock(return_value={"status": "OK", "order_id": "SO123456"})
        token, _ = issue_token("ravi", "create_sales_order", SALES_PARAMS)
        with patch("core.approvals.gate.resolvers.resolve", return_value=_draft(amount=1000)), \
             patch("core.approvals.gate.store.create_request",
                   return_value={"request_id": "apr_a"}) as create, \
             patch("core.approvals.gate.events.emit"), \
             patch.dict("tools.tool_registry.FUNCTION_MAP",
                        {"create_sales_order": sap_stub}):
            with authz.execution_context(user_id="ravi", roles=["sd_analyst"],
                                         confirm_token=token, enforce=True):
                out = execute_tool("create_sales_order", SALES_PARAMS)
        self.assertEqual("OK", out["status"])
        sap_stub.assert_called_once()
        self.assertEqual("executed", create.call_args.kwargs["status"])

    def test_blocking_condition_short_circuits_before_confirmation(self):
        # Never ask a user to confirm something that cannot execute.
        from tools.tool_registry import execute_tool
        with patch("core.approvals.gate.resolvers.resolve",
                   return_value=_draft(blocking=["Customer NOPE not found"])):
            with authz.execution_context(user_id="ravi", roles=["sd_analyst"], enforce=True):
                out = execute_tool("create_sales_order", SALES_PARAMS)
        self.assertEqual("ERROR", out["status"])
        self.assertIn("NOPE", out["message"])

    def test_reads_are_untouched(self):
        from tools.tool_registry import execute_tool
        read = MagicMock(return_value={"status": "OK", "name": "Acme"})
        with patch.dict("tools.tool_registry.FUNCTION_MAP", {"get_customer_info": read}):
            with authz.execution_context(user_id="ravi", roles=["sd_analyst"], enforce=True):
                out = execute_tool("get_customer_info", {"customer_id": "C001"})
        self.assertEqual("OK", out["status"])
        read.assert_called_once()


class TestChatSurfacesApproval(unittest.TestCase):

    def test_chat_returns_the_approval_message_and_payload(self):
        from fastapi.testclient import TestClient
        from api import server as server_module

        app = server_module.app
        app.dependency_overrides[server_module.get_current_user] = lambda: {
            "user_id": "ravi", "roles": ["sd_analyst"]}
        approval = {
            "status": "APPROVAL_REQUIRED",
            "message": "Submitted for approval as apr_1. Waiting on sales_manager.",
            "request_id": "apr_1",
            "approval": {"request_id": "apr_1", "approver_role": "sales_manager"},
        }
        # Model resolution is pinned too: without it this test 503s on any
        # machine that has no AI provider configured.
        with patch.object(server_module, "_resolve_chat_model_or_503"), \
             patch("agent.sap_agent.SAPAgent.chat",
                   return_value=("ok", "create_sales_order", approval)):
            resp = TestClient(app).post("/chat", json={"message": "create an order"})
        body = resp.json()
        self.assertEqual(200, resp.status_code)
        self.assertIn("apr_1", body["response"])
        self.assertEqual("APPROVAL_REQUIRED", body["tool_result"]["status"])


def tearDownModule():
    from api import server as server_module
    server_module.app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_approvals_wiring.py -v`
Expected: FAIL — `KeyError: 'draft'` and `AssertionError: 'OK' != 'APPROVAL_REQUIRED'`

- [ ] **Step 3: Enrich `confirmation_required()` in `core/authorization.py`**

Replace the body after the `verify_token` early return:

```python
    if verify_token(_confirm.get(), user, tool_name, parameters):
        return None

    # The draft answers "how much, and who will have to sign" before the user
    # commits — and short-circuits a request that cannot possibly execute, so
    # nobody confirms a sales order for a customer that does not exist.
    #
    # Imported lazily: core.approvals.gate imports this module at module level.
    draft = None
    try:
        from core.approvals.gate import preview
        draft = preview(tool_name, parameters)
    except Exception:  # pragma: no cover - approvals must never break a write path
        draft = None
    if draft and draft.get("blocking"):
        return {"status": "ERROR", "message": "; ".join(draft["blocking"])}

    token, expires = issue_token(user, tool_name, parameters)
    payload = {
        "status": "CONFIRMATION_REQUIRED",
        "message": (f"'{tool_name}' changes SAP data and needs explicit confirmation. "
                    f"Re-send with confirm_token to execute."),
        "pending_action": {
            "tool":       tool_name,
            "operation":  WRITE,
            "parameters": parameters,
            "requested_by": user,
        },
        "confirm_token": token,
        "expires_at":    expires,
    }
    if draft:
        payload["draft"] = draft
        if not draft.get("auto") and draft.get("would_route_to"):
            payload["message"] = (
                f"'{tool_name}' will be submitted for approval to "
                f"{draft['would_route_to'][0]}. Re-send with confirm_token to submit.")
    return payload
```

Update the function's docstring to say it may also return an `ERROR` payload when the action cannot execute at all.

- [ ] **Step 4: Wire the gate into `execute_tool()` in `tools/tool_registry.py`**

Replace the body of `execute_tool` from the confirmation block onwards:

```python
    # Destructive actions stop here unless explicitly confirmed. This is the one
    # choke point every caller shares — chat, streaming, reports, MCP, research —
    # so the control cannot be routed around (finding F-03).
    from core.authorization import confirmation_required
    pending = confirmation_required(tool_name, parameters)
    if pending:
        return pending

    # Confirmed writes then face the approval policy. Same reasoning as above:
    # gating here rather than in a route handler is what keeps the MCP path
    # from bypassing it.
    from core.approvals.gate import intercept, record_auto
    gated = intercept(tool_name, parameters)
    if gated:
        return gated

    try:
        result = func(**parameters)
        # Inject SAP source attribution into every successful result
        src = get_sap_source(tool_name)
        if src and isinstance(result, dict):
            result["sap_source"] = src
        # Auto-approved writes ran inline; file their audit row. No-op for
        # reads, for pending requests, and for the executor's own calls.
        record_auto(tool_name, parameters, result)
        return result
    except Exception as e:
        return {"status": "ERROR", "message": f"Tool execution error: {str(e)}"}
```

- [ ] **Step 5: Bind roles on the chat path in `api/server.py`**

At line 950, add `roles=user_roles`:

```python
        with execution_context(user_id=user_id, confirm_token=body.confirm_token,
                               roles=user_roles, enforce=_AUTH_ENABLED):
```

- [ ] **Step 6: Bind and reset roles on the streaming path in `api/server.py`**

At line 1117, import and set `_roles`:

```python
    from core.authorization import _actor, _confirm, _enforce, _roles
    _authz_tokens = (_actor.set(user_id),
                     _confirm.set(body.confirm_token),
                     _enforce.set(_AUTH_ENABLED),
                     _roles.set(user_roles))
```

At line 1349, reset it too:

```python
                _actor.reset(_authz_tokens[0])
                _confirm.reset(_authz_tokens[1])
                _enforce.reset(_authz_tokens[2])
                _roles.reset(_authz_tokens[3])
```

- [ ] **Step 7: Surface `APPROVAL_REQUIRED` on the chat path in `api/server.py`**

Immediately after the existing `CONFIRMATION_REQUIRED` block at line 1052-1058, add:

```python
    # A queued write is neither an error nor a completed result. The payload
    # stays in tool_result so both /chat and /chat/stream present the same
    # shape to the frontend; only the text is replaced.
    approval_pending = False
    if isinstance(tool_result, dict) and tool_result.get("status") == "APPROVAL_REQUIRED":
        approval_pending = True
        response_text = tool_result.get("message") or response_text
```

Then extend the cache guard at line 1076 so a queued write is never cached:

```python
    if (err_status == "ok" and not body.clarification_answer
            and not pending_action and not approval_pending):
```

- [ ] **Step 8: Run tests**

Run: `python -m pytest tests/test_approvals_wiring.py -v`
Expected: PASS (7 tests)

Run: `python -m pytest tests/ -q`
Expected: no new failures. `tests/qa_master.py` and `tests/rbac_matrix.py` assert `CONFIRMATION_REQUIRED` — that status is unchanged, and the new `draft` key is additive.

- [ ] **Step 9: Commit**

```bash
git add tools/tool_registry.py core/authorization.py api/server.py tests/test_approvals_wiring.py
git commit -m "feat(approvals): route every confirmed write through the policy gate"
```

---

### Task 7: Executor

**Files:**
- Create: `core/approvals/executor.py`
- Test: `tests/test_approvals_executor.py`

**Interfaces:**
- Consumes: `store.claim_for_execution`, `store.mark_executed`, `store.mark_failed`, `gate.bypass`, `gate.extract_doc_number`, `resolvers.resolve`, `policy.amount_tolerance_pct`, `tools.tool_registry.execute_tool`
- Produces: `execute(request_id: str) -> dict | None` — the final row, or None if the claim failed

- [ ] **Step 1: Write the failing test**

```python
"""Executor tests. The claim test and the revalidation test are the two that
protect real money."""
import unittest
from unittest.mock import patch


def _row(**over):
    base = {
        "request_id": "apr_1", "action": "create_sales_order",
        "entity_type": "sales_order", "status": "executing",
        "payload": {"customer_id": "C001", "material_id": "M001", "qty": 100},
        "measures": {"amount": 420000.0}, "amount": 420000.0, "currency": "INR",
        "requested_by": "ravi",
    }
    base.update(over)
    return base


def _draft(amount=420000.0, blocking=()):
    from core.approvals.resolvers import Draft
    return Draft(entity_type="sales_order", measures={"amount": amount},
                 context={}, risk_flags=[], blocking=list(blocking),
                 summary="s", amount=amount, currency="INR")


class TestClaim(unittest.TestCase):

    def test_a_lost_claim_executes_nothing(self):
        # Two workers, one approved request: exactly one write must happen.
        from core.approvals import executor
        with patch("core.approvals.executor.store.claim_for_execution", return_value=None), \
             patch("core.approvals.executor.execute_tool") as sap:
            out = executor.execute("apr_1")
        self.assertIsNone(out)
        sap.assert_not_called()


class TestRevalidation(unittest.TestCase):

    def test_drifted_amount_fails_instead_of_executing(self):
        # The order was approved at 4,20,000. The price moved. Nobody signed
        # for the new number, so it must not execute.
        from core.approvals import executor
        with patch("core.approvals.executor.store.claim_for_execution", return_value=_row()), \
             patch("core.approvals.executor.resolvers.resolve", return_value=_draft(amount=480000.0)), \
             patch("core.approvals.executor.store.mark_failed") as failed, \
             patch("core.approvals.executor.events.emit"), \
             patch("core.approvals.executor.execute_tool") as sap:
            executor.execute("apr_1")
        sap.assert_not_called()
        self.assertIn("revalidation", failed.call_args.kwargs["error"].lower())

    def test_new_blocking_condition_fails_instead_of_executing(self):
        from core.approvals import executor
        with patch("core.approvals.executor.store.claim_for_execution", return_value=_row()), \
             patch("core.approvals.executor.resolvers.resolve",
                   return_value=_draft(blocking=["Receipt already POSTED"])), \
             patch("core.approvals.executor.store.mark_failed") as failed, \
             patch("core.approvals.executor.events.emit"), \
             patch("core.approvals.executor.execute_tool") as sap:
            executor.execute("apr_1")
        sap.assert_not_called()
        self.assertIn("POSTED", failed.call_args.kwargs["error"])

    def test_unchanged_amount_proceeds(self):
        from core.approvals import executor
        with patch("core.approvals.executor.store.claim_for_execution", return_value=_row()), \
             patch("core.approvals.executor.resolvers.resolve", return_value=_draft()), \
             patch("core.approvals.executor.store.mark_executed") as done, \
             patch("core.approvals.executor.store.get_request", return_value=_row(status="executed")), \
             patch("core.approvals.executor.events.emit"), \
             patch("core.approvals.executor.execute_tool",
                   return_value={"status": "OK", "order_id": "SO999999"}):
            executor.execute("apr_1")
        self.assertEqual("SO999999", done.call_args.kwargs["sap_doc_number"])
        self.assertEqual("order_id", done.call_args.kwargs["sap_doc_field"])


class TestFailureIsNotSuccess(unittest.TestCase):

    def test_error_return_value_is_recorded_as_failed(self):
        # Write functions signal failure by return value, not exception.
        from core.approvals import executor
        with patch("core.approvals.executor.store.claim_for_execution", return_value=_row()), \
             patch("core.approvals.executor.resolvers.resolve", return_value=_draft()), \
             patch("core.approvals.executor.store.mark_failed") as failed, \
             patch("core.approvals.executor.store.mark_executed") as done, \
             patch("core.approvals.executor.events.emit"), \
             patch("core.approvals.executor.execute_tool",
                   return_value={"status": "ERROR", "message": "Customer inactive"}):
            executor.execute("apr_1")
        done.assert_not_called()
        self.assertIn("Customer inactive", failed.call_args.kwargs["error"])

    def test_an_exception_is_recorded_as_failed(self):
        from core.approvals import executor
        with patch("core.approvals.executor.store.claim_for_execution", return_value=_row()), \
             patch("core.approvals.executor.resolvers.resolve", return_value=_draft()), \
             patch("core.approvals.executor.store.mark_failed") as failed, \
             patch("core.approvals.executor.events.emit"), \
             patch("core.approvals.executor.execute_tool", side_effect=RuntimeError("boom")):
            executor.execute("apr_1")
        self.assertIn("boom", failed.call_args.kwargs["error"])


class TestBypass(unittest.TestCase):

    def test_the_gate_is_stood_down_during_execution(self):
        # Without the bypass the executor's own call would be intercepted and
        # queued again — an approval loop that never executes.
        from core.approvals import executor, gate
        seen = {}

        def fake_execute_tool(name, params):
            seen["bypassed"] = gate._executing.get()
            return {"status": "OK", "order_id": "SO1"}

        with patch("core.approvals.executor.store.claim_for_execution", return_value=_row()), \
             patch("core.approvals.executor.resolvers.resolve", return_value=_draft()), \
             patch("core.approvals.executor.store.mark_executed"), \
             patch("core.approvals.executor.store.get_request", return_value=_row()), \
             patch("core.approvals.executor.events.emit"), \
             patch("core.approvals.executor.execute_tool", fake_execute_tool):
            executor.execute("apr_1")
        self.assertTrue(seen["bypassed"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_approvals_executor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.approvals.executor'`

- [ ] **Step 3: Write the implementation**

```python
"""
Executes an approved request against SAP. Runs as a background task.

Two guards, both load-bearing:

  * The CLAIM is an atomic UPDATE ... WHERE status = 'approved'. If two workers
    pick up the same approved request — two uvicorn processes, a webhook retry
    racing the inbox button — exactly one gets a row back and the other does
    nothing. Reading the status and then acting on it is the race that
    double-posts a receipt.

  * REVALIDATION re-runs the resolver and refuses if the world has moved. An
    approver signed for a specific amount. If the material price changed, or
    the receipt was posted by someone else, or stock ran out, the payload no
    longer means what was approved, and executing it is precisely the failure
    this layer exists to prevent. Default tolerance is 0%.
"""
from __future__ import annotations

import logging

from core.approvals import events, gate, policy, resolvers, store
from tools.tool_registry import execute_tool

_logger = logging.getLogger("core.approvals.executor")


def _measure_of(row: dict, draft) -> tuple[float | None, float | None]:
    """(approved value, current value) for the measure this action is judged on."""
    approved = (row.get("measures") or {})
    for key in ("amount", "days", "qty"):
        if key in approved:
            return _as_float(approved.get(key)), _as_float(draft.measures.get(key))
    return None, None


def _as_float(value):
    return None if value is None else float(value)


def _fail(row: dict, message: str) -> dict | None:
    store.mark_failed(row["request_id"], error=message)
    final = {**row, "status": "failed", "error": message}
    events.emit("approval.failed", final, comment=message)
    return final


def execute(request_id: str) -> dict | None:
    """Execute one approved request. None when another worker owns it."""
    row = store.claim_for_execution(request_id)
    if row is None:
        _logger.info("Approval %s was not ours to execute", request_id)
        return None

    action = row["action"]
    payload = row.get("payload") or {}

    # ── Revalidate ───────────────────────────────────────────────────────────
    draft = resolvers.resolve(action, payload)
    if draft is None:
        return _fail(row, f"Revalidation failed: {action} is no longer a governed action")
    if draft.blocking:
        return _fail(row, "Revalidation failed: " + "; ".join(draft.blocking))

    approved_value, current_value = _measure_of(row, draft)
    if approved_value is not None and current_value is not None:
        tolerance = policy.amount_tolerance_pct()
        allowed = abs(approved_value) * (tolerance / 100.0)
        if abs(current_value - approved_value) > allowed:
            return _fail(
                row,
                f"Revalidation failed: approved for {approved_value}, "
                f"now {current_value}. Nothing was written to SAP.")

    # ── Execute ──────────────────────────────────────────────────────────────
    try:
        with gate.bypass():
            result = execute_tool(action, payload)
    except Exception as exc:
        _logger.exception("Approval %s raised during execution", request_id)
        return _fail(row, f"Execution error: {exc}")

    # Write functions report failure by return value, not by raising.
    if not isinstance(result, dict) or result.get("status") != "OK":
        message = (result or {}).get("message", "SAP rejected the write") \
            if isinstance(result, dict) else "SAP returned an unexpected result"
        return _fail(row, message)

    doc_number, doc_field = gate.extract_doc_number(action, result)
    store.mark_executed(request_id, sap_doc_number=doc_number, sap_doc_field=doc_field)
    final = store.get_request(request_id) or {
        **row, "status": "executed", "sap_doc_number": doc_number}
    events.emit("approval.executed", final)
    _logger.info("Approval %s executed as %s %s", request_id, doc_field, doc_number)
    return final
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_approvals_executor.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add core/approvals/executor.py tests/test_approvals_executor.py
git commit -m "feat(approvals): executor with atomic claim and pre-execution revalidation"
```

---
## Phase 2 — Surface

Approvers get an API, external systems get webhooks in both directions, and
overdue requests escalate on their own.

### Task 8: Outbound webhooks and delivery retry

**Files:**
- Create: `core/approvals/webhooks.py`
- Modify: `core/approvals/store.py` (four delivery functions)
- Test: `tests/test_approvals_webhooks.py`

**Interfaces:**
- Consumes: `requests`, `core.approvals.store`
- Produces:
  - `sign(body: bytes, timestamp: str, secret: str) -> str` — `"sha256=<hex>"`
  - `verify(body: bytes, signature: str, timestamp: str, secret: str, *, window: int = 300) -> bool`
  - `check_target_url(url: str) -> None` — raises `ValueError`
  - `deliver(event: str, row: dict) -> None` — the sink registered with `events`
  - `retry_due(limit: int = 50) -> int`
  - `body_for(event: str, row: dict) -> dict`
- Adds to store: `create_delivery(...) -> dict | None`, `due_deliveries(limit) -> list[dict]`, `mark_delivered(delivery_id, code)`, `mark_delivery_failed(delivery_id, code, error, next_attempt_at)`

- [ ] **Step 1: Write the failing test**

```python
"""Signature and delivery tests. The tamper and replay cases are the ones that
keep a forged decision webhook from approving somebody's payout."""
import time
import unittest
from unittest.mock import patch

SECRET = "test-secret"


class TestSignature(unittest.TestCase):

    def test_round_trip(self):
        from core.approvals.webhooks import sign, verify
        body, ts = b'{"event":"approval.approved"}', str(int(time.time()))
        self.assertTrue(verify(body, sign(body, ts, SECRET), ts, SECRET))

    def test_tampered_body_is_rejected(self):
        from core.approvals.webhooks import sign, verify
        ts = str(int(time.time()))
        sig = sign(b'{"decision":"reject"}', ts, SECRET)
        self.assertFalse(verify(b'{"decision":"approve"}', sig, ts, SECRET))

    def test_wrong_secret_is_rejected(self):
        from core.approvals.webhooks import sign, verify
        body, ts = b'{"a":1}', str(int(time.time()))
        self.assertFalse(verify(body, sign(body, ts, SECRET), ts, "other-secret"))

    def test_replay_outside_the_window_is_rejected(self):
        from core.approvals.webhooks import sign, verify
        body = b'{"a":1}'
        old = str(int(time.time()) - 3600)
        self.assertFalse(verify(body, sign(body, old, SECRET), old, SECRET))

    def test_timestamp_is_bound_into_the_signature(self):
        # Moving the timestamp must invalidate the signature, or the window
        # is decorative.
        from core.approvals.webhooks import sign, verify
        body, ts = b'{"a":1}', str(int(time.time()))
        sig = sign(body, ts, SECRET)
        self.assertFalse(verify(body, sig, str(int(time.time()) - 5), SECRET))

    def test_missing_or_malformed_inputs_are_rejected(self):
        from core.approvals.webhooks import verify
        self.assertFalse(verify(b"{}", "", "", SECRET))
        self.assertFalse(verify(b"{}", "sha256=zzz", "not-a-number", SECRET))


class TestTargetUrl(unittest.TestCase):

    def test_non_http_scheme_is_refused(self):
        from core.approvals.webhooks import check_target_url
        with self.assertRaises(ValueError):
            check_target_url("file:///etc/passwd")

    def test_private_address_refused_by_default(self):
        from core.approvals.webhooks import check_target_url
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("APPROVAL_WEBHOOK_ALLOW_PRIVATE", None)
            with self.assertRaises(ValueError):
                check_target_url("http://127.0.0.1:9000/hook")

    def test_private_address_allowed_when_operator_opts_in(self):
        # An on-premise CPI tenant is routinely on a private network. This is
        # an operator-supplied URL, not a caller-supplied one.
        from core.approvals.webhooks import check_target_url
        with patch.dict("os.environ", {"APPROVAL_WEBHOOK_ALLOW_PRIVATE": "true"}):
            check_target_url("http://127.0.0.1:9000/hook")   # must not raise


class TestBody(unittest.TestCase):

    def test_executed_event_carries_the_document_number(self):
        from core.approvals.webhooks import body_for
        row = {"request_id": "apr_1", "action": "create_sales_order",
               "entity_type": "sales_order", "payload": {"qty": 1},
               "summary": "s", "amount": 420000.0, "currency": "INR",
               "requested_by": "ravi", "decided_by": "sm",
               "status": "executed", "sap_doc_number": "SO123456"}
        body = body_for("approval.executed", row)
        self.assertEqual("approval.executed", body["event"])
        self.assertEqual("SO123456", body["sap_doc_number"])
        self.assertEqual("sm", body["approver"])
        self.assertIn("timestamp", body)


class TestDelivery(unittest.TestCase):

    def test_no_url_configured_is_a_silent_no_op(self):
        from core.approvals import webhooks
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("APPROVAL_WEBHOOK_URL", None)
            with patch.object(webhooks.store, "create_delivery") as create:
                webhooks.deliver("approval.requested", {"request_id": "apr_1"})
            create.assert_not_called()

    def test_the_row_is_written_before_the_http_call(self):
        # Durability first: a receiver that is down must not lose the event.
        from core.approvals import webhooks
        order = []
        with patch.dict("os.environ", {"APPROVAL_WEBHOOK_URL": "https://hooks.example.com/a",
                                       "APPROVAL_WEBHOOK_SECRET": SECRET}), \
             patch.object(webhooks.store, "create_delivery",
                          side_effect=lambda **kw: order.append("row") or {"delivery_id": 1}), \
             patch.object(webhooks, "_attempt", side_effect=lambda d: order.append("http")):
            webhooks.deliver("approval.requested", {"request_id": "apr_1", "action": "x"})
        self.assertEqual(["row", "http"], order)

    def test_a_dead_receiver_does_not_raise(self):
        from core.approvals import webhooks
        import requests
        with patch.dict("os.environ", {"APPROVAL_WEBHOOK_URL": "https://hooks.example.com/a",
                                       "APPROVAL_WEBHOOK_SECRET": SECRET}), \
             patch.object(webhooks.store, "create_delivery", return_value={"delivery_id": 1, "url": "https://hooks.example.com/a", "body": "{}", "attempts": 0}), \
             patch.object(webhooks.store, "mark_delivery_failed") as failed, \
             patch("requests.post", side_effect=requests.ConnectionError("down")):
            webhooks.deliver("approval.requested", {"request_id": "apr_1", "action": "x"})
        failed.assert_called_once()

    def test_backoff_grows_with_attempts(self):
        from core.approvals.webhooks import _backoff_seconds
        self.assertLess(_backoff_seconds(1), _backoff_seconds(2))
        self.assertLess(_backoff_seconds(2), _backoff_seconds(5))
        self.assertLessEqual(_backoff_seconds(99), 3600)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_approvals_webhooks.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.approvals.webhooks'`

- [ ] **Step 3: Add the delivery functions to `core/approvals/store.py`**

```python
_DELIVERY_COLUMNS = """delivery_id, request_id, event, url, body, attempts,
    next_attempt_at, status, response_code, last_error, created_at, updated_at"""


def create_delivery(*, request_id: str, event: str, url: str, body: str) -> dict | None:
    return query_one(
        f"""INSERT INTO approval_deliveries (request_id, event, url, body)
            VALUES (%s,%s,%s,%s) RETURNING {_DELIVERY_COLUMNS}""",
        (request_id, event, url, body),
    )


def due_deliveries(limit: int = 50) -> list[dict]:
    return query_all(
        f"""SELECT {_DELIVERY_COLUMNS} FROM approval_deliveries
            WHERE status = 'pending' AND next_attempt_at <= NOW()
            ORDER BY next_attempt_at ASC LIMIT %s""",
        (limit,),
    )


def mark_delivered(delivery_id: int, *, response_code: int) -> None:
    execute(
        """UPDATE approval_deliveries
           SET status = 'delivered', response_code = %s, attempts = attempts + 1,
               last_error = NULL, updated_at = NOW()
           WHERE delivery_id = %s""",
        (response_code, delivery_id),
    )


def mark_delivery_failed(delivery_id: int, *, response_code: int | None,
                         error: str, next_attempt_at, give_up: bool = False) -> None:
    execute(
        """UPDATE approval_deliveries
           SET status = %s, response_code = %s, attempts = attempts + 1,
               last_error = %s, next_attempt_at = %s, updated_at = NOW()
           WHERE delivery_id = %s""",
        ("failed" if give_up else "pending", response_code, error[:1000],
         next_attempt_at, delivery_id),
    )
```

- [ ] **Step 4: Write `core/approvals/webhooks.py`**

```python
"""
Outbound approval webhooks, and the signature scheme both directions share.

On the target URL check: api/server.py has assert_safe_outbound_url(), which
refuses every private and loopback address. That guard is correct where it
lives — it protects /config/test-mcp, where the URL comes from the CALLER and
an unchecked fetch is an internal port scanner. This URL comes from the
OPERATOR, via environment variable, and an on-premise CPI tenant is routinely
on a private network. Refusing those outright would make the feature unusable
on-premise, so the private-address rule is opt-out via
APPROVAL_WEBHOOK_ALLOW_PRIVATE. The scheme rule is not negotiable either way.

Durability before delivery: the row is written first and the HTTP call is an
attempt against it. A receiver that is down delays a webhook; it never loses
one, and it never blocks an approval decision.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import os
import socket
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import requests

from core.approvals import store

_logger = logging.getLogger("core.approvals.webhooks")

_TIMEOUT = float(os.environ.get("APPROVAL_WEBHOOK_TIMEOUT", "5"))
_MAX_ATTEMPTS = int(os.environ.get("APPROVAL_WEBHOOK_MAX_ATTEMPTS", "8"))


def _secret() -> str:
    return os.environ.get("APPROVAL_WEBHOOK_SECRET", "").strip()


def _url() -> str:
    return os.environ.get("APPROVAL_WEBHOOK_URL", "").strip()


# ── Signature ────────────────────────────────────────────────────────────────

def sign(body: bytes, timestamp: str, secret: str) -> str:
    """Sign the timestamp and the raw body together.

    The timestamp is inside the MAC, so an attacker cannot move a captured
    request into the freshness window without invalidating the signature.
    """
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def verify(body: bytes, signature: str, timestamp: str, secret: str,
           *, window: int = 300) -> bool:
    """Constant-time check of signature and freshness. False on anything odd."""
    if not signature or not timestamp or not secret:
        return False
    try:
        age = abs(time.time() - int(timestamp))
    except (TypeError, ValueError):
        return False
    if age > window:
        return False
    return hmac.compare_digest(signature, sign(body, timestamp, secret))


# ── Target ───────────────────────────────────────────────────────────────────

def check_target_url(url: str) -> None:
    """Raise ValueError unless this is a URL we are willing to POST to."""
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported webhook scheme {parsed.scheme or '(none)'!r}")
    host = parsed.hostname
    if not host:
        raise ValueError("Webhook URL has no host")
    if os.environ.get("APPROVAL_WEBHOOK_ALLOW_PRIVATE", "").lower() in ("true", "1", "yes"):
        return
    try:
        infos = socket.getaddrinfo(
            host, parsed.port or (443 if parsed.scheme == "https" else 80),
            proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValueError(f"Webhook host {host!r} could not be resolved") from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (address.is_private or address.is_loopback or address.is_link_local
                or address.is_reserved or address.is_multicast
                or address.is_unspecified):
            raise ValueError(
                f"Refusing to POST to {host!r}: resolves to internal address "
                f"{address}. Set APPROVAL_WEBHOOK_ALLOW_PRIVATE=true if this is "
                f"an on-premise receiver.")


# ── Body ─────────────────────────────────────────────────────────────────────

def body_for(event: str, row: dict) -> dict:
    return {
        "event":          event,
        "request_id":     row.get("request_id"),
        "action":         row.get("action"),
        "entity_type":    row.get("entity_type"),
        "payload":        row.get("payload"),
        "summary":        row.get("summary"),
        "amount":         float(row["amount"]) if row.get("amount") is not None else None,
        "currency":       row.get("currency"),
        "status":         row.get("status"),
        "requested_by":   row.get("requested_by"),
        "approver":       row.get("decided_by"),
        "approver_role":  row.get("approver_role"),
        "risk_flags":     row.get("risk_flags") or [],
        "sap_doc_number": row.get("sap_doc_number"),
        "error":          row.get("error"),
        "timestamp":      datetime.now(timezone.utc).isoformat(),
    }


# ── Delivery ─────────────────────────────────────────────────────────────────

def _backoff_seconds(attempts: int) -> int:
    """Exponential, capped at an hour."""
    return min(3600, 30 * (2 ** max(0, attempts - 1)))


def _attempt(delivery: dict) -> None:
    """One HTTP attempt against a delivery row. Never raises."""
    body = delivery["body"].encode()
    timestamp = str(int(time.time()))
    headers = {
        "Content-Type":     "application/json",
        "X-Signature":      sign(body, timestamp, _secret()),
        "X-Timestamp":      timestamp,
        "X-Approval-Event": delivery["event"],
        "X-Request-Id":     delivery["request_id"],
    }
    attempts = int(delivery.get("attempts") or 0)
    try:
        resp = requests.post(delivery["url"], data=body, headers=headers, timeout=_TIMEOUT)
        if 200 <= resp.status_code < 300:
            store.mark_delivered(delivery["delivery_id"], response_code=resp.status_code)
            return
        raise requests.HTTPError(f"HTTP {resp.status_code}")
    except Exception as exc:
        nxt = datetime.now(timezone.utc) + timedelta(seconds=_backoff_seconds(attempts + 1))
        store.mark_delivery_failed(
            delivery["delivery_id"], response_code=None, error=str(exc),
            next_attempt_at=nxt, give_up=(attempts + 1) >= _MAX_ATTEMPTS)
        _logger.warning("Webhook delivery %s failed: %s", delivery["delivery_id"], exc)


def deliver(event: str, row: dict) -> None:
    """The sink registered with core.approvals.events. Never raises."""
    url = _url()
    if not url or not _secret():
        return
    try:
        check_target_url(url)
    except ValueError as exc:
        _logger.error("Approval webhook not sent: %s", exc)
        return
    try:
        delivery = store.create_delivery(
            request_id=row.get("request_id") or "", event=event, url=url,
            body=json.dumps(body_for(event, row), default=str))
    except Exception:
        _logger.exception("Could not queue approval webhook for %s", event)
        return
    if delivery:
        _attempt(delivery)


def retry_due(limit: int = 50) -> int:
    """Retry every delivery whose backoff has elapsed. Returns how many ran."""
    rows = store.due_deliveries(limit)
    for delivery in rows:
        _attempt(delivery)
    return len(rows)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_approvals_webhooks.py -v`
Expected: PASS (14 tests)

- [ ] **Step 6: Commit**

```bash
git add core/approvals/webhooks.py core/approvals/store.py tests/test_approvals_webhooks.py
git commit -m "feat(approvals): signed outbound webhooks with durable delivery retry"
```

---
### Task 9: Approvals inbox API

**Files:**
- Create: `api/routes_approvals.py`
- Modify: `api/server.py` (mount the router; register the webhook sink at startup)
- Test: `tests/test_approvals_api.py`

**Interfaces:**
- Consumes: `api.deps.get_current_user`, `core.approvals.store`, `policy`, `events`, `executor`
- Produces: router at `/approvals`; helper `_may_decide(row, user) -> tuple[bool, str]`

- [ ] **Step 1: Write the failing test**

```python
"""Approvals API. The authorization tests here are the layer's teeth: if a
requester can approve their own request, the whole thing is decoration."""
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

PENDING = {
    "request_id": "apr_1", "action": "create_sales_order", "entity_type": "sales_order",
    "payload": {"customer_id": "C001", "qty": 100}, "context": {"customer_name": "Acme"},
    "measures": {"amount": 420000.0}, "amount": 420000.0, "currency": "INR",
    "summary": "Sales order for Acme", "risk_flags": [], "requested_by": "ravi",
    "requester_roles": ["sd_analyst"], "status": "pending", "chain_index": 0,
    "approver_role": "sales_manager",
    "approval_chain": [{"role": "sales_manager", "escalate_to": "cfo", "sla_hours": 8}],
}


def client_as(user_id, roles):
    from api import server as server_module
    app = server_module.app
    app.dependency_overrides[server_module.get_current_user] = lambda: {
        "user_id": user_id, "roles": roles}
    return TestClient(app)


def tearDownModule():
    from api import server as server_module
    server_module.app.dependency_overrides.clear()


class TestDecisionAuthorization(unittest.TestCase):

    def test_requester_cannot_approve_their_own_request(self):
        with patch("api.routes_approvals.store.get_request", return_value=PENDING), \
             patch("api.routes_approvals.store.advance_or_approve") as approve:
            resp = client_as("ravi", ["sd_analyst", "sales_manager"]).post(
                "/approvals/apr_1/approve", json={"comment": "mine"})
        self.assertEqual(403, resp.status_code)
        self.assertIn("own request", resp.json()["detail"].lower())
        approve.assert_not_called()

    def test_admin_cannot_approve_their_own_request_either(self):
        # admin holds every role; exempting it would make the layer optional
        # for the one account most worth constraining.
        own = {**PENDING, "requested_by": "admin"}
        with patch("api.routes_approvals.store.get_request", return_value=own), \
             patch("api.routes_approvals.store.advance_or_approve") as approve:
            resp = client_as("admin", ["admin"]).post(
                "/approvals/apr_1/approve", json={"comment": "ok"})
        self.assertEqual(403, resp.status_code)
        approve.assert_not_called()

    def test_wrong_role_cannot_approve(self):
        with patch("api.routes_approvals.store.get_request", return_value=PENDING), \
             patch("api.routes_approvals.store.advance_or_approve") as approve:
            resp = client_as("bob", ["hr_approver"]).post(
                "/approvals/apr_1/approve", json={"comment": "ok"})
        self.assertEqual(403, resp.status_code)
        approve.assert_not_called()

    def test_correct_role_approves(self):
        approved = {**PENDING, "status": "approved", "decided_by": "sm"}
        with patch("api.routes_approvals.store.get_request", return_value=PENDING), \
             patch("api.routes_approvals.store.advance_or_approve", return_value=approved), \
             patch("api.routes_approvals.events.emit"), \
             patch("api.routes_approvals.executor.execute") as run:
            resp = client_as("sm", ["sales_manager"]).post(
                "/approvals/apr_1/approve", json={"comment": "fine"})
        self.assertEqual(200, resp.status_code)
        self.assertEqual("approved", resp.json()["status"])
        run.assert_called_once_with("apr_1")

    def test_admin_may_act_as_any_approver_for_someone_elses_request(self):
        # Operationally necessary: somebody has to be able to unblock a queue.
        approved = {**PENDING, "status": "approved", "decided_by": "admin"}
        with patch("api.routes_approvals.store.get_request", return_value=PENDING), \
             patch("api.routes_approvals.store.advance_or_approve", return_value=approved), \
             patch("api.routes_approvals.events.emit"), \
             patch("api.routes_approvals.executor.execute"):
            resp = client_as("admin", ["admin"]).post(
                "/approvals/apr_1/approve", json={"comment": "unblocking"})
        self.assertEqual(200, resp.status_code)

    def test_a_decided_request_cannot_be_decided_again(self):
        done = {**PENDING, "status": "executed"}
        with patch("api.routes_approvals.store.get_request", return_value=done):
            resp = client_as("sm", ["sales_manager"]).post(
                "/approvals/apr_1/approve", json={"comment": "again"})
        self.assertEqual(409, resp.status_code)


class TestChainAdvance(unittest.TestCase):

    def test_intermediate_approval_does_not_execute(self):
        two_level = {**PENDING, "approval_chain": [
            {"role": "finance_manager", "sla_hours": 8}, {"role": "cfo", "sla_hours": 24}]}
        advanced = {**two_level, "status": "pending", "chain_index": 1, "approver_role": "cfo"}
        with patch("api.routes_approvals.store.get_request", return_value=two_level), \
             patch("api.routes_approvals.store.advance_or_approve", return_value=advanced), \
             patch("api.routes_approvals.events.emit") as emit, \
             patch("api.routes_approvals.executor.execute") as run:
            resp = client_as("fm", ["finance_manager"]).post(
                "/approvals/apr_1/approve", json={"comment": "level 1"})
        self.assertEqual("pending", resp.json()["status"])
        self.assertEqual("cfo", resp.json()["approver_role"])
        run.assert_not_called()
        self.assertEqual("approval.level_approved", emit.call_args.args[0])


class TestReject(unittest.TestCase):

    def test_reject_requires_a_comment(self):
        with patch("api.routes_approvals.store.get_request", return_value=PENDING):
            resp = client_as("sm", ["sales_manager"]).post(
                "/approvals/apr_1/reject", json={"comment": ""})
        self.assertEqual(422, resp.status_code)

    def test_reject_never_executes(self):
        rejected = {**PENDING, "status": "rejected"}
        with patch("api.routes_approvals.store.get_request", return_value=PENDING), \
             patch("api.routes_approvals.store.reject", return_value=rejected), \
             patch("api.routes_approvals.events.emit"), \
             patch("api.routes_approvals.executor.execute") as run:
            resp = client_as("sm", ["sales_manager"]).post(
                "/approvals/apr_1/reject", json={"comment": "credit risk"})
        self.assertEqual("rejected", resp.json()["status"])
        run.assert_not_called()


class TestListing(unittest.TestCase):

    def test_inbox_scope_filters_by_the_callers_roles(self):
        with patch("api.routes_approvals.store.list_requests", return_value=[]) as lst:
            client_as("sm", ["sales_manager"]).get("/approvals?scope=inbox")
        self.assertEqual(["sales_manager"], lst.call_args.kwargs["scope_roles"])
        self.assertEqual("pending", lst.call_args.kwargs["status"])

    def test_mine_scope_filters_by_requester(self):
        with patch("api.routes_approvals.store.list_requests", return_value=[]) as lst:
            client_as("ravi", ["sd_analyst"]).get("/approvals?scope=mine")
        self.assertEqual("ravi", lst.call_args.kwargs["requested_by"])

    def test_all_scope_is_admin_only(self):
        resp = client_as("ravi", ["sd_analyst"]).get("/approvals?scope=all")
        self.assertEqual(403, resp.status_code)

    def test_detail_includes_the_event_trail(self):
        with patch("api.routes_approvals.store.get_request", return_value=PENDING), \
             patch("api.routes_approvals.store.list_events",
                   return_value=[{"event": "approval.requested", "actor": "ravi"}]):
            resp = client_as("sm", ["sales_manager"]).get("/approvals/apr_1")
        self.assertEqual(1, len(resp.json()["events"]))

    def test_unknown_request_is_404(self):
        with patch("api.routes_approvals.store.get_request", return_value=None):
            resp = client_as("sm", ["sales_manager"]).get("/approvals/nope")
        self.assertEqual(404, resp.status_code)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_approvals_api.py -v`
Expected: FAIL — 404 on every route (`api.routes_approvals` does not exist)

- [ ] **Step 3: Write `api/routes_approvals.py`**

```python
"""
The approvals inbox.

Authorization here is the layer's teeth, and two rules carry it:

  * The caller must hold the role at approval_chain[chain_index] — the CURRENT
    step, not any step. Holding a later role does not let you skip an earlier
    signature.

  * Nobody approves their own request, admin included. Admin holds every role,
    so exempting it would make the whole layer optional for exactly the account
    most worth constraining. Admin may still act as any approver for OTHER
    people's requests, because somebody has to be able to unblock a queue.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.deps import get_current_user
from core.approvals import events, executor, policy, store

_logger = logging.getLogger("api.routes_approvals")

router = APIRouter(prefix="/approvals", tags=["approvals"])


class DecisionBody(BaseModel):
    comment: str = Field("", max_length=2000)


class RejectBody(BaseModel):
    comment: str = Field(..., min_length=1, max_length=2000)


def _view(row: dict, roles: list[str] | None = None) -> dict:
    """Response shape. Restricted fields in the resolver context stay masked."""
    from core.authorization import mask_fields
    out = dict(row)
    if roles is not None:
        out["context"] = mask_fields(out.get("context"), roles)
    if out.get("amount") is not None:
        out["amount"] = float(out["amount"])
    return out


def _required_role(row: dict) -> str | None:
    chain = row.get("approval_chain") or []
    idx = int(row.get("chain_index") or 0)
    return chain[idx]["role"] if 0 <= idx < len(chain) else None


def _may_decide(row: dict, user: dict) -> tuple[bool, str]:
    """(allowed, reason). Reason is the 403 detail when not allowed."""
    if row.get("status") != "pending":
        return False, f"This request is already {row.get('status')}."
    if row.get("requested_by") == user["user_id"] and not policy.allow_self_approval():
        return False, "You cannot approve your own request."
    required = _required_role(row)
    if required is None:
        return False, "This request has no pending approval step."
    roles = user.get("roles", [])
    if required not in roles and "admin" not in roles:
        return False, f"This request is waiting on {required}."
    return True, ""


@router.get("")
def list_approvals(
    scope: str = Query("inbox", pattern="^(inbox|mine|all)$"),
    status: str | None = Query(None, max_length=16),
    action: str | None = Query(None, max_length=64),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: dict = Depends(get_current_user),
):
    roles = user.get("roles", [])
    if scope == "all":
        if "admin" not in roles:
            raise HTTPException(403, "Admin role required to list all approvals.")
        rows = store.list_requests(status=status, action=action, limit=limit, offset=offset)
    elif scope == "mine":
        rows = store.list_requests(requested_by=user["user_id"], status=status,
                                   action=action, limit=limit, offset=offset)
    else:
        rows = store.list_requests(scope_roles=list(roles), status=status or "pending",
                                   action=action, limit=limit, offset=offset)
    return {"requests": [_view(r, roles) for r in rows], "scope": scope}


@router.get("/stats")
def approval_stats(user: dict = Depends(get_current_user)):
    roles = user.get("roles", [])
    return {
        "inbox": store.count_by_status(scope_roles=list(roles)).get("pending", 0),
        "mine":  store.count_by_status(requested_by=user["user_id"]),
    }


@router.get("/{request_id}")
def get_approval(request_id: str, user: dict = Depends(get_current_user)):
    row = store.get_request(request_id)
    if row is None:
        raise HTTPException(404, "No such approval request.")
    roles = user.get("roles", [])
    view = _view(row, roles)
    view["events"] = store.list_events(request_id)
    view["can_decide"] = _may_decide(row, user)[0]
    view["required_role"] = _required_role(row)
    return view


@router.post("/{request_id}/approve")
def approve(request_id: str, body: DecisionBody, tasks: BackgroundTasks,
            user: dict = Depends(get_current_user)):
    row = store.get_request(request_id)
    if row is None:
        raise HTTPException(404, "No such approval request.")
    allowed, reason = _may_decide(row, user)
    if not allowed:
        raise HTTPException(409 if row.get("status") != "pending" else 403, reason)

    updated = store.advance_or_approve(request_id, decided_by=user["user_id"],
                                       comment=body.comment)
    if updated is None:
        # Somebody decided it between our read and our write.
        raise HTTPException(409, "This request was decided by someone else.")

    if updated["status"] == "approved":
        events.emit("approval.approved", updated, actor=user["user_id"],
                    comment=body.comment)
        tasks.add_task(executor.execute, request_id)
    else:
        events.emit("approval.level_approved", updated, actor=user["user_id"],
                    comment=body.comment)
    return _view(updated, user.get("roles", []))


@router.post("/{request_id}/reject")
def reject(request_id: str, body: RejectBody, user: dict = Depends(get_current_user)):
    row = store.get_request(request_id)
    if row is None:
        raise HTTPException(404, "No such approval request.")
    allowed, reason = _may_decide(row, user)
    if not allowed:
        raise HTTPException(409 if row.get("status") != "pending" else 403, reason)

    updated = store.reject(request_id, decided_by=user["user_id"], comment=body.comment)
    if updated is None:
        raise HTTPException(409, "This request was decided by someone else.")
    events.emit("approval.rejected", updated, actor=user["user_id"], comment=body.comment)
    return _view(updated, user.get("roles", []))
```

- [ ] **Step 4: Mount the router and register the webhook sink in `api/server.py`**

Next to the existing AI admin router mounts (around line 221):

```python
from api.routes_approvals import router as _approvals_router
app.include_router(_approvals_router)
```

Inside `lifespan`, after the existing migration block, add the approval
migration and the webhook sink registration:

```python
    try:
        from core.approvals.schema import run_approval_migrations
        await _aio.wait_for(_aio.to_thread(run_approval_migrations), timeout=5.0)
    except Exception as _appr_exc:
        _logger.warning("Approval migration step failed or timed out: %s", _appr_exc)

    # Registered explicitly rather than by import side effect, so importing
    # core.approvals never opens a socket and tests never have to unpick one.
    from core.approvals import events as _appr_events, webhooks as _appr_webhooks
    _appr_events.register_sink(_appr_webhooks.deliver)
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_approvals_api.py -v`
Expected: PASS (14 tests)

Run: `python -m pytest tests/ -q`
Expected: no new failures.

- [ ] **Step 6: Commit**

```bash
git add api/routes_approvals.py api/server.py tests/test_approvals_api.py
git commit -m "feat(approvals): inbox API with chain-aware, self-approval-proof decisions"
```

---

### Task 10: Edit supersedes

An approver who wants "reduce qty to 40" must not mutate the request in place.
Mutating would let somebody approve ₹40,000 and execute ₹4,00,000. The patched
payload is re-resolved, re-evaluated by policy, and becomes a NEW request; the
original is marked superseded.

**Files:**
- Modify: `api/routes_approvals.py` (add `POST /{request_id}/edit`)
- Test: `tests/test_approvals_api.py` (add `TestEditSupersedes`)

**Interfaces:**
- Consumes: `resolvers.resolve`, `policy.evaluate`, `policy.chain_as_dicts`, `store.create_request`, `store.mark_superseded`
- Produces: `POST /approvals/{id}/edit` → the new request's view, with `supersedes` set

- [ ] **Step 1: Write the failing test**

```python
class TestEditSupersedes(unittest.TestCase):

    def _draft(self, amount):
        from core.approvals.resolvers import Draft
        return Draft(entity_type="sales_order", measures={"amount": amount},
                     context={}, risk_flags=[], blocking=[],
                     summary=f"Sales order {amount}", amount=amount, currency="INR")

    def test_edit_creates_a_new_request_and_supersedes_the_old(self):
        new_row = {**PENDING, "request_id": "apr_2", "amount": 168000.0,
                   "supersedes": "apr_1"}
        with patch("api.routes_approvals.store.get_request", return_value=PENDING), \
             patch("api.routes_approvals.resolvers.resolve", return_value=self._draft(168000.0)), \
             patch("api.routes_approvals.store.create_request", return_value=new_row) as create, \
             patch("api.routes_approvals.store.mark_superseded") as superseded, \
             patch("api.routes_approvals.events.emit"):
            resp = client_as("sm", ["sales_manager"]).post(
                "/approvals/apr_1/edit",
                json={"payload_patch": {"qty": 40}, "comment": "reduce qty to 40"})
        self.assertEqual(200, resp.status_code)
        self.assertEqual("apr_2", resp.json()["request_id"])
        self.assertEqual("apr_1", create.call_args.kwargs["supersedes"])
        self.assertEqual(40, create.call_args.kwargs["payload"]["qty"])
        superseded.assert_called_once()

    def test_an_edit_that_raises_the_amount_re_escalates(self):
        # Approving 40,000 must never become executing 6,00,000.
        captured = {}

        def fake_create(**kw):
            captured.update(kw)
            return {**PENDING, "request_id": "apr_2"}

        with patch("api.routes_approvals.store.get_request", return_value=PENDING), \
             patch("api.routes_approvals.resolvers.resolve", return_value=self._draft(6000000.0)), \
             patch("api.routes_approvals.store.create_request", side_effect=fake_create), \
             patch("api.routes_approvals.store.mark_superseded"), \
             patch("api.routes_approvals.events.emit"):
            client_as("sm", ["sales_manager"]).post(
                "/approvals/apr_1/edit",
                json={"payload_patch": {"qty": 2000}, "comment": "bump"})
        roles = [e["role"] for e in captured["approval_chain"]]
        self.assertEqual(["sales_manager", "cfo"], roles)

    def test_an_edit_that_drops_below_the_auto_threshold_still_needs_a_signature(self):
        # An approver must not be able to edit their way to auto-execution.
        captured = {}

        def fake_create(**kw):
            captured.update(kw)
            return {**PENDING, "request_id": "apr_2"}

        with patch("api.routes_approvals.store.get_request", return_value=PENDING), \
             patch("api.routes_approvals.resolvers.resolve", return_value=self._draft(1000.0)), \
             patch("api.routes_approvals.store.create_request", side_effect=fake_create), \
             patch("api.routes_approvals.store.mark_superseded"), \
             patch("api.routes_approvals.events.emit"):
            client_as("sm", ["sales_manager"]).post(
                "/approvals/apr_1/edit",
                json={"payload_patch": {"qty": 1}, "comment": "tiny"})
        self.assertEqual("pending", captured["status"])
        self.assertTrue(captured["approval_chain"])

    def test_an_edit_that_becomes_impossible_is_refused(self):
        from core.approvals.resolvers import Draft
        blocked = Draft(entity_type="sales_order", measures={}, context={},
                        risk_flags=[], blocking=["Material GONE not found"],
                        summary="", amount=None, currency="INR")
        with patch("api.routes_approvals.store.get_request", return_value=PENDING), \
             patch("api.routes_approvals.resolvers.resolve", return_value=blocked), \
             patch("api.routes_approvals.store.create_request") as create:
            resp = client_as("sm", ["sales_manager"]).post(
                "/approvals/apr_1/edit",
                json={"payload_patch": {"material_id": "GONE"}, "comment": "swap"})
        self.assertEqual(422, resp.status_code)
        create.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_approvals_api.py::TestEditSupersedes -v`
Expected: FAIL — 405 Method Not Allowed

- [ ] **Step 3: Add the endpoint to `api/routes_approvals.py`**

Add the import of `resolvers` to the existing `core.approvals` import, then:

```python
class EditBody(BaseModel):
    payload_patch: dict = Field(..., description="Fields to change on the payload")
    comment: str = Field(..., min_length=1, max_length=2000)


@router.post("/{request_id}/edit")
def edit(request_id: str, body: EditBody, user: dict = Depends(get_current_user)):
    """Replace a request with a corrected one. Never mutates in place.

    Re-running policy on the patched payload is the point: an edit that raises
    the amount past a threshold escalates, and an edit that lowers it still
    needs whatever signature the new tier requires. Mutating the row instead
    would let an approver approve one number and execute another.
    """
    row = store.get_request(request_id)
    if row is None:
        raise HTTPException(404, "No such approval request.")
    allowed, reason = _may_decide(row, user)
    if not allowed:
        raise HTTPException(409 if row.get("status") != "pending" else 403, reason)

    patched = {**(row.get("payload") or {}), **body.payload_patch}
    draft = resolvers.resolve(row["action"], patched)
    if draft is None:
        raise HTTPException(422, "This action can no longer be validated.")
    if draft.blocking:
        raise HTTPException(422, "; ".join(draft.blocking))

    decision = policy.evaluate(row["action"], draft.measures, draft.risk_flags)
    if decision is None:
        raise HTTPException(422, "This action has no approval policy.")

    # An edited request always needs a signature, even if the new amount would
    # have auto-approved from scratch — otherwise an approver could edit their
    # way to execution without anyone signing the changed numbers.
    chain = policy.chain_as_dicts(decision.chain) or list(row.get("approval_chain") or [])

    new_row = store.create_request(
        action=row["action"], entity_type=decision.entity_type, payload=patched,
        context=draft.context, measures=draft.measures, amount=draft.amount,
        currency=draft.currency, summary=draft.summary,
        risk_flags=list(draft.risk_flags), requested_by=row["requested_by"],
        requester_roles=row.get("requester_roles") or [], approval_chain=chain,
        status="pending", session_id=row.get("session_id"), supersedes=request_id,
        hard_ttl_hours=policy.hard_ttl_hours(),
    )
    if new_row is None:
        raise HTTPException(500, "Could not create the edited request.")

    store.mark_superseded(request_id, superseded_by=new_row["request_id"])
    events.emit("approval.edited", {**row, "superseded_by": new_row["request_id"]},
                actor=user["user_id"], comment=body.comment,
                payload_before=row.get("payload"), payload_after=patched)
    events.emit("approval.requested", new_row, actor=user["user_id"],
                comment=f"Edited from {request_id}: {body.comment}")
    return _view(new_row, user.get("roles", []))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_approvals_api.py -v`
Expected: PASS (18 tests)

- [ ] **Step 5: Commit**

```bash
git add api/routes_approvals.py tests/test_approvals_api.py
git commit -m "feat(approvals): approver edits supersede and re-run policy"
```

---
### Task 11: Inbound webhooks

**Files:**
- Create: `api/routes_approval_webhooks.py`
- Modify: `core/approvals/store.py` (add `set_sap_doc_status`)
- Modify: `api/server.py` (mount the router)
- Test: `tests/test_approvals_inbound.py`

**Interfaces:**
- Consumes: `core.approvals.webhooks.verify`, `store`, `events`, `executor`, `api.routes_approvals._may_decide`
- Produces: `POST /webhooks/approval/{request_id}/decision`, `POST /webhooks/sap/document-status`; store gains `set_sap_doc_status(sap_doc_number, status) -> int`

- [ ] **Step 1: Write the failing test**

```python
"""Inbound webhook tests. Signature verification must happen against the RAW
body — re-serialising and re-signing would pass on any key order and defeat the
whole scheme."""
import json
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

SECRET = "inbound-secret"
PENDING = {
    "request_id": "apr_1", "action": "create_sales_order", "status": "pending",
    "chain_index": 0, "requested_by": "ravi", "approver_role": "sales_manager",
    "approval_chain": [{"role": "sales_manager", "sla_hours": 8}],
    "payload": {}, "context": {}, "measures": {}, "amount": 1.0, "currency": "INR",
}


def signed(path, payload):
    from core.approvals.webhooks import sign
    from api import server as server_module
    body = json.dumps(payload).encode()
    ts = str(int(time.time()))
    return TestClient(server_module.app).post(
        path, content=body,
        headers={"Content-Type": "application/json",
                 "X-Signature": sign(body, ts, SECRET),
                 "X-Timestamp": ts})


class TestSignatureGate(unittest.TestCase):

    def setUp(self):
        self.env = patch.dict("os.environ", {"APPROVAL_WEBHOOK_SECRET": SECRET})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_unsigned_request_is_rejected(self):
        from api import server as server_module
        resp = TestClient(server_module.app).post(
            "/webhooks/approval/apr_1/decision", json={"decision": "approve"})
        self.assertEqual(401, resp.status_code)

    def test_tampered_body_is_rejected(self):
        from core.approvals.webhooks import sign
        from api import server as server_module
        ts = str(int(time.time()))
        sig = sign(json.dumps({"decision": "reject"}).encode(), ts, SECRET)
        resp = TestClient(server_module.app).post(
            "/webhooks/approval/apr_1/decision",
            content=json.dumps({"decision": "approve"}).encode(),
            headers={"X-Signature": sig, "X-Timestamp": ts,
                     "Content-Type": "application/json"})
        self.assertEqual(401, resp.status_code)

    def test_stale_timestamp_is_rejected(self):
        from core.approvals.webhooks import sign
        from api import server as server_module
        body = json.dumps({"decision": "approve"}).encode()
        old = str(int(time.time()) - 3600)
        resp = TestClient(server_module.app).post(
            "/webhooks/approval/apr_1/decision", content=body,
            headers={"X-Signature": sign(body, old, SECRET), "X-Timestamp": old,
                     "Content-Type": "application/json"})
        self.assertEqual(401, resp.status_code)


class TestDecision(unittest.TestCase):

    def setUp(self):
        self.env = patch.dict("os.environ", {"APPROVAL_WEBHOOK_SECRET": SECRET})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_signed_approval_executes(self):
        approved = {**PENDING, "status": "approved"}
        with patch("api.routes_approval_webhooks.store.get_request", return_value=PENDING), \
             patch("api.routes_approval_webhooks.store.advance_or_approve", return_value=approved), \
             patch("api.routes_approval_webhooks.events.emit", return_value=True), \
             patch("api.routes_approval_webhooks.executor.execute") as run:
            resp = signed("/webhooks/approval/apr_1/decision",
                          {"decision": "approve", "by": "sm@corp",
                           "comment": "ok", "idempotency_key": "k1"})
        self.assertEqual(200, resp.status_code)
        run.assert_called_once_with("apr_1")

    def test_a_retried_delivery_does_not_decide_twice(self):
        # events.emit returns False when the (request_id, idempotency_key)
        # unique index rejects the duplicate.
        approved = {**PENDING, "status": "approved"}
        with patch("api.routes_approval_webhooks.store.get_request", return_value=PENDING), \
             patch("api.routes_approval_webhooks.store.advance_or_approve", return_value=approved), \
             patch("api.routes_approval_webhooks.events.emit", return_value=False), \
             patch("api.routes_approval_webhooks.executor.execute") as run:
            resp = signed("/webhooks/approval/apr_1/decision",
                          {"decision": "approve", "by": "sm@corp",
                           "comment": "ok", "idempotency_key": "k1"})
        self.assertEqual(200, resp.status_code)
        self.assertTrue(resp.json()["duplicate"])
        run.assert_not_called()

    def test_reject_never_executes(self):
        rejected = {**PENDING, "status": "rejected"}
        with patch("api.routes_approval_webhooks.store.get_request", return_value=PENDING), \
             patch("api.routes_approval_webhooks.store.reject", return_value=rejected), \
             patch("api.routes_approval_webhooks.events.emit", return_value=True), \
             patch("api.routes_approval_webhooks.executor.execute") as run:
            resp = signed("/webhooks/approval/apr_1/decision",
                          {"decision": "reject", "by": "sm@corp", "comment": "no"})
        self.assertEqual(200, resp.status_code)
        run.assert_not_called()

    def test_unknown_request_is_404(self):
        with patch("api.routes_approval_webhooks.store.get_request", return_value=None):
            resp = signed("/webhooks/approval/nope/decision",
                          {"decision": "approve", "by": "x"})
        self.assertEqual(404, resp.status_code)

    def test_invalid_decision_value_is_422(self):
        with patch("api.routes_approval_webhooks.store.get_request", return_value=PENDING):
            resp = signed("/webhooks/approval/apr_1/decision",
                          {"decision": "maybe", "by": "x"})
        self.assertEqual(422, resp.status_code)


class TestDocumentStatus(unittest.TestCase):

    def setUp(self):
        self.env = patch.dict("os.environ", {"APPROVAL_WEBHOOK_SECRET": SECRET})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_status_is_recorded_against_the_document(self):
        with patch("api.routes_approval_webhooks.store.set_sap_doc_status",
                   return_value=1) as setter:
            resp = signed("/webhooks/sap/document-status",
                          {"sap_doc_number": "SO123456", "status": "released"})
        self.assertEqual(200, resp.status_code)
        self.assertEqual("SO123456", setter.call_args.kwargs["sap_doc_number"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_approvals_inbound.py -v`
Expected: FAIL — 404 on every route

- [ ] **Step 3: Add `set_sap_doc_status` to `core/approvals/store.py`**

```python
def set_sap_doc_status(*, sap_doc_number: str, status: str) -> int:
    return execute(
        """UPDATE approval_requests SET sap_doc_status = %s, updated_at = NOW()
           WHERE sap_doc_number = %s""",
        (status, sap_doc_number),
    )
```

- [ ] **Step 4: Write `api/routes_approval_webhooks.py`**

```python
"""
Inbound approval webhooks: an external portal or CPI tenant deciding a request,
and SAP reporting what happened to a document afterwards.

Signature verification runs against the RAW request body. Verifying a
re-serialised body would succeed on any key order or whitespace the sender used
and would therefore verify nothing, so the body is read once here and the
parsed object is passed on rather than re-read downstream.

These endpoints return quickly and hand execution to a background task, because
a receiver that waits for SAP will time out and retry, and a retry that
executes again is exactly what the idempotency key exists to prevent.
"""
from __future__ import annotations

import json
import logging
import os

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from core.approvals import events, executor, store, webhooks

_logger = logging.getLogger("api.routes_approval_webhooks")

router = APIRouter(tags=["approval-webhooks"])


async def _verified_json(request: Request) -> dict:
    secret = os.environ.get("APPROVAL_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise HTTPException(503, "Inbound approval webhooks are not configured.")
    raw = await request.body()
    if not webhooks.verify(raw,
                           request.headers.get("X-Signature", ""),
                           request.headers.get("X-Timestamp", ""),
                           secret):
        raise HTTPException(401, "Invalid or expired webhook signature.")
    try:
        parsed = json.loads(raw or b"{}")
    except ValueError:
        raise HTTPException(422, "Body is not valid JSON.")
    if not isinstance(parsed, dict):
        raise HTTPException(422, "Body must be a JSON object.")
    return parsed


@router.post("/webhooks/approval/{request_id}/decision")
async def decision(request_id: str, request: Request, tasks: BackgroundTasks):
    body = await _verified_json(request)
    verdict = str(body.get("decision", "")).lower()
    if verdict not in ("approve", "reject"):
        raise HTTPException(422, "decision must be 'approve' or 'reject'.")

    row = store.get_request(request_id)
    if row is None:
        raise HTTPException(404, "No such approval request.")
    if row.get("status") != "pending":
        # Not an error: a retry after a successful decision lands here.
        return {"ok": True, "status": row.get("status"), "duplicate": True}

    actor = str(body.get("by") or "webhook")[:64]
    comment = str(body.get("comment") or "")[:2000]
    idem = body.get("idempotency_key")

    if verdict == "reject":
        updated = store.reject(request_id, decided_by=actor, comment=comment or "rejected")
        if updated is None:
            return {"ok": True, "status": "already-decided", "duplicate": True}
        fresh = events.emit("approval.rejected", updated, actor=actor,
                            comment=comment, idempotency_key=idem)
        return {"ok": True, "status": updated["status"], "duplicate": not fresh}

    updated = store.advance_or_approve(request_id, decided_by=actor, comment=comment)
    if updated is None:
        return {"ok": True, "status": "already-decided", "duplicate": True}

    if updated["status"] == "approved":
        fresh = events.emit("approval.approved", updated, actor=actor,
                            comment=comment, idempotency_key=idem)
        if fresh:
            tasks.add_task(executor.execute, request_id)
        return {"ok": True, "status": "approved", "duplicate": not fresh}

    fresh = events.emit("approval.level_approved", updated, actor=actor,
                        comment=comment, idempotency_key=idem)
    return {"ok": True, "status": updated["status"],
            "approver_role": updated.get("approver_role"), "duplicate": not fresh}


@router.post("/webhooks/sap/document-status")
async def document_status(request: Request):
    body = await _verified_json(request)
    doc = str(body.get("sap_doc_number") or "").strip()
    status = str(body.get("status") or "").strip()[:20]
    if not doc or not status:
        raise HTTPException(422, "sap_doc_number and status are required.")
    updated = store.set_sap_doc_status(sap_doc_number=doc, status=status)
    return {"ok": True, "updated": updated}
```

- [ ] **Step 5: Mount it in `api/server.py`**

Beside the approvals router mount:

```python
from api.routes_approval_webhooks import router as _approval_hooks_router
app.include_router(_approval_hooks_router)
```

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_approvals_inbound.py -v`
Expected: PASS (9 tests)

- [ ] **Step 7: Commit**

```bash
git add api/routes_approval_webhooks.py core/approvals/store.py api/server.py tests/test_approvals_inbound.py
git commit -m "feat(approvals): HMAC-verified inbound decision and SAP status webhooks"
```

---

### Task 12: Escalation sweeper

**Files:**
- Create: `core/approvals/escalation.py`
- Modify: `core/approvals/store.py` (add `escalate`, `expire`)
- Modify: `api/server.py` (start and stop the task in `lifespan`)
- Test: `tests/test_approvals_escalation.py`

**Interfaces:**
- Consumes: `store.due_for_escalation`, `store.due_for_expiry`, `webhooks.retry_due`, `db.connection`
- Produces: `sweep() -> dict`, `run_forever(interval: int = 60)`, `start() -> asyncio.Task`, `stop(task)`; store gains `escalate(request_id, *, new_role, sla_due_at) -> dict | None` and `expire(request_id) -> dict | None`

- [ ] **Step 1: Write the failing test**

```python
"""Sweeper tests. Chain advance and escalation are different mechanisms and
must not be confused: escalation replaces WHO signs at the current step, it
never removes a required signature."""
import unittest
from unittest.mock import patch

OVERDUE = {
    "request_id": "apr_1", "status": "pending", "chain_index": 0,
    "approval_chain": [{"role": "sales_manager", "escalate_to": "cfo", "sla_hours": 8},
                       {"role": "cfo", "sla_hours": 24}],
    "approver_role": "sales_manager", "action": "create_sales_order",
}


class TestEscalation(unittest.TestCase):

    def test_overdue_request_moves_to_the_escalation_role(self):
        from core.approvals import escalation
        with patch("core.approvals.escalation.store.due_for_escalation", return_value=[OVERDUE]), \
             patch("core.approvals.escalation.store.due_for_expiry", return_value=[]), \
             patch("core.approvals.escalation.webhooks.retry_due", return_value=0), \
             patch("core.approvals.escalation.store.escalate",
                   return_value={**OVERDUE, "approver_role": "cfo"}) as esc, \
             patch("core.approvals.escalation.events.emit"):
            out = escalation.sweep()
        self.assertEqual(1, out["escalated"])
        self.assertEqual("cfo", esc.call_args.kwargs["new_role"])

    def test_escalation_does_not_advance_the_chain(self):
        # The number of required signatures must not change.
        from core.approvals import escalation
        with patch("core.approvals.escalation.store.due_for_escalation", return_value=[OVERDUE]), \
             patch("core.approvals.escalation.store.due_for_expiry", return_value=[]), \
             patch("core.approvals.escalation.webhooks.retry_due", return_value=0), \
             patch("core.approvals.escalation.store.escalate",
                   return_value={**OVERDUE, "approver_role": "cfo"}), \
             patch("core.approvals.escalation.store.advance_or_approve") as advance, \
             patch("core.approvals.escalation.events.emit"):
            escalation.sweep()
        advance.assert_not_called()

    def test_a_step_with_no_escalation_target_is_left_alone(self):
        from core.approvals import escalation
        terminal = {**OVERDUE, "approval_chain": [{"role": "hr_approver", "sla_hours": 24}]}
        with patch("core.approvals.escalation.store.due_for_escalation", return_value=[terminal]), \
             patch("core.approvals.escalation.store.due_for_expiry", return_value=[]), \
             patch("core.approvals.escalation.webhooks.retry_due", return_value=0), \
             patch("core.approvals.escalation.store.escalate") as esc, \
             patch("core.approvals.escalation.events.emit"):
            out = escalation.sweep()
        esc.assert_not_called()
        self.assertEqual(0, out["escalated"])


class TestExpiry(unittest.TestCase):

    def test_expired_request_is_closed_and_never_executes(self):
        from core.approvals import escalation
        with patch("core.approvals.escalation.store.due_for_escalation", return_value=[]), \
             patch("core.approvals.escalation.store.due_for_expiry", return_value=[OVERDUE]), \
             patch("core.approvals.escalation.webhooks.retry_due", return_value=0), \
             patch("core.approvals.escalation.store.expire",
                   return_value={**OVERDUE, "status": "expired"}), \
             patch("core.approvals.escalation.events.emit") as emit:
            out = escalation.sweep()
        self.assertEqual(1, out["expired"])
        self.assertEqual("approval.expired", emit.call_args.args[0])


class TestLocking(unittest.TestCase):

    def test_a_lost_lock_does_nothing_and_is_not_an_error(self):
        # Two uvicorn workers tick at the same time; only one may sweep.
        from core.approvals import escalation
        with patch("core.approvals.escalation._try_lock", return_value=False), \
             patch("core.approvals.escalation.store.due_for_escalation") as due:
            out = escalation.sweep()
        self.assertFalse(out["ran"])
        due.assert_not_called()

    def test_a_database_outage_does_not_kill_the_loop(self):
        from core.approvals import escalation
        with patch("core.approvals.escalation._try_lock", side_effect=RuntimeError("no db")):
            out = escalation.sweep()      # must not raise
        self.assertFalse(out["ran"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_approvals_escalation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.approvals.escalation'`

- [ ] **Step 3: Add `escalate` and `expire` to `core/approvals/store.py`**

```python
def escalate(request_id: str, *, new_role: str, sla_due_at) -> dict | None:
    """Replace WHO signs the current step. Does not change chain_index."""
    return query_one(
        f"""UPDATE approval_requests
            SET approver_role = %s, sla_due_at = %s, updated_at = NOW()
            WHERE request_id = %s AND status = 'pending'
            RETURNING {_COLUMNS}""",
        (new_role, sla_due_at, request_id),
    )


def expire(request_id: str) -> dict | None:
    return query_one(
        f"""UPDATE approval_requests
            SET status = 'expired', updated_at = NOW()
            WHERE request_id = %s AND status = 'pending'
            RETURNING {_COLUMNS}""",
        (request_id,),
    )
```

- [ ] **Step 4: Write `core/approvals/escalation.py`**

```python
"""
The 60-second sweeper: escalate overdue approvals, retry failed webhook
deliveries, expire stale requests.

Escalation is NOT chain advance, and conflating them would quietly drop a
required signature. Advancing the chain means one signature was collected and
the next is due. Escalating means the SAME step's SLA ran out and somebody else
must now sign it: approver_role changes, chain_index does not.

A PostgreSQL advisory lock keeps multiple uvicorn workers from all sweeping the
same tick. Losing the lock is the normal outcome for every worker but one — it
is not an error and is not logged as one.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from core.approvals import events, store, webhooks

_logger = logging.getLogger("core.approvals.escalation")

#: Arbitrary but fixed. Any other advisory-lock user must not reuse it.
_LOCK_KEY = 8123401


def _try_lock(conn) -> bool:
    from db.connection import query_one
    row = query_one("SELECT pg_try_advisory_lock(%s) AS got", (_LOCK_KEY,), conn=conn)
    return bool(row and row.get("got"))


def _unlock(conn) -> None:
    from db.connection import query_one
    query_one("SELECT pg_advisory_unlock(%s)", (_LOCK_KEY,), conn=conn)


def _escalate_one(row: dict) -> bool:
    chain = row.get("approval_chain") or []
    idx = int(row.get("chain_index") or 0)
    if not (0 <= idx < len(chain)):
        return False
    target = chain[idx].get("escalate_to")
    if not target:
        return False       # nowhere to go; expiry will close it eventually
    sla = datetime.now(timezone.utc) + timedelta(hours=int(chain[idx].get("sla_hours", 24)))
    updated = store.escalate(row["request_id"], new_role=target, sla_due_at=sla)
    if updated is None:
        return False
    events.emit("approval.escalated", updated,
                comment=f"SLA expired; escalated to {target}")
    return True


def sweep() -> dict:
    """One tick. Never raises; returns what it did."""
    result = {"ran": False, "escalated": 0, "expired": 0, "retried": 0}
    try:
        from db.connection import get_db
        with get_db() as conn:
            if not _try_lock(conn):
                return result           # another worker has this tick
            try:
                result["ran"] = True
                for row in store.due_for_escalation():
                    if _escalate_one(row):
                        result["escalated"] += 1
                for row in store.due_for_expiry():
                    updated = store.expire(row["request_id"])
                    if updated is not None:
                        events.emit("approval.expired", updated,
                                    comment="No decision before the deadline")
                        result["expired"] += 1
                result["retried"] = webhooks.retry_due()
            finally:
                _unlock(conn)
    except Exception:
        # A database outage must not kill the loop; the next tick retries.
        _logger.warning("Approval sweep failed", exc_info=True)
    return result


async def run_forever(interval: int = 60) -> None:
    while True:
        try:
            await asyncio.to_thread(sweep)
        except asyncio.CancelledError:
            raise
        except Exception:
            _logger.warning("Approval sweep loop error", exc_info=True)
        await asyncio.sleep(interval)


def start(interval: int = 60) -> asyncio.Task:
    return asyncio.create_task(run_forever(interval), name="approval-sweeper")


async def stop(task: asyncio.Task | None) -> None:
    if task is None:
        return
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass
```

- [ ] **Step 5: Start and stop it in `api/server.py` `lifespan`**

Just before the `yield`:

```python
    _sweeper = None
    try:
        from core.approvals.escalation import start as _start_sweeper
        _sweeper = _start_sweeper(int(os.environ.get("APPROVAL_SWEEP_SECONDS", "60")))
    except Exception as _sw_exc:
        _logger.warning("Approval sweeper failed to start: %s", _sw_exc)
    yield
    from core.approvals.escalation import stop as _stop_sweeper
    await _stop_sweeper(_sweeper)
```

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_approvals_escalation.py -v`
Expected: PASS (6 tests)

- [ ] **Step 7: Commit**

```bash
git add core/approvals/escalation.py core/approvals/store.py api/server.py tests/test_approvals_escalation.py
git commit -m "feat(approvals): SLA escalation, expiry and delivery retry sweeper"
```

---

### Task 13: Approver roles and the agent prompt

**Files:**
- Modify: `auth/rbac.py` (five approver roles)
- Modify: `agent/sap_agent.py` (three sentences in the system prompt)
- Test: `tests/test_approvals_roles.py`

**Interfaces:**
- Consumes: `core.authorization.WRITE_ROLES`
- Produces: `ROLE_MODULES` entries for `sales_manager`, `finance_manager`, `plant_manager`, `hr_approver`, `cfo`

- [ ] **Step 1: Write the failing test**

```python
"""Approver roles read; they do not write. The executor performs the write
outside the enforcement context, so an approver never needs write rights — and
granting them would let an approver bypass the queue entirely."""
import unittest


APPROVER_ROLES = ["sales_manager", "finance_manager", "plant_manager",
                  "hr_approver", "cfo"]


class TestApproverRoles(unittest.TestCase):

    def test_every_approver_role_exists(self):
        from auth.rbac import ROLE_MODULES
        for role in APPROVER_ROLES:
            self.assertIn(role, ROLE_MODULES)

    def test_no_approver_role_may_write(self):
        from core.authorization import WRITE_ROLES
        for role in APPROVER_ROLES:
            self.assertNotIn(role, WRITE_ROLES,
                             f"{role} could bypass the approval queue entirely")

    def test_approver_tool_access_is_read_only(self):
        from auth.rbac import get_allowed_tools
        from core.authorization import operation_of, WRITE
        for role in APPROVER_ROLES:
            for tool in get_allowed_tools([role]):
                self.assertNotEqual(WRITE, operation_of(tool),
                                    f"{role} can call the write tool {tool}")

    def test_each_approver_can_read_the_module_it_signs_for(self):
        from auth.rbac import get_allowed_tools
        expected = {
            "sales_manager":   "get_customer_info",
            "finance_manager": "get_customer_ledger",
            "plant_manager":   "get_production_order",
            "hr_approver":     "get_leave_balance",
            "cfo":             "get_customer_info",
        }
        for role, tool in expected.items():
            self.assertIn(tool, get_allowed_tools([role]),
                          f"{role} cannot inspect what it is asked to approve")

    def test_holding_both_a_writer_and_an_approver_role_still_permits_writing(self):
        # A user can request and approve — just never the same request.
        from core.authorization import role_may_write
        self.assertTrue(role_may_write(["sd_analyst", "sales_manager"]))


class TestPromptContract(unittest.TestCase):

    def test_the_prompt_forbids_claiming_a_document_before_it_exists(self):
        from agent.sap_agent import SAPAgent
        import inspect
        source = inspect.getsource(SAPAgent)
        self.assertIn("APPROVAL_REQUIRED", source)

    def test_the_prompt_does_not_contain_thresholds(self):
        # Thresholds live in policy_rules.json, where the model cannot see or
        # argue with them.
        from agent.sap_agent import SAPAgent
        import inspect
        source = inspect.getsource(SAPAgent)
        for number in ("50000", "500000", "50,000", "5,00,000"):
            self.assertNotIn(number, source,
                             "approval thresholds must not appear in the prompt")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_approvals_roles.py -v`
Expected: FAIL — `AssertionError: 'sales_manager' not found in ROLE_MODULES`

- [ ] **Step 3: Add the roles to `auth/rbac.py`**

In `ROLE_MODULES`, after `read_only`:

```python
    # ── Approver roles ────────────────────────────────────────────────────────
    # These sign off writes; they do not perform them. None appears in
    # core.authorization.WRITE_ROLES, so get_allowed_tools() filters every
    # write tool out of their grant. The executor performs the approved write
    # outside the enforcement context, which is why an approver needs read
    # access to the module it signs for and nothing more.
    "sales_manager":   ["sd", "tickets", "docs"],
    "finance_manager": ["fi_co", "sd", "receipt", "fi_co_re", "tickets", "docs"],
    "plant_manager":   ["pp", "mm", "tickets", "docs"],
    "hr_approver":     ["hr", "tickets", "docs"],
    "cfo":             ["fi_co", "sd", "mm", "pp", "receipt", "fi_co_re", "tickets", "docs"],
```

- [ ] **Step 4: Add the approval contract to the system prompt in `agent/sap_agent.py`**

`system_prompt_for()` has **two** return branches — the `trained_tool_json`
profile at line ~88 and the default f-string prompt at line ~121. The contract
must reach both, so define it once as a module-level constant and append it to
each, rather than pasting it twice and letting them drift:

```python
# Appended to every prompt profile. Deliberately short: enforcement lives in
# core/approvals/gate.py, below the model, so this covers only what code
# cannot — how to TALK about a queued write. No thresholds appear here; they
# live in policy_rules.json where the model cannot see or argue with them.
_APPROVAL_CONTRACT = """

APPROVALS — writes are governed. Never say a document was created, posted or
applied until a tool result actually contains its number. If a tool returns
status APPROVAL_REQUIRED, tell the user it is submitted, quote the request_id,
and say who it is waiting on — do not retry it and do not invent a document
number. If an approver asks for a change, re-issue the same tool call with the
changed parameters; never try to execute around the approval.
"""
```

Then append `+ _APPROVAL_CONTRACT` to both return statements. The text itself:

```
APPROVALS — writes are governed. Never say a document was created, posted or
applied until a tool result actually contains its number. If a tool returns
status APPROVAL_REQUIRED, tell the user it is submitted, quote the request_id,
and say who it is waiting on — do not retry it and do not invent a document
number. If an approver asks for a change, re-issue the same tool call with the
changed parameters; never try to execute around the approval.
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_approvals_roles.py -v`
Expected: PASS (7 tests)

Run: `python -m pytest tests/rbac_matrix.py tests/qa_master.py -q`
Expected: no new failures — the new roles are additive and hold no write tools.

- [ ] **Step 6: Commit**

```bash
git add auth/rbac.py agent/sap_agent.py tests/test_approvals_roles.py
git commit -m "feat(approvals): read-only approver roles and the agent's approval contract"
```

---
## Phase 3 — Frontend

**Verification note:** this project has no frontend test runner — `frontend/package.json`
has no vitest, jest or testing-library, and adding one is out of scope for this
plan. Phase 3 tasks are verified by `npm run lint`, `npm run build`, and the
manual smoke check written into each task. Do not invent a test framework to
satisfy a TDD step; the backend carries the test coverage for this feature.

### Task 14: Approvals API client and store

**Files:**
- Modify: `frontend/src/lib/api.js` (six functions)
- Create: `frontend/src/stores/approvals-store.js`

**Interfaces:**
- Consumes: `apiJson` from `frontend/src/lib/api.js`
- Produces:
  - `listApprovals({scope, status, action, limit, offset})`, `getApproval(id)`, `approveRequest(id, comment)`, `rejectRequest(id, comment)`, `editRequest(id, payloadPatch, comment)`, `approvalStats()`
  - `useApprovalsStore` with `{ scope, rows, detail, stats, loading, error, load(), open(id), close(), decide(id, verdict, comment), submitEdit(id, patch, comment), refreshStats() }`

- [ ] **Step 1: Add the API functions to `frontend/src/lib/api.js`**

Append, following the existing `apiJson` convention:

```javascript
// ─── Approvals ────────────────────────────────────────────────────────────────

export function listApprovals({ scope = 'inbox', status, action, limit = 50, offset = 0 } = {}) {
  const q = new URLSearchParams({ scope, limit: String(limit), offset: String(offset) })
  if (status) q.set('status', status)
  if (action) q.set('action', action)
  return apiJson(`/approvals?${q.toString()}`)
}

export function getApproval(id) {
  return apiJson(`/approvals/${encodeURIComponent(id)}`)
}

export function approveRequest(id, comment = '') {
  return apiJson(`/approvals/${encodeURIComponent(id)}/approve`, {
    method: 'POST', body: JSON.stringify({ comment }),
  })
}

export function rejectRequest(id, comment) {
  return apiJson(`/approvals/${encodeURIComponent(id)}/reject`, {
    method: 'POST', body: JSON.stringify({ comment }),
  })
}

export function editRequest(id, payloadPatch, comment) {
  return apiJson(`/approvals/${encodeURIComponent(id)}/edit`, {
    method: 'POST', body: JSON.stringify({ payload_patch: payloadPatch, comment }),
  })
}

export function approvalStats() {
  return apiJson('/approvals/stats')
}
```

- [ ] **Step 2: Create `frontend/src/stores/approvals-store.js`**

```javascript
import { create } from 'zustand'
import {
  listApprovals, getApproval, approveRequest, rejectRequest,
  editRequest, approvalStats,
} from '../lib/api.js'

// Mirrors the shape and naming of chat-store.js: primitive setters first,
// then the async actions that own their own loading and error state.
const useApprovalsStore = create((set, get) => ({
  scope: 'inbox',           // 'inbox' | 'mine' | 'all'
  rows: [],
  detail: null,             // full request + events, when one is open
  stats: { inbox: 0 },
  loading: false,
  acting: false,            // a decision is in flight
  error: null,

  setScope: (scope) => { set({ scope, detail: null }); get().load() },
  close: () => set({ detail: null }),

  load: async () => {
    set({ loading: true, error: null })
    try {
      const data = await listApprovals({ scope: get().scope })
      set({ rows: data.requests || [], loading: false })
    } catch (e) {
      set({ error: e.message, loading: false })
    }
  },

  open: async (id) => {
    set({ error: null })
    try {
      set({ detail: await getApproval(id) })
    } catch (e) {
      set({ error: e.message })
    }
  },

  decide: async (id, verdict, comment) => {
    set({ acting: true, error: null })
    try {
      if (verdict === 'approve') await approveRequest(id, comment)
      else await rejectRequest(id, comment)
      set({ acting: false, detail: null })
      await get().load()
      await get().refreshStats()
      return true
    } catch (e) {
      set({ error: e.message, acting: false })
      return false
    }
  },

  submitEdit: async (id, patch, comment) => {
    set({ acting: true, error: null })
    try {
      const created = await editRequest(id, patch, comment)
      set({ acting: false, detail: null })
      await get().load()
      await get().refreshStats()
      return created
    } catch (e) {
      set({ error: e.message, acting: false })
      return null
    }
  },

  refreshStats: async () => {
    try {
      set({ stats: await approvalStats() })
    } catch {
      // A failed badge poll is not worth surfacing to the user.
    }
  },
}))

export default useApprovalsStore
```

- [ ] **Step 3: Verify**

Run: `cd frontend && npm run lint`
Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.js frontend/src/stores/approvals-store.js
git commit -m "feat(approvals): frontend api client and approvals store"
```

---

### Task 15: Approvals components

Built from scratch — no UI component library, per the project's standing rule.
Reuse the existing class names (`btn`, `btn-primary`, `btn-secondary`,
`form-input`, `form-label`, `st-warning`, `result-banner`) so the panel inherits
the app's design tokens rather than introducing a second visual language.

**Files:**
- Create: `frontend/src/components/approvals/ApprovalCard.jsx`
- Create: `frontend/src/components/approvals/ApprovalDetail.jsx`
- Create: `frontend/src/components/approvals/ApprovalsView.jsx`
- Modify: `frontend/src/App.css` (one `.approvals-*` block)

**Interfaces:**
- Consumes: `useApprovalsStore`
- Produces: `<ApprovalsView onClose={fn} />` — a full-screen overlay; `<ApprovalCard request onOpen />`; `<ApprovalDetail />`

- [ ] **Step 1: Create `ApprovalCard.jsx`**

```jsx
// One row in the inbox: what it is, how much, how urgent, who it waits on.
// Amount and SLA are the two things an approver scans for, so they are the two
// things that get visual weight.

function money(amount, currency) {
  if (amount === null || amount === undefined) return null
  return `${currency || 'INR'} ${Number(amount).toLocaleString('en-IN')}`
}

function age(createdAt) {
  if (!createdAt) return ''
  const hours = (Date.now() - new Date(createdAt).getTime()) / 3600000
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))}m ago`
  if (hours < 24) return `${Math.round(hours)}h ago`
  return `${Math.round(hours / 24)}d ago`
}

export default function ApprovalCard({ request, onOpen }) {
  const overdue = request.sla_due_at && new Date(request.sla_due_at) < new Date()
  return (
    <button className="approvals-card" onClick={() => onOpen(request.request_id)}>
      <div className="approvals-card-main">
        <span className="approvals-card-summary">{request.summary}</span>
        <span className="approvals-card-meta">
          {request.request_id} · {request.action} · {age(request.created_at)}
        </span>
      </div>
      <div className="approvals-card-side">
        {money(request.amount, request.currency) && (
          <span className="approvals-card-amount">{money(request.amount, request.currency)}</span>
        )}
        <span className={`approvals-chip ${overdue ? 'st-warning' : ''}`}>
          {request.status === 'pending' ? `waiting on ${request.approver_role}` : request.status}
        </span>
        {(request.risk_flags || []).map(flag => (
          <span key={flag} className="approvals-chip approvals-chip-risk">{flag.replace(/_/g, ' ')}</span>
        ))}
      </div>
    </button>
  )
}
```

- [ ] **Step 2: Create `ApprovalDetail.jsx`**

```jsx
import { useState } from 'react'
import useApprovalsStore from '../../stores/approvals-store.js'

// The approve/reject/edit surface. Reject and edit both require a comment,
// because "no" without a reason sends the requester back to guess.
export default function ApprovalDetail() {
  const { detail, acting, error, decide, submitEdit, close } = useApprovalsStore()
  const [comment, setComment] = useState('')
  const [patchText, setPatchText] = useState('')
  const [editing, setEditing] = useState(false)
  const [patchError, setPatchError] = useState(null)

  if (!detail) return null
  const canDecide = detail.can_decide

  const onEdit = async () => {
    let patch
    try {
      patch = JSON.parse(patchText || '{}')
    } catch {
      setPatchError('That is not valid JSON.')
      return
    }
    setPatchError(null)
    await submitEdit(detail.request_id, patch, comment || 'Edited by approver')
  }

  return (
    <div className="approvals-detail">
      <div className="approvals-detail-header">
        <div>
          <div className="approvals-detail-title">{detail.summary}</div>
          <div className="approvals-card-meta">
            {detail.request_id} · requested by {detail.requested_by}
            {detail.supersedes ? ` · replaces ${detail.supersedes}` : ''}
          </div>
        </div>
        <button className="btn btn-secondary" onClick={close}>Close</button>
      </div>

      {!canDecide && (
        <div className="result-banner">
          {detail.required_role
            ? `Waiting on ${detail.required_role}. You cannot decide this request.`
            : `This request is ${detail.status}.`}
        </div>
      )}
      {error && <div className="result-banner error">{error}</div>}

      <div className="approvals-detail-grid">
        <section>
          <div className="form-section">Payload</div>
          <pre className="approvals-pre">{JSON.stringify(detail.payload, null, 2)}</pre>
        </section>
        <section>
          <div className="form-section">Resolved from SAP</div>
          <pre className="approvals-pre">{JSON.stringify(detail.context, null, 2)}</pre>
        </section>
      </div>

      <div className="form-section">History</div>
      <ul className="approvals-trail">
        {(detail.events || []).map(e => (
          <li key={e.event_id}>
            <b>{e.event.replace('approval.', '')}</b>
            {e.actor ? ` — ${e.actor}` : ''}{e.comment ? `: ${e.comment}` : ''}
          </li>
        ))}
      </ul>

      {canDecide && (
        <div className="approvals-actions">
          <input
            className="form-input"
            placeholder="Comment (required to reject or edit)"
            value={comment}
            onChange={e => setComment(e.target.value)}
          />
          {editing && (
            <>
              <textarea
                className="form-input mono"
                rows={4}
                placeholder='Payload changes as JSON, e.g. {"qty": 40}'
                value={patchText}
                onChange={e => setPatchText(e.target.value)}
              />
              {patchError && <div className="result-banner error">{patchError}</div>}
              <span className="form-hint">
                An edit creates a replacement request and re-runs the approval policy,
                so a larger amount may need more signatures.
              </span>
            </>
          )}
          <div className="approvals-buttons">
            <button className="btn btn-primary" disabled={acting}
              onClick={() => decide(detail.request_id, 'approve', comment)}>
              {acting ? 'Working…' : 'Approve'}
            </button>
            <button className="btn btn-secondary" disabled={acting || !comment.trim()}
              onClick={() => decide(detail.request_id, 'reject', comment)}>
              Reject
            </button>
            {editing
              ? <button className="btn btn-secondary" disabled={acting || !comment.trim()} onClick={onEdit}>
                  Submit edit
                </button>
              : <button className="btn btn-secondary" onClick={() => setEditing(true)}>
                  Edit…
                </button>}
          </div>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 3: Create `ApprovalsView.jsx`**

```jsx
import { useEffect } from 'react'
import useApprovalsStore from '../../stores/approvals-store.js'
import ApprovalCard from './ApprovalCard.jsx'
import ApprovalDetail from './ApprovalDetail.jsx'

const SCOPES = [
  ['inbox', 'Waiting on me'],
  ['mine', 'My requests'],
]

export default function ApprovalsView({ onClose, isAdmin }) {
  const { scope, rows, detail, loading, error, load, setScope, open } = useApprovalsStore()
  const scopes = isAdmin ? [...SCOPES, ['all', 'All']] : SCOPES

  useEffect(() => { load() }, [load])

  return (
    <div className="approvals-overlay" onClick={onClose}>
      <div className="approvals-panel" onClick={e => e.stopPropagation()}>
        <div className="approvals-header">
          <span className="approvals-title">Approvals</span>
          <div className="approvals-tabs">
            {scopes.map(([key, label]) => (
              <button key={key}
                className={`vis-tab ${scope === key ? 'active' : ''}`}
                onClick={() => setScope(key)}>{label}</button>
            ))}
          </div>
          <button className="btn btn-secondary" onClick={onClose}>Close</button>
        </div>

        {error && <div className="result-banner error">{error}</div>}

        {detail ? <ApprovalDetail /> : (
          <div className="approvals-list">
            {loading && <p className="approvals-empty">Loading…</p>}
            {!loading && rows.length === 0 && (
              <p className="approvals-empty">
                {scope === 'inbox' ? 'Nothing is waiting on you.' : 'No requests yet.'}
              </p>
            )}
            {rows.map(r => (
              <ApprovalCard key={r.request_id} request={r} onOpen={open} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Add the styles to `frontend/src/App.css`**

Append one block using the existing CSS custom properties (`--bg-subtle`,
`--border`, `--text-muted`, `--r-lg`, `--font-mono`) so the panel inherits the
app's tokens:

```css
/* ─── Approvals ──────────────────────────────────────────────────────────── */
.approvals-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.45);
  display: flex; align-items: center; justify-content: center; z-index: 60; }
.approvals-panel { background: var(--bg); border: 1px solid var(--border);
  border-radius: var(--r-lg); width: min(1040px, 94vw); max-height: 88vh;
  overflow: auto; padding: 20px; }
.approvals-header { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.approvals-title { font-weight: 700; font-size: 15px; margin-right: auto; }
.approvals-tabs { display: flex; gap: 6px; }
.approvals-list { display: flex; flex-direction: column; gap: 8px; }
.approvals-card { display: flex; gap: 12px; align-items: center; width: 100%;
  text-align: left; background: var(--bg-subtle); border: 1px solid var(--border);
  border-radius: var(--r-lg); padding: 12px 14px; cursor: pointer; }
.approvals-card:hover { border-color: var(--text-muted); }
.approvals-card-main { display: flex; flex-direction: column; gap: 4px; flex: 1; min-width: 0; }
.approvals-card-summary { font-size: 13.5px; font-weight: 600; }
.approvals-card-meta { font-size: 11.5px; color: var(--text-muted); font-family: var(--font-mono); }
.approvals-card-side { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.approvals-card-amount { font-weight: 700; font-size: 13.5px; white-space: nowrap; }
.approvals-chip { font-size: 11px; padding: 2px 8px; border-radius: 999px;
  border: 1px solid var(--border); color: var(--text-muted); white-space: nowrap; }
.approvals-chip-risk { border-color: var(--warning); color: var(--warning); }
.approvals-detail-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
.approvals-detail-title { font-size: 14.5px; font-weight: 700; }
.approvals-detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 16px 0; }
.approvals-pre { background: var(--bg-subtle); border: 1px solid var(--border);
  border-radius: var(--r-lg); padding: 12px; font-family: var(--font-mono);
  font-size: 11.5px; overflow: auto; max-height: 240px; }
.approvals-trail { list-style: none; padding: 0; margin: 8px 0 16px;
  font-size: 12.5px; display: flex; flex-direction: column; gap: 6px; }
.approvals-actions { display: flex; flex-direction: column; gap: 10px;
  border-top: 1px solid var(--border); padding-top: 14px; }
.approvals-buttons { display: flex; gap: 8px; }
.approvals-empty { font-size: 13px; color: var(--text-muted); padding: 24px 0; text-align: center; }
.approvals-badge { background: var(--warning); color: #fff; border-radius: 999px;
  font-size: 10.5px; padding: 1px 6px; margin-left: 6px; font-weight: 700; }
@media (max-width: 720px) { .approvals-detail-grid { grid-template-columns: 1fr; } }
```

- [ ] **Step 5: Verify**

Run: `cd frontend && npm run lint && npm run build`
Expected: build succeeds, no new lint errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/approvals frontend/src/App.css
git commit -m "feat(approvals): approvals inbox, card and detail components"
```

---

### Task 16: Wire the panel into the app and render queued writes in chat

**Files:**
- Modify: `frontend/src/App.jsx` (sidebar entry, badge poll, overlay mount)
- Modify: `frontend/src/components/chat/MessageRow.jsx` (render `APPROVAL_REQUIRED`)

**Interfaces:**
- Consumes: `ApprovalsView`, `useApprovalsStore`
- Produces: nothing further

- [ ] **Step 1: Mount the panel in `frontend/src/App.jsx`**

Add the import beside the existing `AIConfiguration` import at line 15:

```javascript
import ApprovalsView from './components/approvals/ApprovalsView'
import useApprovalsStore from './stores/approvals-store'
```

In the top-level app component (the one that owns `sidebarCollapsed` at line
2573), add state and a badge poll:

```javascript
  const [showApprovals, setShowApprovals] = useState(false)
  const approvalCount = useApprovalsStore(s => s.stats.inbox)
  const refreshApprovalStats = useApprovalsStore(s => s.refreshStats)

  // Poll rather than stream: an approval queue changes on human timescales,
  // and a websocket for a number is not worth the reconnect logic.
  useEffect(() => {
    refreshApprovalStats()
    const t = setInterval(refreshApprovalStats, 30000)
    return () => clearInterval(t)
  }, [refreshApprovalStats])
```

Render the overlay next to the existing `<DataPanel />` at the end of the
component's return:

```jsx
      {showApprovals && (
        <ApprovalsView isAdmin={isAdmin} onClose={() => setShowApprovals(false)} />
      )}
      <DataPanel />
```

- [ ] **Step 2: Add the sidebar entry**

In the expanded sidebar, immediately after the "New chat" container at line
2438-2442, add:

```jsx
      <div className="sidebar-new-chat-container">
        <button className="sidebar-new-chat-btn" onClick={onOpenApprovals}>
          Approvals
          {approvalCount > 0 && <span className="approvals-badge">{approvalCount}</span>}
        </button>
      </div>
```

In the collapsed sidebar, after the collapsed "New chat" button at line 2381,
add the same action as an icon button:

```jsx
        <button className="sidebar-collapsed-icon-btn" onClick={onOpenApprovals} title="Approvals">
          <Svg><path d="M9 11l3 3L22 4" /><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" /></Svg>
          {approvalCount > 0 && <span className="approvals-badge">{approvalCount}</span>}
        </button>
```

Both need `onOpenApprovals` and `approvalCount` threaded through the sidebar
component's props, alongside the existing `onNewChat` and `onLogout`.

- [ ] **Step 3: Render the queued state in `frontend/src/components/chat/MessageRow.jsx`**

Beside the existing `ReceiptWidget` conditional at line 153, add:

```jsx
        {msg.tool_result?.status === 'APPROVAL_REQUIRED' && (
          <div className="approvals-card" style={{ cursor: 'default', marginTop: 10 }}>
            <div className="approvals-card-main">
              <span className="approvals-card-summary">
                {msg.tool_result.approval?.summary || 'Submitted for approval'}
              </span>
              <span className="approvals-card-meta">
                {msg.tool_result.request_id} · waiting on{' '}
                {msg.tool_result.approval?.approver_role} · nothing written to SAP yet
              </span>
            </div>
            <div className="approvals-card-side">
              {msg.tool_result.approval?.amount != null && (
                <span className="approvals-card-amount">
                  {msg.tool_result.approval.currency}{' '}
                  {Number(msg.tool_result.approval.amount).toLocaleString('en-IN')}
                </span>
              )}
            </div>
          </div>
        )}
```

Both `/chat` and `/chat/stream` deliver this payload in `tool_result`, so one
branch covers both paths.

- [ ] **Step 4: Verify**

Run: `cd frontend && npm run lint && npm run build`
Expected: build succeeds.

Manual smoke check, with the API running:
1. Sign in as a user holding `sd_analyst`.
2. Ask for a sales order worth more than ₹50,000. Confirm when prompted — the
   confirmation text should name the amount and the approver role.
3. The reply should say "Submitted for approval as apr_…", and the card should
   render under it.
4. Sign in as a user holding `sales_manager`. The sidebar badge shows 1; the
   inbox lists the request; approving it executes and the detail shows the SAP
   document number.
5. Sign back in as the requester and confirm the Approve button is refused —
   `can_decide` is false for your own request.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.jsx frontend/src/components/chat/MessageRow.jsx
git commit -m "feat(approvals): approvals panel entry point and queued-write chat state"
```

---

## Environment variables

Add to `.env.example` as part of Task 8, with these exact names:

```bash
# ── Approval layer ────────────────────────────────────────────────────────────
# Outbound webhook target. The feature is inert when unset.
APPROVAL_WEBHOOK_URL=
# Shared secret for BOTH directions: signs outbound, verifies inbound.
APPROVAL_WEBHOOK_SECRET=
# On-premise receivers are routinely on private networks. Off by default.
APPROVAL_WEBHOOK_ALLOW_PRIVATE=false
APPROVAL_WEBHOOK_TIMEOUT=5
APPROVAL_WEBHOOK_MAX_ATTEMPTS=8
# Sweeper tick: escalation, delivery retry, expiry.
APPROVAL_SWEEP_SECONDS=60
# Override the shipped thresholds without editing the package.
APPROVALS_POLICY_PATH=
```

## Definition of done

- [ ] `python -m pytest tests/ -q` passes with no new failures.
- [ ] `cd frontend && npm run lint && npm run build` succeeds.
- [ ] Every tool in `core.authorization.WRITE_TOOLS` has an entry in
      `policy_rules.json` and in `gate.DOC_FIELDS` — two tests assert this, so a
      write tool added later cannot silently escape the layer.
- [ ] The manual smoke check in Task 16 passes end to end.
