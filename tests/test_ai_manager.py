"""Manager tests. The egress cases are the reason this file exists: every path
that can send SAP data to an external provider is asserted here."""
import asyncio
import unittest
from unittest.mock import patch

from ai.errors import CapabilityUnsupported, NoModelConfigured
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


class TestResolutionFailureLogging(unittest.TestCase):
    """A misconfiguration that blocks every request must still be visible in
    the audit trail: with no model ever resolved, this is the only row an
    administrator debugging "the assistant stopped answering" would see."""

    def test_no_model_configured_writes_one_error_row(self):
        store = InMemoryConfigStore()
        store.set_policy(TenantPolicy(
            tenant_id="default", allow_user_selection=False, fallback_enabled=True,
            default_chat_model_id=None, default_embedding_model_id=None,
            default_reranker_model_id=None,
        ))
        manager = AIProviderManager(store=store, router=ModelRouter(store))
        with patch("ai.manager.log_usage") as logged:
            with self.assertRaises(NoModelConfigured):
                manager.chat(
                    tenant_id="default", purpose=Purpose.CHAT,
                    messages=[{"role": "user", "content": "hi"}],
                )
        self.assertEqual(1, logged.call_count)
        record = logged.call_args[0][0]
        self.assertEqual("error", record.status)
        self.assertEqual("NoModelConfigured", record.error_code)
        self.assertIsNone(record.model_id)
        self.assertIsNone(record.provider_id)

    def test_stream_with_missing_capability_writes_one_error_row(self):
        """A model registered for chat but not for streaming is a routine,
        expected configuration state — the administrator will want this
        recorded, not silently absorbed by the caller's non-streaming
        fallback."""
        store = InMemoryConfigStore()
        store.add_provider(make_provider_row(id="p1", name="P", base_url="http://unused"))
        store.add_model(
            make_model_row(id="m1", provider_id="p1", purpose=Purpose.CHAT),
            capabilities={Capability.CHAT},  # deliberately no Capability.STREAMING
        )
        store.set_policy(TenantPolicy(
            tenant_id="default", allow_user_selection=False, fallback_enabled=True,
            default_chat_model_id="m1", default_embedding_model_id=None,
            default_reranker_model_id=None,
        ))
        manager = AIProviderManager(store=store, router=ModelRouter(store))
        with patch("ai.manager.log_usage") as logged:
            with self.assertRaises(CapabilityUnsupported):
                manager.stream(
                    tenant_id="default", purpose=Purpose.CHAT,
                    messages=[{"role": "user", "content": "hi"}],
                )
        self.assertEqual(1, logged.call_count)
        record = logged.call_args[0][0]
        self.assertEqual("error", record.status)
        self.assertEqual("CapabilityUnsupported", record.error_code)
        self.assertIsNone(record.model_id)
        self.assertIsNone(record.provider_id)

    def test_embed_with_no_model_configured_writes_one_error_row(self):
        store = InMemoryConfigStore()
        store.set_policy(TenantPolicy(
            tenant_id="default", allow_user_selection=False, fallback_enabled=True,
            default_chat_model_id=None, default_embedding_model_id=None,
            default_reranker_model_id=None,
        ))
        manager = AIProviderManager(store=store, router=ModelRouter(store))
        with patch("ai.manager.log_usage") as logged:
            with self.assertRaises(NoModelConfigured):
                manager.embed(tenant_id="default", texts=["hello"])
        self.assertEqual(1, logged.call_count)
        record = logged.call_args[0][0]
        self.assertEqual("error", record.status)
        self.assertEqual("NoModelConfigured", record.error_code)
        self.assertIsNone(record.model_id)
        self.assertIsNone(record.provider_id)


class EmbedManagerTestCase(unittest.TestCase):

    def build(self, server_url, egress_class="local", sap_data_permitted=False):
        store = InMemoryConfigStore()
        store.add_provider(make_provider_row(
            id="p1", name="P", base_url=server_url, timeout_seconds=2,
            egress_class=egress_class, sap_data_permitted=sap_data_permitted,
        ))
        store.add_model(
            make_model_row(id="m1", provider_id="p1", purpose=Purpose.EMBEDDING),
            capabilities={Capability.EMBEDDING},
        )
        store.set_policy(TenantPolicy(
            tenant_id="default", allow_user_selection=False, fallback_enabled=True,
            default_chat_model_id=None, default_embedding_model_id="m1",
            default_reranker_model_id=None,
        ))
        return AIProviderManager(store=store, router=ModelRouter(store))


class TestEmbedEgress(EmbedManagerTestCase):
    """embed() makes the same three-way redaction decision as chat(). The gap
    was latent — nothing calls embed() yet — but the RAG work that follows
    this plan builds directly on it, so the gate must already be shut."""

    def test_local_provider_receives_the_full_text(self):
        with FakeProviderServer(mode="ok") as s:
            with patch("ai.manager.log_usage") as logged, \
                 patch("ai.credentials.read_credential", return_value=None):
                self.build(s.base_url, egress_class="local").embed(
                    tenant_id="default",
                    texts=[SAP_MESSAGES[0]["content"]],
                    carries_sap_data=True,
                )
        self.assertIn("4200000", s.requests[-1]["prompt"])
        self.assertFalse(logged.call_args[0][0].redaction_applied)

    def test_external_provider_without_opt_in_receives_redacted_text(self):
        with FakeProviderServer(mode="ok") as s:
            with patch("ai.manager.log_usage") as logged, \
                 patch("ai.credentials.read_credential", return_value=None):
                self.build(s.base_url, egress_class="external").embed(
                    tenant_id="default",
                    texts=[SAP_MESSAGES[0]["content"]],
                    carries_sap_data=True,
                )
        sent = s.requests[-1]["prompt"]
        self.assertNotIn("4200000", sent)
        self.assertIn("get_payslip", sent)
        self.assertTrue(logged.call_args[0][0].redaction_applied)


class TestStreamLogging(ManagerTestCase):
    """stream() has no fallback, but it must still log honestly. This is the
    same defect class corrected in FallbackChain.execute's on_attempt
    asymmetry (a failed attempt must never be reported as `error is None`),
    applied to the one dispatch path that isn't routed through that chain."""

    def test_a_successful_stream_is_logged_as_ok(self):
        with FakeProviderServer(mode="ok", reply_text="hello world") as s:
            with patch("ai.manager.log_usage") as logged, \
                 patch("ai.credentials.read_credential", return_value=None):
                manager = self.build(s.base_url)

                async def run():
                    return [t async for t in manager.stream(
                        tenant_id="default", purpose=Purpose.CHAT,
                        messages=[{"role": "user", "content": "hi"}],
                    )]

                tokens = asyncio.run(run())
        self.assertTrue("".join(tokens).strip())
        self.assertEqual(1, logged.call_count)
        self.assertEqual("ok", logged.call_args[0][0].status)

    def test_a_failed_stream_is_logged_with_its_error_code(self):
        with FakeProviderServer(mode="unauthorized") as s:
            with patch("ai.manager.log_usage") as logged, \
                 patch("ai.credentials.read_credential", return_value=None):
                manager = self.build(s.base_url)

                async def run():
                    return [t async for t in manager.stream(
                        tenant_id="default", purpose=Purpose.CHAT,
                        messages=[{"role": "user", "content": "hi"}],
                    )]

                with self.assertRaises(Exception):
                    asyncio.run(run())
        self.assertEqual(1, logged.call_count)
        record = logged.call_args[0][0]
        self.assertEqual("error", record.status)
        self.assertEqual("AuthFailed", record.error_code)

    def test_a_cancelled_stream_is_logged_as_cancelled(self):
        """The consumer stopping early -- a UI stop button, a dropped
        connection, garbage collection -- throws GeneratorExit at the
        suspended yield. That must still produce a usage row."""
        with FakeProviderServer(mode="ok", reply_text="hello world foo bar baz") as s:
            with patch("ai.manager.log_usage") as logged, \
                 patch("ai.credentials.read_credential", return_value=None):
                manager = self.build(s.base_url)

                async def run():
                    gen = manager.stream(
                        tenant_id="default", purpose=Purpose.CHAT,
                        messages=[{"role": "user", "content": "hi"}],
                    )
                    async for _ in gen:
                        break
                    await gen.aclose()

                asyncio.run(run())
        self.assertEqual(1, logged.call_count)
        record = logged.call_args[0][0]
        self.assertEqual("cancelled", record.status)


if __name__ == "__main__":
    unittest.main()
