"""
JWT token creation and validation.

Access token secret  → JWT_SECRET_KEY env var (required in non-dev environments).
Refresh token secret → JWT_REFRESH_SECRET env var (required in non-dev environments).

In APP_ENV=development both fall back to insecure dev-only defaults with a
stderr warning. Any other APP_ENV causes an immediate sys.exit(1) if the
secrets are missing or still set to the dev defaults.
"""
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt  # PyJWT

# ── Environment ───────────────────────────────────────────────────────────────
_DEV_SECRET          = "dev-secret-CHANGE-ME-before-production"
_DEV_REFRESH_SECRET  = "dev-refresh-secret-CHANGE-ME-before-production"
_APP_ENV             = os.environ.get("APP_ENV", "development").lower()
_IS_DEV              = _APP_ENV == "development"
_ALGORITHM           = "HS256"


def _resolve_secret(env_var: str, dev_fallback: str, label: str) -> str:
    """
    Read a secret from an env var.
    - If the env var is set and not equal to the dev fallback → use it.
    - If missing/default AND in dev mode → use dev fallback + warn.
    - If missing/default AND NOT in dev mode → print fatal error and exit.
    """
    value = os.environ.get(env_var, "").strip()
    if value and value != dev_fallback:
        return value
    # Missing or still the default placeholder
    if _IS_DEV:
        print(
            f"WARNING: {env_var} is not set. Using insecure dev default for {label}. "
            "Set APP_ENV=production and provide a real secret before deploying.",
            file=sys.stderr,
        )
        return dev_fallback
    print(
        f"FATAL: {env_var} must be set in non-development environments (APP_ENV={_APP_ENV}). "
        f"Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\"",
        file=sys.stderr,
    )
    sys.exit(1)


_SECRET          = _resolve_secret("JWT_SECRET_KEY",      _DEV_SECRET,         "access tokens")
_REFRESH_SECRET  = _resolve_secret("JWT_REFRESH_SECRET",  _DEV_REFRESH_SECRET, "refresh tokens")

_DEFAULT_EXPIRE_HOURS  = int(os.environ.get("JWT_EXPIRE_HOURS",        "1"))
_REFRESH_EXPIRE_DAYS   = int(os.environ.get("JWT_REFRESH_EXPIRE_DAYS", "7"))


# ── Access token ──────────────────────────────────────────────────────────────

def create_token(user_id: str, roles: list[str], expire_hours: int = _DEFAULT_EXPIRE_HOURS) -> str:
    """Create a signed JWT access token for the given user."""
    now = datetime.now(tz=timezone.utc)
    payload: dict[str, Any] = {
        "sub":   user_id,
        "roles": roles,
        "type":  "access",
        "jti":   str(uuid.uuid4()),
        "iat":   now,
        "exp":   now + timedelta(hours=expire_hours),
    }
    return jwt.encode(payload, _SECRET, algorithm=_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """
    Decode and verify a JWT access token.
    Raises jwt.ExpiredSignatureError or jwt.InvalidTokenError on failure.
    """
    payload = jwt.decode(token, _SECRET, algorithms=[_ALGORITHM])
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("Token is not an access token.")
    return payload


# ── Refresh token ─────────────────────────────────────────────────────────────

def create_refresh_token(user_id: str, expire_days: int = _REFRESH_EXPIRE_DAYS) -> str:
    """Create a signed JWT refresh token (long-lived, used only to issue new access tokens)."""
    now = datetime.now(tz=timezone.utc)
    payload: dict[str, Any] = {
        "sub":  user_id,
        "type": "refresh",
        "jti":  str(uuid.uuid4()),
        "iat":  now,
        "exp":  now + timedelta(days=expire_days),
    }
    return jwt.encode(payload, _REFRESH_SECRET, algorithm=_ALGORITHM)


def decode_refresh_token(token: str) -> dict[str, Any]:
    """
    Decode and verify a JWT refresh token.
    Raises jwt.ExpiredSignatureError or jwt.InvalidTokenError on failure.
    """
    payload = jwt.decode(token, _REFRESH_SECRET, algorithms=[_ALGORITHM])
    if payload.get("type") != "refresh":
        raise jwt.InvalidTokenError("Token is not a refresh token.")
    return payload


# ── Utilities ─────────────────────────────────────────────────────────────────

def is_dev_secret() -> bool:
    """Return True if the insecure dev secret is still in use (access token)."""
    return _SECRET == _DEV_SECRET
