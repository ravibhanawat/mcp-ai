"""
File-based user store for the SAP AI Agent.

Users are persisted in users.json in the project root.
Passwords are hashed with bcrypt (cost factor 12).

On first run, default user accounts are created with NO password set.
An administrator must call POST /auth/users (or update_password()) to
set passwords before anyone can log in.

For production, replace with your LDAP/AD/SSO directory.
"""
import json
import os
import re
import stat
import sys
import time
from typing import Any

import bcrypt

# ── Password policy ───────────────────────────────────────────────────────────
_MIN_LENGTH = 10
_PASSWORD_RE = re.compile(
    r'^(?=.*[A-Z])(?=.*[a-z])(?=.*\d)(?=.*[!@#$%^&*()\-_=+\[\]{};:\'",.<>?/\\|`~]).{10,}$'
)

def validate_password(password: str) -> None:
    """
    Raise ValueError if password doesn't meet policy:
    - Minimum 10 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit
    - At least one special character
    """
    if not password or len(password) < _MIN_LENGTH:
        raise ValueError(f"Password must be at least {_MIN_LENGTH} characters long.")
    if not _PASSWORD_RE.match(password):
        raise ValueError(
            "Password must contain at least one uppercase letter, one lowercase letter, "
            "one digit, and one special character (!@#$%^&* etc.)."
        )


# ── Account lockout ───────────────────────────────────────────────────────────
_MAX_FAILURES  = 5          # failed attempts before lockout
_LOCKOUT_SECS  = 900        # 15 minutes

# Lockout state lives in Redis when it is configured, so a lock holds across all
# gunicorn workers and survives a restart. With N workers and per-process state
# an attacker previously got 5xN attempts, and any restart cleared every lock
# (finding F-07). The in-process dicts remain as a single-worker fallback.
_fail_counts:  dict[str, int]   = {}   # user_id → failed attempt count
_locked_until: dict[str, float] = {}   # user_id → unlock timestamp


def _shared():
    """Return the Redis client if shared lockout is available, else None."""
    try:
        from core import redis_cache
        if redis_cache.is_enabled():
            return redis_cache._client
    except Exception:
        pass
    return None


def _record_failure(user_id: str) -> None:
    r = _shared()
    if r is not None:
        try:
            n = r.incr(f"authlock:fail:{user_id}")
            r.expire(f"authlock:fail:{user_id}", _LOCKOUT_SECS)
            if n >= _MAX_FAILURES:
                r.setex(f"authlock:locked:{user_id}", _LOCKOUT_SECS, "1")
                print(
                    f"WARNING: Account '{user_id}' locked after {_MAX_FAILURES} failed "
                    f"attempts for {_LOCKOUT_SECS // 60} minutes.",
                    file=sys.stderr,
                )
            return
        except Exception:
            pass   # fall through to in-process counters
    _fail_counts[user_id] = _fail_counts.get(user_id, 0) + 1
    if _fail_counts[user_id] >= _MAX_FAILURES:
        _locked_until[user_id] = time.monotonic() + _LOCKOUT_SECS
        print(
            f"WARNING: Account '{user_id}' locked after {_MAX_FAILURES} failed attempts "
            f"for {_LOCKOUT_SECS // 60} minutes.",
            file=sys.stderr,
        )


def _clear_failure(user_id: str) -> None:
    r = _shared()
    if r is not None:
        try:
            r.delete(f"authlock:fail:{user_id}", f"authlock:locked:{user_id}")
        except Exception:
            pass
    _fail_counts.pop(user_id, None)
    _locked_until.pop(user_id, None)


def _is_locked(user_id: str) -> bool:
    r = _shared()
    if r is not None:
        try:
            if r.get(f"authlock:locked:{user_id}"):
                return True
        except Exception:
            pass
    unlock_at = _locked_until.get(user_id, 0)
    if unlock_at and time.monotonic() < unlock_at:
        return True
    if unlock_at and time.monotonic() >= unlock_at:
        # Auto-unlock after lockout period expires
        _clear_failure(user_id)
    return False

_USERS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "users.json")

# Default user accounts created on first run — pre-configured with default passwords.
_DEFAULT_USERS = [
    {
        "user_id":           "admin",
        "full_name":         "System Administrator",
        "email":             "admin@company.com",
        "roles":             ["admin"],
        "active":            True,
        "password_hash":     None,
        "must_set_password": True,
    },
    {
        "user_id":           "fi_user",
        "full_name":         "Finance Analyst",
        "email":             "finance@company.com",
        "roles":             ["fi_co_analyst"],
        "active":            True,
        "password_hash":     None,
        "must_set_password": True,
    },
    {
        "user_id":           "hr_user",
        "full_name":         "HR Manager",
        "email":             "hr@company.com",
        "roles":             ["hr_manager"],
        "active":            True,
        "password_hash":     None,
        "must_set_password": True,
    },
    {
        "user_id":           "demo",
        "full_name":         "Demo User",
        "email":             "demo@company.com",
        "roles":             ["read_only"],
        "active":            True,
        "password_hash":     None,
        "must_set_password": True,
    },
]

# bcrypt hashes that shipped in earlier builds of this repo and were published in
# README.md, users.json.example and the frontend bundle. Any account still using
# one is treated as unset: the credentials are public, so they are not a secret.
_PUBLISHED_HASHES: frozenset[str] = frozenset({
    "$2b$12$LQxBhJlGrVIopGaBE08dh.GDef10eK/nU2PF4xXhxibj9ggR7XPye",
    "$2b$12$UFlBUwnF0y.sKkoPame3AuyJveVghctXc2OPQ1xsLcfcU2hNCj6vi",
    "$2b$12$6KlFqMOhjzy9F/NalnQbs.MH6lGPoqzp3CSL3WARVbRwyyQAxYice",
    "$2b$12$8hI2np0FSq2PoAWuy2XZqONml7Rgt4oD8eNxrKN8j54fc2AjYHLXK",
})


# ── Password hashing (bcrypt) ─────────────────────────────────────────────────

def _hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt (cost 12). Returns the hash string."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def _verify_password(password: str, stored_hash: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
    except Exception:
        return False


# ── Persistence ───────────────────────────────────────────────────────────────

def _load() -> dict[str, dict]:
    """Load users from file; initialise with defaults if file absent."""
    if not os.path.exists(_USERS_FILE):
        _init_defaults()
    with open(_USERS_FILE, encoding="utf-8") as f:
        raw: list[dict] = json.load(f)
    users = {u["user_id"]: u for u in raw}
    # Migrate any legacy SHA-256 records (they have a "salt" key) → force reset
    _migrate_legacy(users)
    return users


def _save(users: dict[str, dict]) -> None:
    with open(_USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(users.values()), f, indent=2)
    # Restrict to owner read/write only (no world/group access)
    os.chmod(_USERS_FILE, stat.S_IRUSR | stat.S_IWUSR)


def _init_defaults() -> None:
    """Write default user records (no passwords). Admin must set passwords via API."""
    with open(_USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(_DEFAULT_USERS, f, indent=2)
    os.chmod(_USERS_FILE, stat.S_IRUSR | stat.S_IWUSR)
    print(
        "WARNING: users.json initialised with default accounts but NO passwords. "
        "Run scripts/setup_admin.py (or POST /auth/users as an admin) to set "
        "passwords before anyone can log in.",
        file=sys.stderr,
    )


def _migrate_legacy(users: dict[str, dict]) -> None:
    """
    Invalidate credentials that can no longer be trusted, forcing a reset:

    1. SHA-256 era records (identified by a 'salt' key).
    2. Any account still using a bcrypt hash that was published in this repo.

    Earlier builds re-seeded the default accounts here whenever their passwords
    were cleared, which made the published credentials impossible to revoke.
    That behaviour is deliberately gone: an account with no usable password
    stays locked until an administrator sets one (scripts/setup_admin.py).
    """
    changed = False
    for user in users.values():
        if "salt" in user:
            user.pop("salt", None)
            user["password_hash"] = None
            user["must_set_password"] = True
            changed = True
        elif user.get("password_hash") in _PUBLISHED_HASHES:
            print(
                f"WARNING: account '{user['user_id']}' was using a password published "
                f"in this repository. It has been revoked — run "
                f"scripts/setup_admin.py to set a new one.",
                file=sys.stderr,
            )
            user["password_hash"] = None
            user["must_set_password"] = True
            changed = True

    if changed:
        _save(users)


def uses_published_credentials() -> list[str]:
    """Return the ids of accounts still using a password published in this repo.

    Called at startup so a production deployment refuses to run with them.
    """
    try:
        with open(_USERS_FILE, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return []
    return [u["user_id"] for u in raw
            if u.get("password_hash") in _PUBLISHED_HASHES]


# ── Public API ────────────────────────────────────────────────────────────────

def authenticate(user_id: str, password: str) -> dict[str, Any] | None:
    """
    Return public user dict if credentials are valid, None otherwise.
    Refuses login if account is inactive, locked out, or password not set.
    Records failed attempts and applies lockout after _MAX_FAILURES tries.
    """
    # Check lockout before touching the DB (prevents timing oracle)
    if _is_locked(user_id):
        return None

    users = _load()
    user = users.get(user_id)
    if not user or not user.get("active", True):
        _record_failure(user_id)
        return None
    if user.get("must_set_password") or not user.get("password_hash"):
        return None
    if not _verify_password(password, user["password_hash"]):
        _record_failure(user_id)
        return None

    _clear_failure(user_id)   # reset counter on success
    return _public_user(user)


def get_user(user_id: str) -> dict[str, Any] | None:
    """Return public user dict or None."""
    users = _load()
    u = users.get(user_id)
    return _public_user(u) if u else None


def list_users() -> list[dict[str, Any]]:
    """Return all users (no password fields)."""
    return [_public_user(u) for u in _load().values()]


def create_user(
    user_id: str,
    password: str,
    full_name: str,
    email: str,
    roles: list[str],
) -> dict[str, Any]:
    """Create a new user with a bcrypt-hashed password. Raises ValueError if user already exists."""
    validate_password(password)
    from auth.rbac import ALL_ROLES
    for r in roles:
        if r not in ALL_ROLES:
            raise ValueError(f"Unknown role: {r}")
    users = _load()
    if user_id in users:
        raise ValueError(f"User '{user_id}' already exists")
    entry = {
        "user_id":           user_id,
        "full_name":         full_name,
        "email":             email,
        "roles":             roles,
        "active":            True,
        "password_hash":     _hash_password(password),
        "must_set_password": False,
    }
    users[user_id] = entry
    _save(users)
    return _public_user(entry)


def update_password(user_id: str, new_password: str) -> None:
    """Update a user's password (bcrypt hash). Enforces password policy."""
    validate_password(new_password)
    users = _load()
    if user_id not in users:
        raise ValueError(f"User '{user_id}' not found")
    users[user_id]["password_hash"]     = _hash_password(new_password)
    users[user_id]["must_set_password"] = False
    _save(users)


def set_active(user_id: str, active: bool) -> None:
    """Enable or disable a user account."""
    users = _load()
    if user_id not in users:
        raise ValueError(f"User '{user_id}' not found")
    users[user_id]["active"] = active
    _save(users)


def _public_user(u: dict) -> dict[str, Any]:
    """Strip sensitive fields before returning to API callers."""
    return {k: v for k, v in u.items()
            if k not in ("password_hash", "salt", "refresh_jtis")}


# ── Refresh-token rotation state ──────────────────────────────────────────────
#
# One entry per live login session, so signing in on a second device does not
# sign the first one out. /auth/refresh accepts a token only if its jti is
# still in this list, and swaps that entry for the new token's jti — which is
# what makes rotation mean something. Replaying a jti that has already been
# swapped out is the standard refresh-token-theft signal, and the caller
# responds by clearing the whole list.

_MAX_SESSIONS_PER_USER = 10


def get_refresh_jtis(user_id: str) -> list[str]:
    """Return the jtis of this user's currently valid refresh tokens."""
    user = _load().get(user_id)
    return list(user.get("refresh_jtis") or []) if user else []


def set_refresh_jtis(user_id: str, jtis: list[str]) -> None:
    """Replace the set of valid refresh-token jtis for a user."""
    users = _load()
    if user_id not in users:
        return
    users[user_id]["refresh_jtis"] = list(jtis)[-_MAX_SESSIONS_PER_USER:]
    _save(users)


def record_refresh_jti(user_id: str, jti: str) -> None:
    """Add a newly issued refresh token to the valid set (a fresh login)."""
    set_refresh_jtis(user_id, [*get_refresh_jtis(user_id), jti])


def rotate_refresh_jti(user_id: str, old_jti: str, new_jti: str) -> bool:
    """Swap `old_jti` for `new_jti`. False if `old_jti` was not valid.

    A False return means the presented token had already been rotated away —
    treat it as a compromised chain, not a retry.
    """
    current = get_refresh_jtis(user_id)
    if old_jti not in current:
        return False
    set_refresh_jtis(user_id, [j for j in current if j != old_jti] + [new_jti])
    return True


def revoke_all_refresh_tokens(user_id: str) -> None:
    """Invalidate every refresh token for a user (logout-everywhere, or theft)."""
    set_refresh_jtis(user_id, [])
