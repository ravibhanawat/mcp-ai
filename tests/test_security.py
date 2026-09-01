"""
Tests for core.security (redaction + cache classification) and the graceful
core.redis_cache (no Redis required — must degrade to a no-op).

Run:  python -m unittest tests.test_security
"""
import unittest

from core.security import (
    redact_secrets,
    contains_secret,
    redact_obj,
    classify_for_cache,
)


class TestRedaction(unittest.TestCase):
    def test_openai_key(self):
        out = redact_secrets("here is my key sk-proj-ABCD1234efgh5678IJKL90mn please")
        self.assertNotIn("sk-proj-ABCD1234", out)
        self.assertIn("[API_KEY]", out)

    def test_anthropic_key(self):
        out = redact_secrets("key=sk-ant-api03-XYZ12345678abcdefgh")
        self.assertIn("[API_KEY]", out)
        self.assertNotIn("XYZ12345678abcdefgh", out)

    def test_jwt(self):
        jwt = "eyJhbGciOiJIUzI1Ni1.eyJzdWIiOiIxMjM0NTY.SflKxwRJSMeKKF2QT4"
        out = redact_secrets(f"token {jwt}")
        self.assertIn("[JWT]", out)
        self.assertNotIn(jwt, out)

    def test_connection_string(self):
        out = redact_secrets("postgres://user:s3cr3t@db.internal:5432/app")
        self.assertIn("[CONNECTION_STRING]", out)
        self.assertNotIn("s3cr3t", out)

    def test_password_assignment(self):
        out = redact_secrets('password = "hunter2longpass"')
        self.assertNotIn("hunter2longpass", out)
        self.assertIn("[REDACTED]", out)

    def test_email_and_phone(self):
        out = redact_secrets("contact john.doe@acme.com or +1 415 555 1234")
        self.assertIn("[EMAIL]", out)
        self.assertIn("[PHONE]", out)

    def test_plain_text_untouched(self):
        text = "Ticket #43LYY0LEZK is Completed for module MM."
        self.assertEqual(redact_secrets(text), text)

    def test_non_string_passthrough(self):
        self.assertEqual(redact_secrets(123), 123)
        self.assertIsNone(redact_secrets(None))

    def test_contains_secret(self):
        self.assertTrue(contains_secret("api_key=ABCDEF123456"))
        self.assertFalse(contains_secret("just a normal sentence"))

    def test_redact_obj_nested(self):
        obj = {"a": "sk-proj-ABCD1234efgh5678IJKL", "b": ["ok", {"c": "x@y.com"}]}
        red = redact_obj(obj)
        self.assertIn("[API_KEY]", red["a"])
        self.assertIn("[EMAIL]", red["b"][1]["c"])
        self.assertEqual(red["b"][0], "ok")


class TestCacheClassification(unittest.TestCase):
    def test_sensitive_tool_blocked(self):
        ok, reason = classify_for_cache(tool_called="get_payslip", text="Net pay 50000")
        self.assertFalse(ok)
        self.assertIn("sensitive", reason)

    def test_secret_in_text_blocked(self):
        ok, _ = classify_for_cache(tool_called=None, text="db url is postgres://u:p@h/db")
        self.assertFalse(ok)

    def test_pii_in_text_blocked(self):
        ok, _ = classify_for_cache(tool_called="search_sap_docs", text="email a@b.com")
        self.assertFalse(ok)

    def test_redaction_idempotent_and_cacheable(self):
        # After redaction, placeholders must not re-trigger secret detection,
        # so the safe (redacted) answer can be cached.
        raw = "connect postgres://u:p@h:5432/db api_key=sk-proj-ABCD1234EFGH5678"
        once = redact_secrets(raw)
        twice = redact_secrets(once)
        self.assertEqual(once, twice)                 # idempotent
        self.assertFalse(contains_secret(once))       # no secret remains
        ok, reason = classify_for_cache(tool_called="search_sap_tickets", text=once)
        self.assertTrue(ok, reason)

    def test_safe_response_cacheable(self):
        ok, reason = classify_for_cache(
            tool_called="search_sap_tickets",
            text="There are 12 WIP MM tickets in the backlog.",
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")


class TestRedisGraceful(unittest.TestCase):
    def test_disabled_without_redis_url(self):
        import os
        from core import redis_cache
        # Force a clean re-init with REDIS_URL unset.
        os.environ.pop("REDIS_URL", None)
        redis_cache._initialised = False
        redis_cache._enabled = False
        redis_cache._client = None
        self.assertFalse(redis_cache.is_enabled())
        # No-op get/set must not raise.
        self.assertIsNone(redis_cache.get("ns", "user1", "k"))
        self.assertFalse(redis_cache.set("ns", "user1", "k", {"x": 1}))

    def test_make_key_stable_and_short(self):
        from core import redis_cache
        k1 = redis_cache.make_key("a", "b")
        k2 = redis_cache.make_key("a", "b")
        k3 = redis_cache.make_key("a", "c")
        self.assertEqual(k1, k2)
        self.assertNotEqual(k1, k3)
        self.assertEqual(len(k1), 32)


class TestSanitizeSapPayload(unittest.TestCase):
    """Moved out of SAPAgent so ai.manager can apply it to any provider, not
    only to the agent's own cloud-fallback path."""

    def test_strips_the_tool_result_payload(self):
        from core.security import sanitize_sap_payload
        messages = [{
            "role": "user",
            "content": "SAP tool 'get_payslip' returned:\n{\"salary\": 4200000}",
        }]
        out = sanitize_sap_payload(messages)
        self.assertNotIn("4200000", out[0]["content"])
        self.assertIn("get_payslip", out[0]["content"])
        self.assertIn("redacted", out[0]["content"].lower())

    def test_leaves_ordinary_messages_untouched(self):
        from core.security import sanitize_sap_payload
        messages = [{"role": "user", "content": "how do I run MIGO?"}]
        self.assertEqual(messages, sanitize_sap_payload(messages))

    def test_preserves_message_order_and_roles(self):
        from core.security import sanitize_sap_payload
        messages = [
            {"role": "system", "content": "be helpful"},
            {"role": "user", "content": "SAP tool 'x' returned:\n{\"a\": 1}"},
            {"role": "assistant", "content": "ok"},
        ]
        out = sanitize_sap_payload(messages)
        self.assertEqual(["system", "user", "assistant"], [m["role"] for m in out])
        self.assertEqual("be helpful", out[0]["content"])

    def test_does_not_mutate_the_input(self):
        from core.security import sanitize_sap_payload
        messages = [{"role": "user", "content": "SAP tool 'x' returned:\n{\"a\": 1}"}]
        sanitize_sap_payload(messages)
        self.assertIn("\"a\": 1", messages[0]["content"])


if __name__ == "__main__":
    unittest.main()
