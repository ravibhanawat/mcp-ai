"""
Reachability and latency for configured models.

`is_known_unreachable` lets the router skip a model already known to be down
rather than paying its full timeout first. It deliberately returns False for a
model with no health record: an unprobed model is unknown, not broken, and
treating unknown as broken would make a fresh install refuse to answer.
"""
from __future__ import annotations

import logging

from ai.providers.registry import build_provider
from ai.types import HealthResult, ResolvedModel

_logger = logging.getLogger("ai.health")


def _execute(sql: str, params: tuple) -> int:
    from db.connection import execute
    return execute(sql, params)


def _query_one(sql: str, params: tuple) -> dict | None:
    from db.connection import query_one
    return query_one(sql, params)


def probe(resolved: ResolvedModel, api_key: str | None) -> HealthResult:
    """Check whether the model's provider answers. Never raises."""
    try:
        return build_provider(resolved.provider, api_key).health_check()
    except Exception as exc:
        return HealthResult("unreachable", 0, str(exc)[:500])


def record_health(model_id: str, tenant_id: str, result: HealthResult) -> None:
    """Upsert the latest health record. Never raises."""
    try:
        _execute(
            """INSERT INTO ai_model_health
                   (model_id, tenant_id, status, latency_ms, checked_at,
                    last_success_at, last_error)
               VALUES (%s, %s, %s, %s, NOW(),
                       CASE WHEN %s = 'healthy' THEN NOW() ELSE NULL END, %s)
               ON CONFLICT (model_id) DO UPDATE SET
                   status          = EXCLUDED.status,
                   latency_ms      = EXCLUDED.latency_ms,
                   checked_at      = NOW(),
                   last_success_at = CASE WHEN EXCLUDED.status = 'healthy'
                                          THEN NOW()
                                          ELSE ai_model_health.last_success_at END,
                   last_error      = EXCLUDED.last_error""",
            (model_id, tenant_id, result.status, result.latency_ms,
             result.status, result.error),
        )
    except Exception as exc:
        _logger.debug("ai_model_health write failed: %s", exc)


def last_health(model_id: str, tenant_id: str) -> dict | None:
    try:
        return _query_one(
            "SELECT status, latency_ms, checked_at, last_success_at, last_error "
            "FROM ai_model_health WHERE model_id = %s AND tenant_id = %s",
            (model_id, tenant_id),
        )
    except Exception:
        return None


def is_known_unreachable(model_id: str, tenant_id: str) -> bool:
    """True only when the last probe positively failed. Unknown is not broken."""
    row = last_health(model_id, tenant_id)
    return bool(row and row.get("status") == "unreachable")
