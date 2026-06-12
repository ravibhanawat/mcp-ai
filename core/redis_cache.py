"""
Graceful Redis cache wrapper.

Used to cache chat answers and chart/report payloads so repeated questions don't
re-hit the LLM (a direct scale lever) and to keep response latency low.

Design principles:
  - **Optional & graceful.** If the `redis` package is missing, `REDIS_URL` is
    unset, or the server is unreachable, the cache silently disables itself and
    every call becomes a no-op. The app keeps working without Redis.
  - **Per-user namespacing.** Cache keys embed the user id so one user's cached
    answer can never be served to another (cross-user leak prevention).
  - **JSON values.** Stored values are JSON; non-serialisable values are skipped.

Callers decide *whether* a value is safe to cache (see core.security.classify_for_cache)
and *what* to store (redacted text). This module only handles storage.

Config (env):
  REDIS_URL           e.g. redis://localhost:6379/0   (absent → disabled)
  CACHE_TTL_SECONDS   default value TTL (default 3600)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os

_logger = logging.getLogger("redis_cache")

_DEFAULT_TTL = int(os.environ.get("CACHE_TTL_SECONDS", "3600"))

_client = None          # redis.Redis | None
_initialised = False
_enabled = False


def _init() -> None:
    """Lazily connect on first use. Failures disable the cache permanently."""
    global _client, _initialised, _enabled
    if _initialised:
        return
    _initialised = True

    url = os.environ.get("REDIS_URL", "").strip()
    if not url:
        _logger.info("Cache disabled: REDIS_URL not set.")
        return
    try:
        import redis  # type: ignore
        client = redis.Redis.from_url(url, socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        _client = client
        _enabled = True
        _logger.info("Redis cache enabled (%s).", url)
    except ImportError:
        _logger.warning("Cache disabled: 'redis' package not installed.")
    except Exception as exc:  # connection refused, auth, etc.
        _logger.warning("Cache disabled: cannot reach Redis (%s).", exc)


def is_enabled() -> bool:
    _init()
    return _enabled


def make_key(*parts: str) -> str:
    """Stable short key from arbitrary string parts."""
    raw = "\x1f".join(p or "" for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _full_key(namespace: str, user_id: str, key: str) -> str:
    # user_id in the key → per-user isolation.
    return f"kutty:{namespace}:{user_id}:{key}"


def get(namespace: str, user_id: str, key: str):
    """Return the cached JSON value or None (on miss / disabled / error)."""
    _init()
    if not _enabled:
        return None
    try:
        raw = _client.get(_full_key(namespace, user_id, key))
        return json.loads(raw) if raw else None
    except Exception as exc:
        _logger.debug("cache get failed: %s", exc)
        return None


def set(namespace: str, user_id: str, key: str, value, ttl: int | None = None) -> bool:
    """Store a JSON-serialisable value. Returns True if written."""
    _init()
    if not _enabled:
        return False
    try:
        payload = json.dumps(value)
    except (TypeError, ValueError):
        return False
    try:
        _client.setex(_full_key(namespace, user_id, key), ttl or _DEFAULT_TTL, payload)
        return True
    except Exception as exc:
        _logger.debug("cache set failed: %s", exc)
        return False
