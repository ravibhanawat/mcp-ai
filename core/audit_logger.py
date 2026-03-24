"""
Audit Logger — SOX + GDPR compliant request logging.

Every /chat call is written to logs/audit.jsonl as a single JSON line.
Rotation: a new file is created each day (audit_YYYY-MM-DD.jsonl).
Retention: log files older than AUDIT_LOG_RETENTION_DAYS (default 90) are
           automatically deleted on each write to keep storage bounded.

PII redaction is applied to queries, response summaries, and sensitive
tool parameters before writing to disk.

Fields logged:
  timestamp, request_id, user_id, user_roles, client_ip,
  endpoint, query (redacted), tool_called, tool_parameters (redacted),
  sap_source, response_summary (first 200 chars, redacted), duration_ms, status
"""
import json
import os
import re
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path


class _SafeEncoder(json.JSONEncoder):
    """JSON encoder that handles types not serializable by default (e.g. Decimal)."""
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)

_LOG_DIR = Path(__file__).parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)

_RETENTION_DAYS = int(os.environ.get("AUDIT_LOG_RETENTION_DAYS", "90"))

# ── PII redaction patterns ────────────────────────────────────────────────────
_EMAIL_RE  = re.compile(r'[\w.+\-]+@[\w\-]+\.[\w.]+')
_PHONE_RE  = re.compile(r'\b(\+?[\d][\d\s\-().]{7,}\d)\b')

# Tool parameter keys that may contain PII
_SENSITIVE_PARAM_KEYS = {"full_name", "employee_name", "name", "email", "phone", "mobile"}


def _redact(text: str) -> str:
    """Redact email addresses and phone numbers from a string."""
    if not text:
        return text
    text = _EMAIL_RE.sub("[EMAIL]", text)
    text = _PHONE_RE.sub("[PHONE]", text)
    return text


def _redact_params(params: dict | None) -> dict | None:
    """Replace values of known PII keys with [REDACTED]."""
    if not params:
        return params
    return {
        k: "[REDACTED]" if k.lower() in _SENSITIVE_PARAM_KEYS else v
        for k, v in params.items()
    }


# ── Log file management ───────────────────────────────────────────────────────

def _log_file() -> Path:
    date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    return _LOG_DIR / f"audit_{date_str}.jsonl"


def _purge_old_logs() -> None:
    """Delete audit log files older than _RETENTION_DAYS."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=_RETENTION_DAYS)
    for f in _LOG_DIR.glob("audit_*.jsonl"):
        try:
            # Parse date from filename: audit_YYYY-MM-DD.jsonl
            date_part = f.stem.replace("audit_", "")
            file_date = datetime.strptime(date_part, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if file_date < cutoff:
                f.unlink()
        except Exception:
            pass  # Skip files with unexpected names


# ── Public API ────────────────────────────────────────────────────────────────

def log_request(
    *,
    user_id: str,
    user_roles: list[str],
    client_ip: str,
    endpoint: str,
    query: str,
    tool_called: str | None = None,
    tool_parameters: dict | None = None,
    sap_source: dict | None = None,
    response_text: str = "",
    duration_ms: int = 0,
    status: str = "ok",
    request_id: str | None = None,
    status_code: int | None = None,
    error_message: str | None = None,
) -> str:
    """Write one audit record (with PII redacted). Returns the request_id.

    Dual-writes to:
      1. Daily JSONL file on disk  (always)
      2. request_logs DB table     (if DB is available)
    """
    rid = request_id or str(uuid.uuid4())
    record = {
        "timestamp":        datetime.now(tz=timezone.utc).isoformat(),
        "request_id":       rid,
        "user_id":          user_id,
        "user_roles":       user_roles,
        "client_ip":        client_ip,
        "endpoint":         endpoint,
        "query":            _redact(query),
        "tool_called":      tool_called,
        "tool_parameters":  _redact_params(tool_parameters),
        "sap_source":       sap_source,
        "response_summary": _redact(response_text[:200]),
        "duration_ms":      duration_ms,
        "status":           status,
    }
    with open(_log_file(), "a", encoding="utf-8") as f:
        f.write(json.dumps(record, cls=_SafeEncoder) + "\n")

    # Dual-write to DB (best-effort)
    try:
        from db.activity_log import write_log
        write_log(
            request_id=rid,
            user_id=user_id,
            user_roles=user_roles,
            client_ip=client_ip,
            method="POST",
            endpoint=endpoint,
            status_code=status_code or (200 if status == "ok" else 500),
            status=status,
            query_text=_redact(query),
            tool_called=tool_called,
            tool_parameters=_redact_params(tool_parameters),
            sap_source=sap_source,
            response_summary=_redact(response_text[:500]),
            duration_ms=duration_ms,
            error_message=error_message,
            log_source="audit",
        )
    except Exception:
        pass  # Never let DB failure break audit logging

    # Run retention cleanup periodically (1% of writes to avoid overhead)
    import random
    if random.random() < 0.01:
        _purge_old_logs()
    return rid


def get_recent_logs(limit: int = 100, user_id: str | None = None) -> list[dict]:
    """
    Read the most recent audit records from today's log file.
    Optionally filter by user_id.
    """
    path = _log_file()
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    records = []
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if user_id and rec.get("user_id") != user_id:
            continue
        records.append(rec)
        if len(records) >= limit:
            break
    return records


def list_log_files() -> list[str]:
    """Return all audit log filenames, newest first."""
    files = sorted(_LOG_DIR.glob("audit_*.jsonl"), reverse=True)
    return [f.name for f in files]
