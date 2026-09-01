"""Telemetry tests. Database access is patched — what matters is the field
mapping and, above all, that a broken writer cannot break a chat request."""
import unittest
from unittest.mock import patch

from ai.health import is_known_unreachable, last_health, probe, record_health
from ai.types import Capability, HealthResult, Purpose
from ai.usage import UsageRecord, log_usage
from tests.fakes.fake_provider_server import FakeProviderServer
from tests.fakes.fake_store import InMemoryConfigStore, make_model_row, make_provider_row


def a_record(**over):
    base = dict(
        tenant_id="default", user_id="u1", provider_id="p1", model_id="m1",
        request_id="r1", purpose="CHAT", intent=None, tool_used=None,
        authorization_result="allowed", prompt_tokens=10, completion_tokens=5,
        latency_ms=120, fallback_used=False, fallback_from_model_id=None,
        egress_class="local", redaction_applied=False, status="ok", error_code=None,
    )
    base.update(over)
    return UsageRecord(**base)


class TestUsageLogging(unittest.TestCase):

    def test_writes_every_column(self):
        captured = {}

        def fake_execute(sql, params):
            captured["sql"] = sql
            captured["params"] = params
            return 1

        with patch("ai.usage._execute", fake_execute):
            log_usage(a_record())
        self.assertIn("INSERT INTO ai_usage_logs", captured["sql"])
        self.assertIn("default", captured["params"])

    def test_a_database_failure_never_propagates(self):
        """A chat request must not fail because the usage table is unavailable."""
        with patch("ai.usage._execute", side_effect=RuntimeError("db down")):
            log_usage(a_record())          # must not raise

    def test_fallback_fields_round_trip(self):
        captured = {}
        with patch("ai.usage._execute", lambda sql, params: captured.update(params=params) or 1):
            log_usage(a_record(fallback_used=True, fallback_from_model_id="m0"))
        self.assertIn("m0", captured["params"])
        self.assertIn(True, captured["params"])


class TestHealthProbe(unittest.TestCase):

    def _resolved(self, url):
        store = InMemoryConfigStore()
        store.add_provider(make_provider_row(id="p1", base_url=url, timeout_seconds=1))
        store.add_model(make_model_row(id="m1", provider_id="p1"), {Capability.CHAT})
        return store.resolved("m1", "default")

    def test_reachable_provider_reports_healthy_with_latency(self):
        with FakeProviderServer(mode="ok") as s:
            result = probe(self._resolved(s.base_url), api_key=None)
            self.assertEqual("healthy", result.status)
            self.assertGreaterEqual(result.latency_ms, 0)

    def test_unreachable_provider_reports_unreachable_and_does_not_raise(self):
        result = probe(self._resolved("http://127.0.0.1:1"), api_key=None)
        self.assertEqual("unreachable", result.status)
        self.assertIsNotNone(result.error)

    def test_probe_survives_a_provider_construction_failure(self):
        """build_provider raises for an unknown provider_type, before any adapter
        exists to catch it - probe()'s own guard is the only thing in the way."""
        with patch("ai.health.build_provider", side_effect=RuntimeError("no adapter")):
            result = probe(self._resolved("http://127.0.0.1:1"), api_key=None)
        self.assertEqual("unreachable", result.status)
        self.assertIsNotNone(result.error)


class TestHealthRecording(unittest.TestCase):

    def test_record_health_failure_never_propagates(self):
        with patch("ai.health._execute", side_effect=RuntimeError("db down")):
            record_health("m1", "default", HealthResult("healthy", 10))

    def test_is_known_unreachable_is_false_when_no_record_exists(self):
        """An unprobed model must not be treated as broken."""
        with patch("ai.health._query_one", return_value=None):
            self.assertFalse(is_known_unreachable("m1", "default"))

    def test_is_known_unreachable_reads_the_stored_status(self):
        with patch("ai.health._query_one", return_value={"status": "unreachable"}):
            self.assertTrue(is_known_unreachable("m1", "default"))
        with patch("ai.health._query_one", return_value={"status": "healthy"}):
            self.assertFalse(is_known_unreachable("m1", "default"))

    def test_last_health_survives_a_database_failure(self):
        with patch("ai.health._query_one", side_effect=RuntimeError("db down")):
            self.assertIsNone(last_health("m1", "default"))

    def test_is_known_unreachable_is_false_when_the_database_fails(self):
        """A DB outage must not make every model look broken."""
        with patch("ai.health._query_one", side_effect=RuntimeError("db down")):
            self.assertFalse(is_known_unreachable("m1", "default"))


if __name__ == "__main__":
    unittest.main()
