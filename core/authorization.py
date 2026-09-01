"""
Operation-level authorization and the confirmation gate for destructive actions.

Two controls the module-level RBAC in auth/rbac.py does not provide:

  1. OPERATION  — granting a module used to grant every tool in it, reads and
     writes alike, so a role named "analyst" could post a customer receipt
     (finding F-03). Each tool now carries a verb, and a role must hold that
     verb as well as the module.

  2. CONFIRMATION — a write must not execute merely because someone asked.
     Previously the only control was a line in the system prompt telling the
     model to confirm, which made the LLM the sole authority over money
     movement. Enforcement now sits in execute_tool(), below the model.

The confirmation token is an HMAC over (user, tool, parameters) with a short
TTL, so it cannot be replayed by another user, reused for a different action,
or minted by a client.
"""
from __future__ import annotations

import contextvars
import hashlib
import hmac
import json
import os
import sys
import time
from typing import Any

# ── Operation classification ─────────────────────────────────────────────────
READ  = "read"
WRITE = "write"

# Tools that create, post, park or otherwise mutate SAP business data.
# Everything not listed here is a read.
WRITE_TOOLS: frozenset[str] = frozenset({
    "create_sales_order",
    "create_production_order",
    "apply_leave",
    "park_customer_receipt",
    "post_customer_receipt",
    "initiate_broker_po",
})

# Roles permitted to perform writes at all. A role absent here is read-only no
# matter which modules it holds.
WRITE_ROLES: frozenset[str] = frozenset({
    "admin",
    "sd_analyst",
    "hr_manager",
    "pp_planner",
    "re_analyst",
})


def operation_of(tool_name: str) -> str:
    """Return READ or WRITE for a tool."""
    return WRITE if tool_name in WRITE_TOOLS else READ


def role_may_write(roles: list[str] | set[str]) -> bool:
    """True if any of `roles` is permitted to perform write operations."""
    return bool(set(roles) & WRITE_ROLES)


def check_operation(tool_name: str, roles: list[str] | set[str]) -> bool:
    """True if `roles` may perform this tool's operation.

    Module access is checked separately by auth.rbac.check_tool_access; both
    must pass.
    """
    if operation_of(tool_name) == READ:
        return True
    return role_may_write(roles)


def filter_by_operation(tools: set[str], roles: list[str] | set[str]) -> set[str]:
    """Drop write tools from `tools` when `roles` may not write."""
    if role_may_write(roles):
        return tools
    return {t for t in tools if operation_of(t) == READ}


# ── Confirmation tokens ──────────────────────────────────────────────────────
_TTL_SECONDS = int(os.environ.get("CONFIRM_TOKEN_TTL", "300"))


def _secret() -> bytes:
    """Signing key for confirmation tokens.

    Reuses JWT_SECRET_KEY so there is one secret to rotate. In development the
    same insecure fallback as auth.jwt_handler applies; outside development the
    server already refuses to start without a real secret.
    """
    key = os.environ.get("JWT_SECRET_KEY", "").strip()
    if key:
        return key.encode()
    if os.environ.get("APP_ENV", "development").lower() == "development":
        return b"dev-secret-CHANGE-ME-before-production"
    print("FATAL: JWT_SECRET_KEY must be set to issue confirmation tokens.",
          file=sys.stderr)
    sys.exit(1)


def _digest(user_id: str, tool_name: str, parameters: dict, expires: int) -> str:
    payload = json.dumps(
        {"u": user_id, "t": tool_name,
         "p": parameters, "e": expires},
        sort_keys=True, separators=(",", ":"), default=str,
    )
    return hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()


def issue_token(user_id: str, tool_name: str, parameters: dict) -> tuple[str, int]:
    """Mint a confirmation token for one specific action. Returns (token, expires)."""
    expires = int(time.time()) + _TTL_SECONDS
    return f"{expires}.{_digest(user_id, tool_name, parameters, expires)}", expires


def verify_token(token: str | None, user_id: str,
                 tool_name: str, parameters: dict) -> bool:
    """True if `token` authorises exactly this user/tool/parameters, unexpired."""
    if not token or "." not in token:
        return False
    raw_exp, _, sig = token.partition(".")
    try:
        expires = int(raw_exp)
    except ValueError:
        return False
    if time.time() > expires:
        return False
    return hmac.compare_digest(sig, _digest(user_id, tool_name, parameters, expires))


# ── Execution context ────────────────────────────────────────────────────────
# execute_tool() has no request object, so the caller's identity and any
# supplied confirmation token travel on context variables. The same pattern is
# used for the MCP identity in api/server.py.
_actor: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "authz_actor", default=None)
_confirm: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "authz_confirm", default=None)
_enforce: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "authz_enforce", default=False)


class execution_context:
    """Bind the acting user and confirmation token for the duration of a request.

    Enforcement is opt-in so library and CLI callers that have no user are not
    silently blocked; every authenticated API path enters this context.

        with execution_context(user_id="alice", confirm_token=tok):
            execute_tool(...)
    """

    def __init__(self, *, user_id: str | None,
                 confirm_token: str | None = None, enforce: bool = True):
        self._user, self._token, self._on = user_id, confirm_token, enforce

    def __enter__(self):
        self._t = (_actor.set(self._user), _confirm.set(self._token),
                   _enforce.set(self._on))
        return self

    def __exit__(self, *exc):
        _actor.reset(self._t[0]); _confirm.reset(self._t[1]); _enforce.reset(self._t[2])
        return False


def confirmation_required(tool_name: str, parameters: dict) -> dict[str, Any] | None:
    """Return a pending-action payload if this call needs confirmation first.

    Returns None when the action may proceed: it is a read, enforcement is off,
    or a valid confirmation token for exactly this action was supplied.
    """
    if operation_of(tool_name) == READ or not _enforce.get():
        return None
    user = _actor.get() or "unknown"
    if verify_token(_confirm.get(), user, tool_name, parameters):
        return None
    token, expires = issue_token(user, tool_name, parameters)
    return {
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


# ── Field-level masking ──────────────────────────────────────────────────────
# Holding a module grants its rows, but not every column in them. These fields
# are withheld unless the caller's role is explicitly listed (finding: field
# scoping had no implementation, so bank details, tax IDs, credit limits and
# full salary breakdowns were returned to any role holding the module).
#
# Roles are deliberately narrow: widen them by adding the role here, not by
# removing the field.
RESTRICTED_FIELDS: dict[str, frozenset[str]] = {
    # salary detail — HR and admin only
    "basic_salary":     frozenset({"admin", "hr_manager"}),
    "hra":              frozenset({"admin", "hr_manager"}),
    "other_allowances": frozenset({"admin", "hr_manager"}),
    "total_deductions": frozenset({"admin", "hr_manager"}),
    "net_salary":       frozenset({"admin", "hr_manager"}),
    # vendor banking / tax — finance and admin only
    "bank_account":     frozenset({"admin", "fi_co_analyst"}),
    "bank_name":        frozenset({"admin", "fi_co_analyst"}),
    "tax_id":           frozenset({"admin", "fi_co_analyst"}),
    "gst_number":       frozenset({"admin", "fi_co_analyst", "re_analyst"}),
    # commercial terms — sales, finance and admin
    "credit_limit":     frozenset({"admin", "fi_co_analyst", "sd_analyst", "re_analyst"}),
    # personal contact detail — HR and admin
    "email":            frozenset({"admin", "hr_manager"}),
    "phone":            frozenset({"admin", "hr_manager"}),
    "mobile":           frozenset({"admin", "hr_manager"}),
}

MASK = "[RESTRICTED]"


def mask_fields(obj, roles: list[str] | set[str] | None):
    """Recursively replace restricted field values the caller may not see.

    `roles` of None means enforcement is off (auth disabled). Keys are kept and
    the value replaced, so the shape of the response is unchanged and the caller
    can see that something was withheld rather than that it does not exist.
    """
    if roles is None:
        return obj
    role_set = set(roles)
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            allowed_roles = RESTRICTED_FIELDS.get(k.lower())
            if allowed_roles is not None and not (role_set & allowed_roles):
                out[k] = MASK
            else:
                out[k] = mask_fields(v, roles)
        return out
    if isinstance(obj, list):
        return [mask_fields(v, roles) for v in obj]
    return obj
