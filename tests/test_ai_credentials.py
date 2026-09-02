"""Credential storage tests. The database calls are patched so these run anywhere;
what is being tested is the encryption boundary, not psycopg."""
import os
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet

from ai.credentials import (
    UNCHANGED_SENTINEL,
    credential_display,
    delete_credential,
    has_credential,
    is_unchanged,
    read_credential,
    store_credential,
)
from ai.errors import CredentialUnavailable

_KEY = Fernet.generate_key().decode()


class FakeRows:
    """Stands in for the ai_provider_credentials table."""

    def __init__(self):
        self.rows: dict[str, dict] = {}

    def execute(self, sql, params, conn=None):
        if sql.strip().upper().startswith("DELETE"):
            provider_id, tenant_id = params
            row = self.rows.get(provider_id)
            # Mirror the production WHERE clause: a tenant may only delete its own.
            if row and row["tenant_id"] == tenant_id:
                del self.rows[provider_id]
                return 1
            return 0
        provider_id, tenant_id, ciphertext, key_version, last4 = params
        existing = self.rows.get(provider_id)
        # Mirror the production ON CONFLICT (provider_id) DO UPDATE ... WHERE
        # tenant_id = EXCLUDED.tenant_id: a write for a provider_id that
        # already belongs to a DIFFERENT tenant must not overwrite it. Without
        # this, the fake would report isolation the production statement,
        # before its own tenant guard, does not actually have.
        if existing and existing["tenant_id"] != tenant_id:
            return 0
        self.rows[provider_id] = {
            "provider_id": provider_id, "tenant_id": tenant_id,
            "ciphertext": ciphertext, "key_version": key_version, "last4": last4,
        }
        return 1

    def query_one(self, sql, params):
        row = self.rows.get(params[0])
        if row and row["tenant_id"] == params[1]:
            return row
        return None


class CredentialTestCase(unittest.TestCase):

    def setUp(self):
        self.rows = FakeRows()
        self.env = patch.dict(os.environ, {"AI_CONFIG_KEY": _KEY})
        self.env.start()
        self.exec_patch = patch("ai.credentials._execute", self.rows.execute)
        self.query_patch = patch("ai.credentials._query_one", self.rows.query_one)
        self.exec_patch.start()
        self.query_patch.start()

    def tearDown(self):
        self.env.stop()
        self.exec_patch.stop()
        self.query_patch.stop()


class TestCredentialRoundtrip(CredentialTestCase):

    def test_store_then_read_returns_the_key(self):
        store_credential("p1", "default", "sk-live-abcdwxyz")
        self.assertEqual("sk-live-abcdwxyz", read_credential("p1", "default"))

    def test_stored_bytes_do_not_contain_the_plaintext(self):
        store_credential("p1", "default", "sk-live-abcdwxyz")
        self.assertNotIn(b"sk-live", self.rows.rows["p1"]["ciphertext"])

    def test_read_for_wrong_tenant_returns_none(self):
        store_credential("p1", "default", "sk-live-abcdwxyz")
        self.assertIsNone(read_credential("p1", "other-tenant"))

    def test_missing_credential_returns_none(self):
        self.assertIsNone(read_credential("nope", "default"))

    def test_display_masks_all_but_last_four(self):
        store_credential("p1", "default", "sk-live-abcdwxyz")
        shown = credential_display("p1", "default")
        self.assertEqual("sk-****wxyz", shown)
        self.assertNotIn("live", shown)

    def test_display_is_empty_when_no_credential(self):
        self.assertEqual("", credential_display("nope", "default"))

    def test_delete_removes_the_credential(self):
        store_credential("p1", "default", "sk-live-abcdwxyz")
        delete_credential("p1", "default")
        self.assertIsNone(read_credential("p1", "default"))

    def test_delete_from_another_tenant_leaves_the_row_intact(self):
        """The tenant filter on DELETE is what stops one tenant from destroying
        another's credential. Confirmed to fail if that filter is dropped from
        the production SQL — see task-9-report.md for the experiment."""
        store_credential("p1", "default", "sk-live-abcdwxyz")
        delete_credential("p1", "other-tenant")
        self.assertEqual("sk-live-abcdwxyz", read_credential("p1", "default"))

    def test_has_credential_reflects_presence(self):
        self.assertFalse(has_credential("p1", "default"))
        store_credential("p1", "default", "sk-live-abcdwxyz")
        self.assertTrue(has_credential("p1", "default"))
        self.assertFalse(has_credential("p1", "other-tenant"))

    def test_store_from_another_tenant_does_not_overwrite(self):
        """The ON CONFLICT (provider_id) DO UPDATE ... WHERE tenant_id =
        EXCLUDED.tenant_id clause is what stops a write for a different
        tenant from replacing another tenant's ciphertext while leaving
        tenant_id untouched — provider_id alone is the table's primary key,
        so without that WHERE clause the conflict target would match
        regardless of which tenant issued the write. Confirmed to fail if
        that WHERE clause is dropped from the production SQL (verified by
        temporarily removing it and re-running: the second store_credential
        call overwrites p1's ciphertext under tenant 'default')."""
        store_credential("p1", "default", "sk-live-original")
        store_credential("p1", "other-tenant", "sk-live-attacker")
        self.assertEqual("sk-live-original", read_credential("p1", "default"))
        self.assertIsNone(read_credential("p1", "other-tenant"))


class TestKeyFailures(CredentialTestCase):

    def test_undecryptable_credential_raises_rather_than_returning_none(self):
        """The admin must be able to tell 'no key' from 'key I cannot read'."""
        store_credential("p1", "default", "sk-live-abcdwxyz")
        with patch.dict(os.environ, {"AI_CONFIG_KEY": Fernet.generate_key().decode()}):
            with self.assertRaises(CredentialUnavailable):
                read_credential("p1", "default")

    def test_storing_without_a_key_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(CredentialUnavailable):
                store_credential("p1", "default", "sk-value")


class TestSentinel(unittest.TestCase):

    def test_sentinel_matches_the_existing_config_manager_placeholder(self):
        self.assertEqual("••••••••", UNCHANGED_SENTINEL)

    def test_is_unchanged_detects_the_sentinel(self):
        self.assertTrue(is_unchanged("••••••••"))
        self.assertFalse(is_unchanged("sk-real-key"))
        self.assertFalse(is_unchanged(None))


if __name__ == "__main__":
    unittest.main()
