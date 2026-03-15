"""
File-based user store for the SAP AI Agent.

Users are persisted in users.json in the project root.
Passwords are stored as SHA-256(salt + password) hex digests.

For production, replace with your LDAP/AD/SSO directory.
"""
import hashlib
import json
import os
import secrets
from typing import Any

_USERS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "users.json")

# Default users created on first run
_DEFAULT_USERS = [
    {
        "user_id":  "admin",
        "full_name": "System Administrator",
        "email":    "admin@company.com",
        "roles":    ["admin"],
        "active":   True,
    },
    {
        "user_id":  "fi_user",
        "full_name": "Finance Analyst",
        "email":    "finance@company.com",
        "roles":    ["fi_co_analyst"],
        "active":   True,
    },
    {
        "user_id":  "hr_user",
        "full_name": "HR Manager",
        "email":    "hr@company.com",
        "roles":    ["hr_manager"],
        "active":   True,
    },
    {
        "user_id":  "demo",
        "full_name": "Demo User",
        "email":    "demo@company.com",
        "roles":    ["read_only"],
        "active":   True,
    },
]

# Default plaintext passwords (hashed on first load)
_DEFAULT_PASSWORDS = {
    "admin":   "Admin@123",
    "fi_user": "Finance@123",
    "hr_user": "HR@123",
    "demo":    "demo",
}


def _hash_password(password: str, salt: str) -> str:
    return hashlib.sha256((salt + password).encode()).hexdigest()


def _load() -> dict[str, dict]:
    """Load users from file; initialise with defaults if file absent."""
    if not os.path.exists(_USERS_FILE):
        _init_defaults()
    with open(_USERS_FILE) as f:
        raw: list[dict] = json.load(f)
    return {u["user_id"]: u for u in raw}


def _save(users: dict[str, dict]) -> None:
    with open(_USERS_FILE, "w") as f:
        json.dump(list(users.values()), f, indent=2)


def _init_defaults() -> None:
    users: list[dict] = []
    for u in _DEFAULT_USERS:
        salt = secrets.token_hex(16)
        pw = _DEFAULT_PASSWORDS.get(u["user_id"], "changeme")
        entry = {**u, "salt": salt, "password_hash": _hash_password(pw, salt)}
        users.append(entry)
    with open(_USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)


def authenticate(user_id: str, password: str) -> dict[str, Any] | None:
    """
    Return user dict (without password fields) if credentials are valid,
    or None if user not found / password wrong / account inactive.
    """
    users = _load()
    user = users.get(user_id)
    if not user or not user.get("active", True):
        return None
    expected = _hash_password(password, user["salt"])
    if not secrets.compare_digest(expected, user["password_hash"]):
        return None
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
    """Create a new user. Raises ValueError if user_id already exists."""
    from auth.rbac import ALL_ROLES
    for r in roles:
        if r not in ALL_ROLES:
            raise ValueError(f"Unknown role: {r}")
    users = _load()
    if user_id in users:
        raise ValueError(f"User '{user_id}' already exists")
    salt = secrets.token_hex(16)
    entry = {
        "user_id": user_id,
        "full_name": full_name,
        "email": email,
        "roles": roles,
        "active": True,
        "salt": salt,
        "password_hash": _hash_password(password, salt),
    }
    users[user_id] = entry
    _save(users)
    return _public_user(entry)


def update_password(user_id: str, new_password: str) -> None:
    """Update a user's password."""
    users = _load()
    if user_id not in users:
        raise ValueError(f"User '{user_id}' not found")
    salt = secrets.token_hex(16)
    users[user_id]["salt"] = salt
    users[user_id]["password_hash"] = _hash_password(new_password, salt)
    _save(users)


def set_active(user_id: str, active: bool) -> None:
    """Enable or disable a user account."""
    users = _load()
    if user_id not in users:
        raise ValueError(f"User '{user_id}' not found")
    users[user_id]["active"] = active
    _save(users)


def _public_user(u: dict) -> dict[str, Any]:
    """Strip sensitive fields for API responses."""
    return {k: v for k, v in u.items() if k not in ("salt", "password_hash")}
