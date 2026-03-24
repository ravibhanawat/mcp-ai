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
"""
import os
import logging
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, AsyncConnectionPool

_logger = logging.getLogger("db.connection")


# ── DSN builder ───────────────────────────────────────────────────────────────

def _conninfo() -> str:
    """Build a libpq-style connection string from env vars or defaults."""
    host     = os.environ.get("DB_HOST",     "localhost")
    port     = int(os.environ.get("DB_PORT", "5432"))
    user     = os.environ.get("DB_USER",     "sap_agent")
    password = os.environ.get("DB_PASSWORD", "")
    database = os.environ.get("DB_NAME",     "sap_agent")
    return (
        f"host={host} port={port} dbname={database} "
        f"user={user} password={password} connect_timeout=10"
    )


# ── Sync connection pool ───────────────────────────────────────────────────────

_pool: ConnectionPool | None = None


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        pool_size = int(os.environ.get("DB_POOL_SIZE", "5"))
        _pool = ConnectionPool(
            _conninfo(),
            min_size=2,
            max_size=pool_size,
            open=True,
        )
        _logger.info("PostgreSQL sync pool ready (max_size=%d)", pool_size)
    return _pool


@contextmanager
def get_db():
    """Yield a pooled psycopg3 Connection.

    Auto-commits on success, rolls back on any exception.
    Usage mirrors the old mysql.connector pattern so no module code changes.
    """
    with _get_pool().connection() as conn:
        yield conn


# ── Sync helpers (identical public signatures as the MySQL version) ────────────

def query_one(sql: str, params: tuple = ()) -> dict[str, Any] | None:
    """Execute SELECT; return the first row as a plain dict, or None."""
    with _get_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return dict(row) if row else None


def query_all(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    """Execute SELECT; return all rows as a list of plain dicts."""
    with _get_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]


def execute(sql: str, params: tuple = ()) -> int:
    """Execute INSERT/UPDATE/DELETE; return rowcount."""
    with _get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount


def is_connected() -> bool:
    """Return True if the database is reachable."""
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
