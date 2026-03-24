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
_fail_counts:  dict[str, int]   = {}   # user_id → failed attempt count
_locked_until: dict[str, float] = {}   # user_id → unlock timestamp


def _record_failure(user_id: str) -> None:
    _fail_counts[user_id] = _fail_counts.get(user_id, 0) + 1
    if _fail_counts[user_id] >= _MAX_FAILURES:
        _locked_until[user_id] = time.monotonic() + _LOCKOUT_SECS
        print(
            f"WARNING: Account '{user_id}' locked after {_MAX_FAILURES} failed attempts "
            f"for {_LOCKOUT_SECS // 60} minutes.",
            file=sys.stderr,
        )


def _clear_failure(user_id: str) -> None:
    _fail_counts.pop(user_id, None)
    _locked_until.pop(user_id, None)


def _is_locked(user_id: str) -> bool:
    unlock_at = _locked_until.get(user_id, 0)
    if unlock_at and time.monotonic() < unlock_at:
        return True
    if unlock_at and time.monotonic() >= unlock_at:
        # Auto-unlock after lockout period expires
        _clear_failure(user_id)
    return False

_USERS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "users.json")

# Default user accounts created on first run — NO passwords set by default.
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
        "Use POST /auth/users or update_password() to set passwords before use.",
        file=sys.stderr,
    )


def _migrate_legacy(users: dict[str, dict]) -> None:
    """
    Detect SHA-256 records (identified by a 'salt' key) and invalidate them
    so users are forced to reset their passwords via the admin API.
    This is a one-time migration when upgrading from the old SHA-256 scheme.
    """
    changed = False
    for user in users.values():
        if "salt" in user:
            user.pop("salt", None)
            user["password_hash"] = None
            user["must_set_password"] = True
            changed = True
    if changed:
        _save(users)
        print(
            "INFO: Legacy SHA-256 password records detected and invalidated. "
            "All affected users must have their passwords reset via POST /auth/users/{id}/password.",
            file=sys.stderr,
        )


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
    return {k: v for k, v in u.items() if k not in ("password_hash", "salt")}
