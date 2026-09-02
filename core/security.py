"""
Central security utilities: secret/PII redaction and cache classification.

Two jobs:
  1. redact_secrets(text)  — scrub secrets & PII out of any text before it is
     returned to the user, written to the cache, or logged. Defense-in-depth on
     top of agent._sanitize_for_cloud (which only protects *cloud* LLM calls).
  2. classify_for_cache(...) — decide whether a response may be stored in the
     cache. Sensitive tool results (salaries, PII, financials) and anything still
     containing secrets are never cached.

These are pure functions with no external dependencies, so they are cheap to call
on every request and easy to unit-test.
"""
from __future__ import annotations

import re

# ── Secret patterns ─────────────────────────────────────────────────────────────
# Ordered roughly most-specific → most-general. Each maps to a placeholder.
_SECRET_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Private key blocks
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL), "[PRIVATE_KEY]"),
    # OpenAI-style keys (sk-..., sk-proj-...)
    (re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{16,}\b"), "[API_KEY]"),
    # Anthropic keys
    (re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{16,}\b"), "[API_KEY]"),
    # AWS access key id
    (re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), "[AWS_KEY]"),
    # GitHub / generic provider tokens
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|xox[baprs])[-_][A-Za-z0-9]{16,}\b"), "[TOKEN]"),
    # JWT (three base64url segments)
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"), "[JWT]"),
    # Bearer tokens
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{12,}"), "Bearer [TOKEN]"),
    # Connection strings with embedded credentials (scheme://user:pass@host)
    (re.compile(r"\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:[^\s:/@]+@[^\s]+"), "[CONNECTION_STRING]"),
    # key/secret/password/token assignments:  password = "...", api_key: '...'
    # The (?!\[) lookahead skips already-redacted placeholders like "[REDACTED]",
    # keeping redaction idempotent and avoiding false-positive secret detection.
    (re.compile(r"(?i)\b(pass(?:word|wd)?|secret|api[_\- ]?key|access[_\- ]?token|auth[_\- ]?token|client[_\- ]?secret|token)\b\s*[:=]\s*[\"']?(?!\[)([^\s\"',;]{4,})"), r"\1=[REDACTED]"),
]

# ── PII patterns (shared shape with core.audit_logger) ──────────────────────────
# Bounded local part and domain labels. The previous unbounded `[\w.+\-]+@…`
# backtracked over every prefix of a long word run, making redaction O(n^2) —
# a 1 MB message occupied a worker for ~40 minutes (finding F-10).
_EMAIL_RE = re.compile(r"[\w.+\-]{1,64}@[\w\-]{1,63}(?:\.[\w\-]{1,63}){1,4}")
_PHONE_RE = re.compile(r"\b(\+?\d[\d\s\-().]{7,}\d)\b")
# Credit-card-like 13-19 digit runs (allowing spaces/dashes)
_CARD_RE = re.compile(r"\b\d(?:[ -]?\d){12,18}\b")

_REDACTORS = [(p, r) for p, r in _SECRET_PATTERNS] + [
    (_EMAIL_RE, "[EMAIL]"),
    (_CARD_RE, "[CARD]"),
    (_PHONE_RE, "[PHONE]"),
]


def redact_secrets(text):
    """Return `text` with secrets and PII replaced by placeholders.
    Non-strings are returned unchanged."""
    if not isinstance(text, str) or not text:
        return text
    # Defence in depth: redaction runs on every response, so it must stay cheap
    # even if a future pattern is added carelessly. Long inputs are redacted in
    # overlapping chunks rather than in one pass.
    if len(text) > _CHUNK:
        step, overlap = _CHUNK, 256
        parts, i = [], 0
        while i < len(text):
            parts.append(_redact_once(text[i:i + step + overlap]))
            i += step
        return "".join(parts)
    return _redact_once(text)


_CHUNK = 16_384


def _redact_once(text: str) -> str:
    out = text
    for pattern, repl in _REDACTORS:
        out = pattern.sub(repl, out)
    return out


def contains_secret(text) -> bool:
    """True if `text` matches any *secret* pattern (excludes plain email/phone)."""
    if not isinstance(text, str) or not text:
        return False
    return any(p.search(text) for p, _ in _SECRET_PATTERNS)


def redact_obj(obj):
    """Recursively redact strings inside dicts/lists (for tool results / sources)."""
    if isinstance(obj, str):
        return redact_secrets(obj)
    if isinstance(obj, dict):
        return {k: redact_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_obj(v) for v in obj]
    return obj


# ── Cache classification ────────────────────────────────────────────────────────
# Tools whose results carry PII / financial / personal data — never cache these.
SENSITIVE_TOOLS: frozenset[str] = frozenset({
    "get_payslip",
    "get_employee_info",
    "get_leave_balance",
    "search_employees",
    "get_customer_info",
    "get_vendor_info",
    "get_customer_ledger",
    "get_tds_certificate_data",
    "get_customer_unit_outstanding",
    "get_receipt_history",
    "get_gl_posting_for_receipt",
    "park_customer_receipt",
    "post_customer_receipt",
    "get_sales_deed_data",
    "get_allotment_letter_data",
    "get_broker_payout_status",
})


def classify_for_cache(*, tool_called: str | None, text: str | None) -> tuple[bool, str]:
    """Decide whether a response may be cached.

    Returns (cacheable, reason). Conservative by design: when in doubt, don't cache.
    """
    if tool_called in SENSITIVE_TOOLS:
        return False, f"sensitive tool '{tool_called}'"
    if text and contains_secret(text):
        return False, "response contains secret material"
    if text and (_EMAIL_RE.search(text) or _CARD_RE.search(text)):
        return False, "response contains PII"
    return True, "ok"


# ── SAP payload sanitisation ──────────────────────────────────────────────────

def sanitize_sap_payload(messages: list[dict]) -> list[dict]:
    """Strip SAP tool result bodies from a message list.

    Two independent ways a message is recognised as SAP-bearing:

      1. Content shaped "SAP tool 'X' returned:\\n{...}" — what SAPAgent's
         _format_tool_response produces. Keeping the first line preserves
         enough context for the model to write a coherent follow-up prompt
         without the record itself leaving the estate. This is the original
         path; SAPAgent and its tests depend on this exact shape and it must
         keep working unchanged.

      2. An explicit `sap_payload: True` marker on the message dict. Some
         callers (agent.autonomous_agent, agent.report_agent) build a message
         by embedding raw tool-result JSON into a larger prompt — planner
         context, a reasoning summary, a report formatter's system prompt —
         where there is no fixed "first line" to preserve the way the
         prefix-shaped case has. Those callers set the marker on exactly the
         message they built from tool results; this function is the only
         place that reads it. The marker itself is never forwarded: a matched
         message is rebuilt from scratch (role + redacted content only), and
         ai.manager's conversion to the wire `Message` type reads only
         role/content anyway, so it cannot leak downstream even if some other
         caller forgot to strip it.

    This lived on SAPAgent, where it only ever guarded that class's own cloud
    fallback. It belongs here because ai.manager must be able to apply it to any
    external provider, whichever agent made the call.

    Returns a new list; the input is not mutated.
    """
    sanitized: list[dict] = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str) and content.startswith("SAP tool '") and "returned:" in content:
            first_line = content.split("\n")[0]
            sanitized.append({
                **msg,
                "content": f"{first_line}\n[SAP data redacted — not transmitted to external providers]",
            })
        elif msg.get("sap_payload") and isinstance(content, str):
            sanitized.append({
                "role": msg.get("role"),
                "content": "[SAP data redacted — not transmitted to external providers]",
            })
        else:
            sanitized.append(dict(msg))
    return sanitized
