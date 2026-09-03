"""
Shared FastAPI auth dependencies.

Extracted from api/server.py so route modules can depend on authentication
without importing the module that mounts them. Behaviour is unchanged: this is
a move, not a rewrite.

This module is the single source of truth for _AUTH_ENABLED. api/server.py
imports it so the flag is never recomputed; see the comments there.
"""
from __future__ import annotations

import os
import sys

import jwt as _jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from auth.jwt_handler import decode_token

_bearer = HTTPBearer(auto_error=False)

# ── Environment & security constants ─────────────────────────────────────────
_APP_ENV = os.environ.get("APP_ENV", "development").lower()
_IS_DEV = _APP_ENV == "development"

# ── DISABLE_AUTH: only permitted in development ────────────────────────────────
_disable_auth_requested = os.environ.get("DISABLE_AUTH", "false").lower() in ("true", "1", "yes")
if _disable_auth_requested and not _IS_DEV:
    print(
        "FATAL: DISABLE_AUTH=true is not permitted outside APP_ENV=development.",
        file=sys.stderr,
    )
    sys.exit(1)
_AUTH_ENABLED = not _disable_auth_requested

_GUEST_USER = {"user_id": "guest", "roles": ["read_only"], "full_name": "Guest (auth disabled)"}


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """Validate the JWT bearer token and return the user payload."""
    if not _AUTH_ENABLED:
        return _GUEST_USER
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header. Use: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(credentials.credentials)
    except _jwt.ExpiredSignatureError:
        raise HTTPException(401, "Access token expired. Use /auth/refresh to renew.")
    except _jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token.")

    user_id = payload["sub"]

    # A signature only proves the token was minted by us, not that the account
    # still exists. PATCH /auth/users/{id}/deactivate revoked the MCP key and
    # blocked re-login, but the access token already in the user's hands kept
    # working until it expired — so a revoked or compromised account retained
    # full API access for up to JWT_EXPIRE_HOURS after it was closed. The
    # account is re-checked on every request instead.
    try:
        from auth import users as user_store
        account = user_store.get_user(user_id)
    except Exception as exc:
        # Fail closed, but say which failure it is: an unreadable user store is
        # an operational problem, not a bad credential, and answering 401 would
        # send everyone to the login screen to no effect.
        raise HTTPException(503, "The user directory is temporarily unavailable.") from exc

    if account is None:
        raise HTTPException(401, "Account no longer exists.")
    if not account.get("active", True):
        raise HTTPException(401, "Account is deactivated.")

    return {"user_id": user_id, "roles": payload.get("roles", [])}


def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if "admin" not in current_user.get("roles", []):
        raise HTTPException(status_code=403, detail="Admin role required.")
    return current_user
