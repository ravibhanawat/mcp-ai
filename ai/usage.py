"""
Writes one ai_usage_logs row per model attempt.

One row per *attempt*, not per request: a request that fails over from a local
model to a cloud one produces two rows, which is the only way a fallback is
visible in the audit trail rather than an invisible degradation.

Never raises. Losing a telemetry row is an acceptable outcome; failing a user's
question because the logging table is unavailable is not.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, fields

_logger = logging.getLogger("ai.usage")


@dataclass(frozen=True)
class UsageRecord:
    tenant_id: str
    user_id: str | None
    provider_id: str | None
    model_id: str | None
    request_id: str | None
    purpose: str | None
    intent: str | None
    tool_used: str | None
    authorization_result: str | None
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int | None
    fallback_used: bool
    fallback_from_model_id: str | None
    egress_class: str | None
    redaction_applied: bool
    status: str
    error_code: str | None


def _execute(sql: str, params: tuple) -> int:
    from db.connection import execute
    return execute(sql, params)


_COLUMNS = [f.name for f in fields(UsageRecord)]
_INSERT = (
    f"INSERT INTO ai_usage_logs ({', '.join(_COLUMNS)}) "
    f"VALUES ({', '.join(['%s'] * len(_COLUMNS))})"
)


def log_usage(record: UsageRecord) -> None:
    """Persist one attempt. Swallows every failure by design."""
    try:
        _execute(_INSERT, tuple(getattr(record, name) for name in _COLUMNS))
    except Exception as exc:
        _logger.debug("ai_usage_logs write failed: %s", exc)
