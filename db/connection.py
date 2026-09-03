"""
PostgreSQL Connection Manager for SAP AI Agent (psycopg3 / psycopg[binary,pool]).

Two connection layers:
  Sync  — used by all SAP module functions (fi_co, mm, sd, hr, pp, abap)
  Async — used by streaming endpoint for non-blocking chat-history / audit writes

Public sync API (unchanged signatures from MySQL version):
    get_db()         — context manager yielding a psycopg3 Connection
    query_one(sql, params) -> dict | None
    query_all(sql, params) -> list[dict]
    execute(sql, params)   -> rowcount int
    is_connected()         -> bool

Public async API (new, for streaming event_generator):
    open_async_pool()      — call from FastAPI lifespan startup
    close_async_pool()     — call from FastAPI lifespan shutdown
    async_query_one(sql, params) -> dict | None
    async_query_all(sql, params) -> list[dict]
    async_execute(sql, params)   -> rowcount int

Environment variables (DB_* take priority over config.json):
    DB_HOST, DB_PORT (default 5432), DB_USER, DB_PASSWORD, DB_NAME, DB_POOL_SIZE
    DB_POOL_TIMEOUT      seconds to wait for a pooled connection (default 3)
    DB_BREAKER_COOLDOWN  seconds to fail fast after an outage (default 10)
"""
import logging
import os
import time
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, AsyncConnectionPool, PoolTimeout

_logger = logging.getLogger("db.connection")


# ── DSN builder ───────────────────────────────────────────────────────────────

def _conninfo() -> str:
    """Build a libpq-style connection string from env vars or defaults."""
    # Priority 1: standard DATABASE_URL (Railway, Heroku, etc.)
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        return db_url

    # Priority 2: individual DB_* variables
    host     = os.environ.get("DB_HOST",     "localhost")
    port     = int(os.environ.get("DB_PORT", "5432"))
    user     = os.environ.get("DB_USER",     "sap_agent")
    password = os.environ.get("DB_PASSWORD", "")
    database = os.environ.get("DB_NAME",     "sap_agent")
    # libpq defaults to sslmode=prefer, which silently falls back to plaintext.
    # Pin it explicitly; DB_SSLMODE=require is the default outside development
    # (finding F-09).
    default_mode = "prefer" if os.environ.get("APP_ENV", "development").lower() == "development" else "require"
    sslmode = os.environ.get("DB_SSLMODE", default_mode)
    return (
        f"host={host} port={port} dbname={database} "
        f"user={user} password={password} connect_timeout=10 sslmode={sslmode}"
    )


def conninfo() -> str:
    """Public accessor for the libpq connection string.

    _conninfo() builds it from DATABASE_URL or the individual DB_* env vars;
    this is the one place outside this module that should ever need it (a
    boot-time reachability probe that must NOT go through the shared pool,
    which now also carries breaker state a boot probe has no business
    tripping). Exists so a caller never has to duplicate the DSN-building
    logic above.
    """
    return _conninfo()


# ── Sync connection pool ───────────────────────────────────────────────────────

_pool: ConnectionPool | None = None


#: How long a caller may wait for a pooled connection. psycopg's own default is
#: 30 seconds, which is far too patient for anything on a request path: with
#: PostgreSQL down, every caller sat for the full 30 s before finding out, and
#: the request-logging middleware did that wait on the event loop, taking the
#: whole worker with it. A few seconds is long enough to ride out contention
#: and short enough that an outage surfaces as a fast, honest failure.
_POOL_TIMEOUT = float(os.environ.get("DB_POOL_TIMEOUT", "3"))


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        pool_size = int(os.environ.get("DB_POOL_SIZE", "5"))
        _pool = ConnectionPool(
            _conninfo(),
            min_size=2,
            max_size=pool_size,
            timeout=_POOL_TIMEOUT,
            open=True,
        )
        _logger.info(
            "PostgreSQL sync pool ready (max_size=%d, timeout=%.1fs)",
            pool_size, _POOL_TIMEOUT,
        )
    return _pool


# ── Availability circuit breaker ──────────────────────────────────────────────
#
# A bounded pool timeout stops one caller waiting forever, but every caller
# still pays that timeout to rediscover the same outage — /health pays it more
# than once and took 12 seconds. After a connection failure the database is
# treated as down for a short cooldown and callers are refused immediately;
# the first caller after the cooldown retries and, if it succeeds, service
# resumes at once.

class DatabaseUnavailable(Exception):
    """Raised instead of waiting, while the database is known to be down."""


_BREAKER_COOLDOWN = float(os.environ.get("DB_BREAKER_COOLDOWN", "10"))
_unavailable_until: float = 0.0


def circuit_open() -> bool:
    """True while the database is known down and callers should fail fast."""
    return time.monotonic() < _unavailable_until


def note_unavailable(exc: BaseException) -> None:
    """Record that a connection attempt failed."""
    global _unavailable_until
    was_open = circuit_open()
    _unavailable_until = time.monotonic() + _BREAKER_COOLDOWN
    if not was_open:
        _logger.warning(
            "PostgreSQL unreachable (%s). Failing fast for %.0fs before retrying.",
            exc, _BREAKER_COOLDOWN,
        )


def note_available() -> None:
    """Record a successful connection; resume normal service immediately."""
    global _unavailable_until
    if circuit_open():
        _logger.info("PostgreSQL reachable again.")
    _unavailable_until = 0.0


def reset_availability() -> None:
    """Clear breaker state (tests, and after a deliberate reconnect)."""
    global _unavailable_until
    _unavailable_until = 0.0


@contextmanager
def _checked_connection():
    """A pooled connection, refused immediately while the circuit is open."""
    if circuit_open():
        raise DatabaseUnavailable(
            "PostgreSQL is unreachable; not retrying yet. "
            "The connection will be retried automatically."
        )
    try:
        pool = _get_pool()
    except Exception as exc:
        note_unavailable(exc)
        raise
    try:
        with pool.connection() as conn:
            note_available()
            yield conn
    except DatabaseUnavailable:
        raise
    except Exception as exc:
        # Only connectivity failures trip the breaker. A syntax error or a
        # constraint violation means the database answered perfectly well.
        if isinstance(exc, (psycopg.OperationalError, PoolTimeout)):
            note_unavailable(exc)
        raise


@contextmanager
def get_db():
    """Yield a pooled psycopg3 Connection.

    Auto-commits on success, rolls back on any exception.
    Usage mirrors the old mysql.connector pattern so no module code changes.
    """
    with _checked_connection() as conn:
        yield conn


# ── Sync helpers (identical public signatures as the MySQL version) ────────────
#
# All three accept an optional `conn`: when given, the statement runs on that
# connection instead of checking one out of the pool, and this function does
# not commit or roll it back — the caller (typically a `with get_db() as conn:`
# block) owns that transaction's boundary. This is what lets a caller like
# ai.seed group several statements into one all-or-nothing commit instead of
# each call auto-committing its own pooled connection independently.

def query_one(sql: str, params: tuple = (), *, conn=None) -> dict[str, Any] | None:
    """Execute SELECT; return the first row as a plain dict, or None."""
    if conn is not None:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return dict(row) if row else None
    with _checked_connection() as _conn:
        with _conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return dict(row) if row else None


def query_all(sql: str, params: tuple = (), *, conn=None) -> list[dict[str, Any]]:
    """Execute SELECT; return all rows as a list of plain dicts."""
    if conn is not None:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
    with _checked_connection() as _conn:
        with _conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]


def execute(sql: str, params: tuple = (), *, conn=None) -> int:
    """Execute INSERT/UPDATE/DELETE; return rowcount."""
    if conn is not None:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount
    with _checked_connection() as _conn:
        with _conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount


def is_connected() -> bool:
    """Return True if the database is reachable.

    Answers immediately from breaker state while the database is known down,
    so /health stays fast during an outage instead of re-timing-out per call.
    """
    if circuit_open():
        return False
    try:
        row = query_one("SELECT 1 AS ok")
        return row is not None
    except Exception as exc:
        _logger.warning("DB connectivity check failed: %s", exc)
        return False


# ── Async connection pool ──────────────────────────────────────────────────────

_async_pool: AsyncConnectionPool | None = None


def _get_async_pool() -> AsyncConnectionPool:
    global _async_pool
    if _async_pool is None:
        pool_size = int(os.environ.get("DB_POOL_SIZE", "5"))
        _async_pool = AsyncConnectionPool(
            _conninfo(),
            min_size=2,
            max_size=pool_size,
            timeout=_POOL_TIMEOUT,   # see _POOL_TIMEOUT above
            open=False,  # opened explicitly in lifespan
        )
        _logger.info("PostgreSQL async pool created (max_size=%d)", pool_size)
    return _async_pool


async def open_async_pool() -> None:
    """Open the async pool. Call from FastAPI lifespan startup."""
    await _get_async_pool().open()
    _logger.info("PostgreSQL async pool opened.")


async def close_async_pool() -> None:
    """Close the async pool. Call from FastAPI lifespan shutdown."""
    global _async_pool
    if _async_pool is not None:
        await _async_pool.close()
        _async_pool = None
        _logger.info("PostgreSQL async pool closed.")


# ── Async helpers (for streaming event_generator — non-blocking) ───────────────

async def async_query_one(sql: str, params: tuple = ()) -> dict[str, Any] | None:
    """Async SELECT; return the first row as a plain dict, or None."""
    async with _get_async_pool().connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            row = await cur.fetchone()
            return dict(row) if row else None


async def async_query_all(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    """Async SELECT; return all rows as a list of plain dicts."""
    async with _get_async_pool().connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return [dict(r) for r in await cur.fetchall()]


async def async_execute(sql: str, params: tuple = ()) -> int:
    """Async INSERT/UPDATE/DELETE; return rowcount."""
    async with _get_async_pool().connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            return cur.rowcount
