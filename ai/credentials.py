"""
Provider API keys: written encrypted, read only at dispatch, never rendered.

The plaintext exists in three places and no others — the admin's browser at the
moment of entry, this module's local variables, and the outbound provider
request. It is never returned by an API, never written to a log, never included
in the config.json snapshot, and never held on a cached configuration object.

`_execute` and `_query_one` are module-level indirections rather than direct
imports so tests can substitute the table without a database.
"""
from __future__ import annotations

import logging

from ai.errors import CredentialUnavailable
from core.crypto import MissingKeyError, get_secret_box, last4, mask_secret

_logger = logging.getLogger("ai.credentials")

#: Sent by the UI to mean "leave the stored key alone". Matches the placeholder
#: core/config_manager.py already uses for SAP secrets.
UNCHANGED_SENTINEL = "••••••••"


def _execute(sql: str, params: tuple, conn=None) -> int:
    from db.connection import execute
    return execute(sql, params, conn=conn)


def _query_one(sql: str, params: tuple) -> dict | None:
    from db.connection import query_one
    return query_one(sql, params)


def is_unchanged(value: str | None) -> bool:
    """True when the client sent the placeholder instead of a new key."""
    return value == UNCHANGED_SENTINEL


def store_credential(provider_id: str, tenant_id: str, api_key: str, conn=None) -> None:
    """Encrypt and persist a provider credential, replacing any existing one.

    `provider_id` alone is the table's primary key (ai_provider_credentials
    has no composite key), so the ON CONFLICT target can only be `provider_id`
    — but its DO UPDATE is additionally guarded by a `WHERE tenant_id =
    EXCLUDED.tenant_id`. Without that guard, a write carrying a *different*
    tenant_id than the row already stored would still match on provider_id and
    overwrite the ciphertext while leaving tenant_id untouched — replacing one
    tenant's credential with another tenant's key under the original tenant's
    name. With the guard, a cross-tenant write for an existing provider_id is
    silently a no-op (0 rows affected), the same shape ai.credentials.
    delete_credential already uses via its own tenant-scoped WHERE clause.

    `conn`, when given, runs on that connection rather than a fresh pooled
    one — ai.seed uses this so a newly-seeded provider's credential commits
    atomically with the provider row it references (a foreign key), which
    would otherwise not yet be visible to a separate connection.
    """
    try:
        ciphertext, version = get_secret_box().encrypt(api_key)
    except MissingKeyError as exc:
        raise CredentialUnavailable(str(exc)) from exc

    _execute(
        """INSERT INTO ai_provider_credentials
               (provider_id, tenant_id, ciphertext, key_version, last4)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (provider_id) DO UPDATE SET
               ciphertext  = EXCLUDED.ciphertext,
               key_version = EXCLUDED.key_version,
               last4       = EXCLUDED.last4,
               rotated_at  = NOW()
           WHERE ai_provider_credentials.tenant_id = EXCLUDED.tenant_id""",
        (provider_id, tenant_id, ciphertext, version, last4(api_key)),
        conn=conn,
    )


def read_credential(provider_id: str, tenant_id: str) -> str | None:
    """Return the plaintext credential, or None when none is stored.

    Raises CredentialUnavailable when a credential exists but cannot be
    decrypted — that is a different operational problem from having none, and
    conflating the two would show the administrator a misleading empty field.
    """
    row = _query_one(
        "SELECT ciphertext, key_version FROM ai_provider_credentials "
        "WHERE provider_id = %s AND tenant_id = %s",
        (provider_id, tenant_id),
    )
    if not row:
        return None
    try:
        return get_secret_box().decrypt(bytes(row["ciphertext"]), int(row["key_version"]))
    except MissingKeyError as exc:
        _logger.error("Credential for provider %s could not be decrypted.", provider_id)
        raise CredentialUnavailable(str(exc)) from exc


def has_credential(provider_id: str, tenant_id: str) -> bool:
    return _query_one(
        "SELECT 1 AS present FROM ai_provider_credentials "
        "WHERE provider_id = %s AND tenant_id = %s",
        (provider_id, tenant_id),
    ) is not None


def credential_display(provider_id: str, tenant_id: str) -> str:
    """Masked form for the admin UI: 'sk-****wxyz'. Never decrypts anything."""
    row = _query_one(
        "SELECT last4 FROM ai_provider_credentials WHERE provider_id = %s AND tenant_id = %s",
        (provider_id, tenant_id),
    )
    if not row or not row["last4"]:
        return ""
    return mask_secret(f"sk-{'x' * 12}{row['last4']}")


def delete_credential(provider_id: str, tenant_id: str) -> None:
    _execute(
        "DELETE FROM ai_provider_credentials WHERE provider_id = %s AND tenant_id = %s",
        (provider_id, tenant_id),
    )
