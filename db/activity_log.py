"""
DB-backed activity logging for every API request.

Two write paths:
  - middleware  : writes basic HTTP info for ALL requests (log_source='middleware')
  - audit       : log_request() writes rich detail for chat/research/autonomous (log_source='audit')

All DB writes are fire-and-forget — errors are logged at DEBUG level and
never propagate to the caller so a DB outage never breaks the API.

async_write_log() is provided for non-blocking writes in streaming endpoints.
"""
import json
import logging
import uuid
from decimal import Decimal
from typing import Any

from psycopg.rows import dict_row

_logger = logging.getLogger("db.activity_log")


# ── Helpers ───────────────────────────────────────────────────────────────────

class _SafeEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)


def _j(obj) -> str | None:
    if obj is None:
        return None
    try:
        return json.dumps(obj, cls=_SafeEncoder)
    except Exception:
        return str(obj)


def _ts(dt) -> str | None:
    if dt is None:
        return None
    try:
        return dt.isoformat()
    except Exception:
        return str(dt)


# ── Write ─────────────────────────────────────────────────────────────────────

def write_log(
    *,
    request_id: str | None = None,
    user_id: str | None = None,
    user_roles: list[str] | None = None,
    client_ip: str | None = None,
    method: str = "GET",
    endpoint: str,
    status_code: int | None = None,
    status: str = "ok",
    query_text: str | None = None,
    tool_called: str | None = None,
    tool_parameters: dict | None = None,
    sap_source: dict | None = None,
    response_summary: str | None = None,
    duration_ms: int = 0,
    error_message: str | None = None,
    log_source: str = "middleware",
) -> str:
    """Persist one activity record. Returns the request_id used."""
    rid = request_id or str(uuid.uuid4())
    try:
        from db.connection import get_db
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO request_logs
                       (request_id, user_id, user_roles, client_ip, method, endpoint,
                        status_code, status, query_text, tool_called, tool_parameters,
                        sap_source, response_summary, duration_ms, error_message, log_source)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        rid,
                        user_id,
                        _j(user_roles),
                        client_ip,
                        method,
                        endpoint,
                        status_code,
                        status,
                        query_text[:2000] if query_text else None,
                        tool_called,
                        _j(tool_parameters),
                        _j(sap_source),
                        response_summary[:500] if response_summary else None,
                        duration_ms,
                        error_message[:1000] if error_message else None,
                        log_source,
                    ),
                )
    except Exception as exc:
        _logger.debug("activity_log.write_log failed: %s", exc)
    return rid


async def async_write_log(
    *,
    request_id: str | None = None,
    user_id: str | None = None,
    user_roles: list[str] | None = None,
    client_ip: str | None = None,
    method: str = "GET",
    endpoint: str,
    status_code: int | None = None,
    status: str = "ok",
    query_text: str | None = None,
    tool_called: str | None = None,
    tool_parameters: dict | None = None,
    sap_source: dict | None = None,
    response_summary: str | None = None,
    duration_ms: int = 0,
    error_message: str | None = None,
    log_source: str = "middleware",
) -> str:
    """Async version of write_log — non-blocking for streaming event_generator."""
    rid = request_id or str(uuid.uuid4())
    try:
        from db.connection import async_execute
        await async_execute(
            """INSERT INTO request_logs
               (request_id, user_id, user_roles, client_ip, method, endpoint,
                status_code, status, query_text, tool_called, tool_parameters,
                sap_source, response_summary, duration_ms, error_message, log_source)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                rid,
                user_id,
                _j(user_roles),
                client_ip,
                method,
                endpoint,
                status_code,
                status,
                query_text[:2000] if query_text else None,
                tool_called,
                _j(tool_parameters),
                _j(sap_source),
                response_summary[:500] if response_summary else None,
                duration_ms,
                error_message[:1000] if error_message else None,
                log_source,
            ),
        )
    except Exception as exc:
        _logger.debug("activity_log.async_write_log failed: %s", exc)
    return rid


# ── Query ─────────────────────────────────────────────────────────────────────

def query_logs(
    *,
    user_id: str | None = None,
    endpoint: str | None = None,
    status: str | None = None,
    method: str | None = None,
    log_source: str | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return filtered activity log records, newest first."""
    try:
        from db.connection import get_db
        where, params = _build_where(
            user_id=user_id, endpoint=endpoint, status=status,
            method=method, log_source=log_source,
            from_ts=from_ts, to_ts=to_ts,
        )
        params += [limit, offset]
        with get_db() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"SELECT * FROM request_logs {where} "
                    f"ORDER BY timestamp DESC LIMIT %s OFFSET %s",
                    params,
                )
                rows = [dict(r) for r in cur.fetchall()]
        return _normalise_rows(rows)
    except Exception as exc:
        _logger.debug("activity_log.query_logs failed: %s", exc)
        return []


def count_logs(
    *,
    user_id: str | None = None,
    endpoint: str | None = None,
    status: str | None = None,
    method: str | None = None,
    log_source: str | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
) -> int:
    try:
        from db.connection import get_db
        where, params = _build_where(
            user_id=user_id, endpoint=endpoint, status=status,
            method=method, log_source=log_source,
            from_ts=from_ts, to_ts=to_ts,
        )
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM request_logs {where}", params)
                row = cur.fetchone()
                return row[0] if row else 0
    except Exception as exc:
        _logger.debug("activity_log.count_logs failed: %s", exc)
        return 0


def get_stats(*, from_ts: str | None = None, to_ts: str | None = None) -> dict[str, Any]:
    """Return aggregate analytics for the admin dashboard."""
    try:
        from db.connection import get_db
        where, params = _build_where(from_ts=from_ts, to_ts=to_ts)
        with get_db() as conn:
            cur = conn.cursor(row_factory=dict_row)

            # Summary totals
            cur.execute(
                f"SELECT COUNT(*) AS total, "
                f"SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS errors, "
                f"SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) AS successes, "
                f"ROUND(AVG(duration_ms)) AS avg_duration_ms, "
                f"MAX(duration_ms) AS max_duration_ms "
                f"FROM request_logs {where}",
                params,
            )
            summary = dict(cur.fetchone() or {})

            # Requests per endpoint
            cur.execute(
                f"SELECT endpoint, COUNT(*) AS total, "
                f"SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS errors, "
                f"ROUND(AVG(duration_ms)) AS avg_ms "
                f"FROM request_logs {where} "
                f"GROUP BY endpoint ORDER BY total DESC LIMIT 30",
                params,
            )
            by_endpoint = [dict(r) for r in cur.fetchall()]

            # Requests per user
            cur.execute(
                f"SELECT user_id, COUNT(*) AS total, "
                f"SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS errors "
                f"FROM request_logs {where} "
                f"GROUP BY user_id ORDER BY total DESC LIMIT 30",
                params,
            )
            by_user = [dict(r) for r in cur.fetchall()]

            # Tool usage
            cur.execute(
                f"SELECT tool_called, COUNT(*) AS total "
                f"FROM request_logs {where} "
                f"WHERE tool_called IS NOT NULL "
                f"GROUP BY tool_called ORDER BY total DESC LIMIT 30",
                params,
            )
            by_tool = [dict(r) for r in cur.fetchall()]

            # Errors breakdown
            cur.execute(
                f"SELECT endpoint, status_code, COUNT(*) AS count, "
                f"LEFT(error_message, 120) AS sample_error "
                f"FROM request_logs {where} "
                f"WHERE status = 'error' "
                f"GROUP BY endpoint, status_code, sample_error ORDER BY count DESC LIMIT 20",
                params,
            )
            errors = [dict(r) for r in cur.fetchall()]

            # Hourly activity (PostgreSQL date_trunc)
            cur.execute(
                f"SELECT TO_CHAR(DATE_TRUNC('hour', timestamp), 'YYYY-MM-DD HH24:00') AS hour, "
                f"COUNT(*) AS total, "
                f"SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS errors "
                f"FROM request_logs {where} "
                f"GROUP BY DATE_TRUNC('hour', timestamp) ORDER BY DATE_TRUNC('hour', timestamp) DESC LIMIT 48",
                params,
            )
            hourly = [dict(r) for r in cur.fetchall()]

        return {
            "summary": {
                "total":           int(summary.get("total") or 0),
                "errors":          int(summary.get("errors") or 0),
                "successes":       int(summary.get("successes") or 0),
                "avg_duration_ms": float(summary.get("avg_duration_ms") or 0),
                "max_duration_ms": int(summary.get("max_duration_ms") or 0),
            },
            "by_endpoint": by_endpoint,
            "by_user":     by_user,
            "by_tool":     by_tool,
            "errors":      errors,
            "hourly":      hourly,
        }
    except Exception as exc:
        _logger.debug("activity_log.get_stats failed: %s", exc)
        return {"summary": {}, "by_endpoint": [], "by_user": [], "by_tool": [], "errors": [], "hourly": []}


# ── DB schema auto-migration (PostgreSQL DDL) ─────────────────────────────────

_MIGRATION_SQL = [
    # request_logs table
    """CREATE TABLE IF NOT EXISTS request_logs (
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
        duration_ms      INT,
        error_message    TEXT,
        log_source       VARCHAR(20)   DEFAULT 'middleware'
    )""",

    "CREATE INDEX IF NOT EXISTS idx_rl_ts       ON request_logs(timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS idx_rl_user     ON request_logs(user_id, timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS idx_rl_endpoint ON request_logs(endpoint, timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS idx_rl_status   ON request_logs(status, timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS idx_rl_request  ON request_logs(request_id)",
    "CREATE INDEX IF NOT EXISTS idx_rl_roles_gin  ON request_logs USING GIN (user_roles)",
    "CREATE INDEX IF NOT EXISTS idx_rl_params_gin ON request_logs USING GIN (tool_parameters)",

    # conversations table
    """CREATE TABLE IF NOT EXISTS conversations (
        id          INTEGER       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        user_id     VARCHAR(50)   NOT NULL,
        session_id  VARCHAR(100)  NOT NULL,
        title       VARCHAR(255),
        created_at  TIMESTAMPTZ   DEFAULT NOW(),
        updated_at  TIMESTAMPTZ   DEFAULT NOW(),
        CONSTRAINT uq_user_session UNIQUE (user_id, session_id)
    )""",

    "CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_id, updated_at DESC)",

    """CREATE OR REPLACE FUNCTION _set_updated_at()
       RETURNS TRIGGER AS $$
       BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
       $$ LANGUAGE plpgsql""",

    """DO $$ BEGIN
         IF NOT EXISTS (
           SELECT 1 FROM pg_trigger WHERE tgname = 'trg_conv_updated_at'
         ) THEN
           CREATE TRIGGER trg_conv_updated_at
             BEFORE UPDATE ON conversations
             FOR EACH ROW EXECUTE FUNCTION _set_updated_at();
         END IF;
       END $$""",

    # messages table
    """CREATE TABLE IF NOT EXISTS messages (
        id              INTEGER       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        conversation_id INTEGER       NOT NULL,
        role            VARCHAR(10)   NOT NULL CHECK (role IN ('user', 'bot')),
        content         TEXT          NOT NULL,
        tool_called     VARCHAR(100),
        tool_result     JSONB,
        sap_source      JSONB,
        abap_check      JSONB,
        abap_code       JSONB,
        report          JSONB,
        status_steps    JSONB         DEFAULT '[]'::jsonb,
        created_at      TIMESTAMPTZ   DEFAULT NOW(),
        FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
    )""",

    # Migration: add status_steps to existing installations that predate this column
    "ALTER TABLE messages ADD COLUMN IF NOT EXISTS status_steps JSONB DEFAULT '[]'::jsonb",

    "CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id, created_at ASC)",
]


def run_migrations() -> None:
    """Create all required tables if they don't exist. Called at server startup."""
    try:
        from db.connection import get_db
        with get_db() as conn:
            with conn.cursor() as cur:
                for ddl in _MIGRATION_SQL:
                    cur.execute(ddl)
        _logger.info("DB migrations applied successfully.")
    except Exception as exc:
        _logger.warning("DB migration failed (DB may not be available): %s", exc)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _build_where(**filters) -> tuple[str, list]:
    clauses, params = [], []
    if filters.get("user_id"):
        clauses.append("user_id = %s"); params.append(filters["user_id"])
    if filters.get("endpoint"):
        clauses.append("endpoint LIKE %s"); params.append(f"%{filters['endpoint']}%")
    if filters.get("status"):
        clauses.append("status = %s"); params.append(filters["status"])
    if filters.get("method"):
        clauses.append("method = %s"); params.append(filters["method"].upper())
    if filters.get("log_source"):
        clauses.append("log_source = %s"); params.append(filters["log_source"])
    if filters.get("from_ts"):
        clauses.append("timestamp >= %s"); params.append(filters["from_ts"])
    if filters.get("to_ts"):
        clauses.append("timestamp <= %s"); params.append(filters["to_ts"])
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def _normalise_rows(rows: list[dict]) -> list[dict]:
    for r in rows:
        if r.get("timestamp"):
            r["timestamp"] = _ts(r["timestamp"])
        # psycopg3 with JSONB returns Python dicts/lists directly — no json.loads needed
        # The isinstance(val, str) guard below is kept for safety
        for col in ("user_roles", "tool_parameters", "sap_source"):
            val = r.get(col)
            if isinstance(val, str):
                try:
                    r[col] = json.loads(val)
                except Exception:
                    pass
    return rows
