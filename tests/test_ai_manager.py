"""Manager tests. The egress cases are the reason this file exists: every path
that can send SAP data to an external provider is asserted here."""
import unittest
from unittest.mock import patch

from ai.manager import AIProviderManager
from ai.router import ModelRouter
from ai.types import Capability, Purpose, TenantPolicy
from tests.fakes.fake_provider_server import FakeProviderServer
from tests.fakes.fake_store import InMemoryConfigStore, make_model_row, make_provider_row

SAP_MESSAGES = [
    {"role": "user", "content": "SAP tool 'get_payslip' returned:\n{\"salary\": 4200000}"}
]


class ManagerTestCase(unittest.TestCase):

    def build(self, server_url, egress_class="local", sap_data_permitted=False):
        store = InMemoryConfigStore()
        store.add_provider(make_provider_row(
            id="p1", name="P", base_url=server_url, timeout_seconds=2,
            egress_class=egress_class, sap_data_permitted=sap_data_permitted,
        ))
        store.add_model(
            make_model_row(id="m1", provider_id="p1", purpose=Purpose.CHAT),
            capabilities={Capability.CHAT, Capability.STREAMING},
        )
        store.set_policy(TenantPolicy(
            tenant_id="default", allow_user_selection=False, fallback_enabled=True,
            default_chat_model_id="m1", default_embedding_model_id=None,
            default_reranker_model_id=None,
        ))
        return AIProviderManager(store=store, router=ModelRouter(store))


class TestDispatch(ManagerTestCase):

    def test_returns_the_provider_response(self):
        with FakeProviderServer(mode="ok", reply_text="answer") as s:
            with patch("ai.manager.log_usage"), patch("ai.credentials.read_credential", return_value=None):
                resp = self.build(s.base_url).chat(
                    tenant_id="default", purpose=Purpose.CHAT,
                    messages=[{"role": "user", "content": "hi"}],
                )
        self.assertEqual("answer", resp.content)

    def test_writes_one_usage_row_per_attempt(self):
        with FakeProviderServer(mode="ok") as s:
            with patch("ai.manager.log_usage") as logged, \
                 patch("ai.credentials.read_credential", return_value=None):
                self.build(s.base_url).chat(
                    tenant_id="default", purpose=Purpose.CHAT,
                    messages=[{"role": "user", "content": "hi"}],
                )
        self.assertEqual(1, logged.call_count)
        record = logged.call_args[0][0]
        self.assertEqual("ok", record.status)
        self.assertEqual("m1", record.model_id)


class TestEgress(ManagerTestCase):
    """The protection that must survive every future refactor."""

    def _sent_content(self, server):
        return server.requests[0]["messages"][-1]["content"]

    def test_local_provider_receives_the_full_payload(self):
        with FakeProviderServer(mode="ok") as s:
            with patch("ai.manager.log_usage"), patch("ai.credentials.read_credential", return_value=None):
                self.build(s.base_url, egress_class="local").chat(
                    tenant_id="default", purpose=Purpose.CHAT,
                    messages=SAP_MESSAGES, carries_sap_data=True,
                )
        self.assertIn("4200000", self._sent_content(s))

    def test_external_provider_without_opt_in_receives_a_redacted_payload(self):
        with FakeProviderServer(mode="ok") as s:
            with patch("ai.manager.log_usage"), patch("ai.credentials.read_credential", return_value=None):
                self.build(s.base_url, egress_class="external").chat(
                    tenant_id="default", purpose=Purpose.CHAT,
                    messages=SAP_MESSAGES, carries_sap_data=True,
                )
        sent = self._sent_content(s)
        self.assertNotIn("4200000", sent)
        self.assertIn("get_payslip", sent)

    def test_external_provider_with_opt_in_receives_the_full_payload(self):
        with FakeProviderServer(mode="ok") as s:
            with patch("ai.manager.log_usage"), patch("ai.credentials.read_credential", return_value=None):
                self.build(s.base_url, egress_class="external", sap_data_permitted=True).chat(
                    tenant_id="default", purpose=Purpose.CHAT,
                    messages=SAP_MESSAGES, carries_sap_data=True,
                )
        self.assertIn("4200000", self._sent_content(s))

    def test_redaction_is_recorded_in_the_usage_log(self):
        with FakeProviderServer(mode="ok") as s:
            with patch("ai.manager.log_usage") as logged, \
                 patch("ai.credentials.read_credential", return_value=None):
                self.build(s.base_url, egress_class="external").chat(
                    tenant_id="default", purpose=Purpose.CHAT,
                    messages=SAP_MESSAGES, carries_sap_data=True,
                )
        self.assertTrue(logged.call_args[0][0].redaction_applied)

    def test_carries_sap_data_false_means_no_redaction_even_externally(self):
        with FakeProviderServer(mode="ok") as s:
            with patch("ai.manager.log_usage"), patch("ai.credentials.read_credential", return_value=None):
                self.build(s.base_url, egress_class="external").chat(
                    tenant_id="default", purpose=Purpose.CHAT,
                    messages=[{"role": "user", "content": "what is MIGO?"}],
                    carries_sap_data=False,
                )
        self.assertIn("MIGO", self._sent_content(s))


class TestFailureLogging(ManagerTestCase):

    def test_a_failed_attempt_is_logged_with_its_error_code(self):
        with FakeProviderServer(mode="unauthorized") as s:
            with patch("ai.manager.log_usage") as logged, \
                 patch("ai.credentials.read_credential", return_value=None):
                with self.assertRaises(Exception):
                    self.build(s.base_url).chat(
                        tenant_id="default", purpose=Purpose.CHAT,
                        messages=[{"role": "user", "content": "hi"}],
                    )
        record = logged.call_args[0][0]
        self.assertEqual("error", record.status)
        self.assertEqual("AuthFailed", record.error_code)


if __name__ == "__main__":
    unittest.main()
