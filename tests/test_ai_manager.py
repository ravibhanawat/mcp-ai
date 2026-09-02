"""Manager tests. The egress cases are the reason this file exists: every path
that can send SAP data to an external provider is asserted here."""
import asyncio
import json
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

    def test_report_agent_shaped_system_message_is_redacted_externally(self):
        """agent.report_agent._format embeds json.dumps(collected_data) into
        the *system* message with no 'SAP tool ... returned:' prefix — the
        exact shape core/security.py's old prefix-only match could never see
        (Critical 2). This must not reach an external, unpermitted provider."""
        report_agent_system_message = [
            {
                "role": "system",
                "content": (
                    "Format this data into a chart:\n"
                    "{\n  \"get_payslip\": {\"salary\": 4200000, \"account\": \"ACC-9911\"}\n}"
                ),
                "sap_payload": True,
            },
            {"role": "user", "content": "Format the collected data into the chart payload JSON."},
        ]
        with FakeProviderServer(mode="ok") as s:
            with patch("ai.manager.log_usage") as logged, \
                 patch("ai.credentials.read_credential", return_value=None):
                self.build(s.base_url, egress_class="external").chat(
                    tenant_id="default", purpose=Purpose.SUMMARIZATION,
                    messages=report_agent_system_message, carries_sap_data=True,
                )
        sent = json.dumps(s.requests[-1])
        self.assertNotIn("4200000", sent)
        self.assertNotIn("ACC-9911", sent)
        self.assertTrue(logged.call_args[0][0].redaction_applied)

    def test_autonomous_agent_shaped_user_message_is_redacted_externally(self):
        """agent.autonomous_agent._build_context / _run_reasoning embed
        json.dumps(...) of raw tool results into a *user* message with no
        prefix shape either. Same Critical 2 gap, different agent and role."""
        autonomous_agent_user_message = [
            {"role": "system", "content": "You are a senior SAP business consultant."},
            {
                "role": "user",
                "content": (
                    "COLLECTED DATA SUMMARY:\n"
                    "[get_payslip]: {\"salary\": 4200000, \"account\": \"ACC-9911\"}"
                ),
                "sap_payload": True,
            },
        ]
        with FakeProviderServer(mode="ok") as s:
            with patch("ai.manager.log_usage") as logged, \
                 patch("ai.credentials.read_credential", return_value=None):
                self.build(s.base_url, egress_class="external").chat(
                    tenant_id="default", purpose=Purpose.REASONING,
                    messages=autonomous_agent_user_message, carries_sap_data=True,
                )
        sent = json.dumps(s.requests[-1])
        self.assertNotIn("4200000", sent)
        self.assertNotIn("ACC-9911", sent)
        self.assertTrue(logged.call_args[0][0].redaction_applied)

    def test_sap_agent_real_tool_response_prompt_is_redacted_externally(self):
        """The whole-branch review's own C2 finding, closed the wrong way
        once already: every redaction test in this repository — including
        the two above — asserts against a HAND-AUTHORED message shape. That
        is exactly how the real bug survived two full reviews.
        SAPAgent._format_tool_response (agent/sap_agent.py) builds:
            'The user asked: "..."\n\nSAP tool 'X' returned this data:\n{...}'
        which matches NEITHER half of the original prefix predicate — it does
        not start with "SAP tool '" (it starts with "The user asked:"), and
        "returned this data:" does not contain the substring "returned:".
        This drives the REAL agent method end to end rather than a message
        this test wrote, so it cannot pass by construction."""
        from agent.sap_agent import SAPAgent

        with FakeProviderServer(mode="ok") as s:
            manager = self.build(s.base_url, egress_class="external", sap_data_permitted=False)
            agent = SAPAgent(manager=manager, tenant_id="default")
            with patch("ai.manager.log_usage") as logged, \
                 patch("ai.credentials.read_credential", return_value=None):
                agent._format_tool_response(
                    user_message="What is Priya's salary?",
                    tool_name="get_payslip",
                    tool_result={"salary": 4200000, "account": "ACC-9911", "employee": "Priya"},
                )
        sent = json.dumps(s.requests[-1])
        self.assertNotIn("4200000", sent)
        self.assertNotIn("ACC-9911", sent)
        self.assertTrue(logged.call_args[0][0].redaction_applied)

    def test_sap_agent_real_streaming_tool_response_prompt_is_redacted_externally(self):
        """Same defect, streaming path: _format_tool_response_stream builds
        the identical prompt shape and dispatches through manager.stream()."""
        import asyncio
        from agent.sap_agent import SAPAgent

        with FakeProviderServer(mode="ok", reply_text="a plain-text summary") as s:
            manager = self.build(s.base_url, egress_class="external", sap_data_permitted=False)
            agent = SAPAgent(manager=manager, tenant_id="default")

            async def _drain():
                chunks = []
                async for chunk in agent._format_tool_response_stream(
                    user_message="What is Priya's salary?",
                    tool_name="get_payslip",
                    tool_result={"salary": 4200000, "account": "ACC-9911", "employee": "Priya"},
                ):
                    chunks.append(chunk)
                return chunks

            with patch("ai.manager.log_usage"), \
                 patch("ai.credentials.read_credential", return_value=None):
                asyncio.run(_drain())
        sent = json.dumps(s.requests[-1])
        self.assertNotIn("4200000", sent)
        self.assertNotIn("ACC-9911", sent)

    def test_carries_sap_data_false_means_no_redaction_even_externally(self):
        with FakeProviderServer(mode="ok") as s:
            with patch("ai.manager.log_usage"), patch("ai.credentials.read_credential", return_value=None):
                self.build(s.base_url, egress_class="external").chat(
                    tenant_id="default", purpose=Purpose.CHAT,
                    messages=[{"role": "user", "content": "what is MIGO?"}],
                    carries_sap_data=False,
                )
        self.assertIn("MIGO", self._sent_content(s))


class TestRedactionFailsClosedOnTheAuditTrail(ManagerTestCase):
    """A carries_sap_data=True call to an external, unpermitted provider where
    no message actually matches a known SAP-payload shape (prefix or marker)
    is a caller bug, not a clean pass. The audit trail must say what actually
    happened, never what was merely intended."""

    def test_unmatched_sap_bearing_call_is_not_recorded_as_redacted(self):
        with FakeProviderServer(mode="ok") as s:
            with patch("ai.manager.log_usage") as logged, \
                 patch("ai.credentials.read_credential", return_value=None):
                self.build(s.base_url, egress_class="external").chat(
                    tenant_id="default", purpose=Purpose.CHAT,
                    # carries_sap_data=True, but nothing here is shaped as a
                    # SAP payload the redactor recognises — the caller-bug case.
                    messages=[{"role": "user", "content": "plain text, no marker"}],
                    carries_sap_data=True,
                )
        self.assertFalse(logged.call_args[0][0].redaction_applied)

    def test_a_warning_is_logged_when_redaction_was_required_but_had_no_effect(self):
        with self.assertLogs("ai.manager", level="WARNING") as cm:
            with FakeProviderServer(mode="ok") as s:
                with patch("ai.manager.log_usage"), \
                     patch("ai.credentials.read_credential", return_value=None):
                    self.build(s.base_url, egress_class="external").chat(
                        tenant_id="default", purpose=Purpose.CHAT,
                        messages=[{"role": "user", "content": "plain text, no marker"}],
                        carries_sap_data=True,
                    )
        self.assertTrue(any("Redaction was required" in m for m in cm.output))


class TestDeniedSelectionAuditing(unittest.TestCase):
    """Important I8: ai.router.ModelRouter refuses a requested_model_id
    (policy or allowlist) by falling back to another source rather than
    raising — the request still succeeds, just not with the model the caller
    asked for. Before this fix, ai.manager._record hard-coded
    authorization_result="allowed" for every successful dispatch, so that
    refusal never reached ai_usage_logs at all: an administrator auditing
    "who tried to use a model they weren't allowed to" would see nothing."""

    def build(self, server_url):
        store = InMemoryConfigStore()
        store.add_provider(make_provider_row(id="p1", name="P", base_url=server_url, timeout_seconds=2))
        store.add_model(
            make_model_row(id="chat-local", provider_id="p1", purpose=Purpose.CHAT),
            capabilities={Capability.CHAT},
        )
        store.add_model(
            make_model_row(id="chat-cloud", provider_id="p1", purpose=Purpose.CHAT),
            capabilities={Capability.CHAT},
        )
        store.set_policy(TenantPolicy(
            tenant_id="default", allow_user_selection=True, fallback_enabled=False,
            default_chat_model_id="chat-local", default_embedding_model_id=None,
            default_reranker_model_id=None,
        ))
        # Deliberately NOT marking chat-cloud user_selectable: the request
        # below asks for it anyway.
        return AIProviderManager(store=store, router=ModelRouter(store))

    def test_a_refused_selection_is_recorded_as_denied_even_though_the_request_succeeds(self):
        with FakeProviderServer(mode="ok") as s:
            with patch("ai.manager.log_usage") as logged, \
                 patch("ai.credentials.read_credential", return_value=None):
                resp = self.build(s.base_url).chat(
                    tenant_id="default", purpose=Purpose.CHAT,
                    messages=[{"role": "user", "content": "hi"}],
                    requested_model_id="chat-cloud",
                )
        self.assertEqual(1, logged.call_count)
        record = logged.call_args[0][0]
        self.assertEqual("ok", record.status)
        self.assertEqual("chat-local", record.model_id)
        self.assertEqual("denied", record.authorization_result)

    def test_an_honoured_selection_is_recorded_as_allowed(self):
        with FakeProviderServer(mode="ok") as s:
            store = InMemoryConfigStore()
            store.add_provider(make_provider_row(id="p1", name="P", base_url=s.base_url, timeout_seconds=2))
            store.add_model(
                make_model_row(id="chat-local", provider_id="p1", purpose=Purpose.CHAT),
                capabilities={Capability.CHAT},
            )
            store.add_model(
                make_model_row(id="chat-cloud", provider_id="p1", purpose=Purpose.CHAT),
                capabilities={Capability.CHAT},
            )
            store.set_policy(TenantPolicy(
                tenant_id="default", allow_user_selection=True, fallback_enabled=False,
                default_chat_model_id="chat-local", default_embedding_model_id=None,
                default_reranker_model_id=None,
            ))
            store.set_tenant_model("default", "chat-cloud", user_selectable=True)
            manager = AIProviderManager(store=store, router=ModelRouter(store))
            with patch("ai.manager.log_usage") as logged, \
                 patch("ai.credentials.read_credential", return_value=None):
                manager.chat(
                    tenant_id="default", purpose=Purpose.CHAT,
                    messages=[{"role": "user", "content": "hi"}],
                    requested_model_id="chat-cloud",
                )
        record = logged.call_args[0][0]
        self.assertEqual("chat-cloud", record.model_id)
        self.assertEqual("allowed", record.authorization_result)


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

    def test_a_task_cancelled_stream_is_logged_as_cancelled(self):
        """asyncio.CancelledError -- not GeneratorExit -- is what a real ASGI
        server throws into the generator when a client disconnects mid-stream.
        It must be told apart from a clean finish, not fall through to the
        default status="ok"."""
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
                    with self.assertRaises(asyncio.CancelledError):
                        await gen.athrow(asyncio.CancelledError())

                asyncio.run(run())
        self.assertEqual(1, logged.call_count)
        record = logged.call_args[0][0]
        self.assertEqual("cancelled", record.status)


if __name__ == "__main__":
    unittest.main()
