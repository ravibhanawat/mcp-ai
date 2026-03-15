"""
Audit Logger — SOX + GDPR compliant request logging.

Every /chat call is written to logs/audit.jsonl as a single JSON line.
Rotation: a new file is created each day (audit_YYYY-MM-DD.jsonl).

Fields logged:
  timestamp, request_id, user_id, user_roles, client_ip,
  endpoint, query, tool_called, tool_parameters, sap_source,
  response_summary (first 200 chars), duration_ms, status
"""
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

_LOG_DIR = Path(__file__).parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)


def _log_file() -> Path:
    date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    return _LOG_DIR / f"audit_{date_str}.jsonl"


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
) -> str:
    """Write one audit record. Returns the request_id."""
    rid = request_id or str(uuid.uuid4())
    record = {
        "timestamp":        datetime.now(tz=timezone.utc).isoformat(),
        "request_id":       rid,
        "user_id":          user_id,
        "user_roles":       user_roles,
        "client_ip":        client_ip,
        "endpoint":         endpoint,
        "query":            query,
        "tool_called":      tool_called,
        "tool_parameters":  tool_parameters,
        "sap_source":       sap_source,
        "response_summary": response_text[:200],
        "duration_ms":      duration_ms,
        "status":           status,
    }
    with open(_log_file(), "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
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
