"""
First-run admin setup script.

Run this ONCE after first starting the server to set passwords for all default
user accounts. Passwords set here are bcrypt-hashed and stored in users.json.

Usage:
    python scripts/setup_admin.py
"""
import getpass
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auth.users import update_password, list_users, _load

DEFAULT_ACCOUNTS = ["admin", "fi_user", "hr_user", "demo"]


def main():
    print("=" * 60)
    print("SAP AI Agent — First-Run Admin Setup")
    print("=" * 60)
    print()
    print("This script sets passwords for the default user accounts.")
    print("All passwords are stored as bcrypt hashes in users.json.")
    print("Press Ctrl+C at any time to quit.\n")

    # Trigger users.json creation if it doesn't exist
    try:
        users = _load()
    except Exception as e:
        print(f"Error loading users: {e}")
        sys.exit(1)

    for user_id in DEFAULT_ACCOUNTS:
        user = users.get(user_id)
        if not user:
            print(f"  [SKIP] User '{user_id}' not found in users.json")
            continue

        needs_set = user.get("must_set_password") or not user.get("password_hash")
        status    = "(no password set)" if needs_set else "(password already set)"
        print(f"User: {user.get('full_name', user_id)} [{user_id}] {status}")

        try:
            pw1 = getpass.getpass(f"  Enter password for '{user_id}' (blank to skip): ")
            if not pw1:
                print(f"  Skipped '{user_id}'.")
                continue
            if len(pw1) < 8:
                print("  Password must be at least 8 characters. Skipped.")
                continue
            pw2 = getpass.getpass(f"  Confirm password for '{user_id}': ")
            if pw1 != pw2:
                print("  Passwords do not match. Skipped.")
                continue
            update_password(user_id, pw1)
            print(f"  Password set for '{user_id}'.\n")
        except KeyboardInterrupt:
            print("\nSetup cancelled.")
            sys.exit(0)

    print()
    print("Setup complete. Users with passwords set can now log in.")
    print()
    print("Current user status:")
    for u in list_users():
        pwd_status = "NEEDS PASSWORD" if u.get("must_set_password") else "ready"
        print(f"  {u['user_id']:15} roles={u['roles']}  [{pwd_status}]")


if __name__ == "__main__":
    main()
