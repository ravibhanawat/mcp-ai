"""
JWT token creation and validation.

Secret key is read from env var JWT_SECRET_KEY.
Falls back to a dev-only default — CHANGE IN PRODUCTION.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt  # PyJWT

_SECRET = os.environ.get("JWT_SECRET_KEY", "dev-secret-CHANGE-ME-before-production")
_ALGORITHM = "HS256"
_DEFAULT_EXPIRE_HOURS = int(os.environ.get("JWT_EXPIRE_HOURS", "8"))


def create_token(user_id: str, roles: list[str], expire_hours: int = _DEFAULT_EXPIRE_HOURS) -> str:
    """Create a signed JWT for the given user."""
    now = datetime.now(tz=timezone.utc)
    payload: dict[str, Any] = {
        "sub": user_id,
        "roles": roles,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(hours=expire_hours),
    }
    return jwt.encode(payload, _SECRET, algorithm=_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """
    Decode and verify a JWT.
    Raises jwt.ExpiredSignatureError or jwt.InvalidTokenError on failure.
    """
    return jwt.decode(token, _SECRET, algorithms=[_ALGORITHM])


def is_dev_secret() -> bool:
    """Return True if the default (insecure) dev secret is still in use."""
    return _SECRET == "dev-secret-CHANGE-ME-before-production"
