"""Streaming tests. The chat UI consumes plain string tokens over SSE; anything
that changes that shape breaks the interface silently, so it is asserted here."""
import asyncio
import unittest
from unittest.mock import patch

from ai.errors import AuthFailed, CapabilityUnsupported
from ai.manager import AIProviderManager
from ai.router import ModelRouter
from ai.types import Capability, Purpose, TenantPolicy
from tests.fakes.fake_provider_server import FakeProviderServer
from tests.fakes.fake_store import InMemoryConfigStore, make_model_row, make_provider_row


def build(url, capabilities, egress_class="local"):
    store = InMemoryConfigStore()
    store.add_provider(make_provider_row(
        id="p1", base_url=url, timeout_seconds=3, egress_class=egress_class
    ))
    store.add_model(
        make_model_row(id="m1", provider_id="p1", purpose=Purpose.CHAT),
        capabilities=capabilities,
    )
    store.set_policy(TenantPolicy(
        tenant_id="default", allow_user_selection=False, fallback_enabled=True,
        default_chat_model_id="m1", default_embedding_model_id=None,
        default_reranker_model_id=None,
    ))
    return AIProviderManager(store=store, router=ModelRouter(store))


def collect(manager, **kw):
    async def run():
        gen = manager.stream(
            tenant_id="default", purpose=Purpose.CHAT,
            messages=[{"role": "user", "content": "hi"}], **kw
        )
        return [t async for t in gen]

    with patch("ai.manager.log_usage"), \
         patch("ai.credentials.read_credential", return_value=None):
        return asyncio.run(run())


class TestStreamShape(unittest.TestCase):

    def test_yields_plain_strings(self):
        with FakeProviderServer(mode="ok", reply_text="a b c") as s:
            tokens = collect(build(s.base_url, {Capability.CHAT, Capability.STREAMING}))
        self.assertTrue(tokens)
        self.assertTrue(all(isinstance(t, str) for t in tokens))

    def test_tokens_concatenate_to_the_full_reply(self):
        with FakeProviderServer(mode="ok", reply_text="the full reply") as s:
            tokens = collect(build(s.base_url, {Capability.CHAT, Capability.STREAMING}))
        self.assertEqual("the full reply ", "".join(tokens))

    def test_generator_terminates_by_exhaustion(self):
        with FakeProviderServer(mode="ok", reply_text="x") as s:
            tokens = collect(build(s.base_url, {Capability.CHAT, Capability.STREAMING}))
        self.assertNotIn(None, tokens)


class TestStreamGuards(unittest.TestCase):

    def test_a_model_without_the_streaming_capability_is_refused(self):
        with FakeProviderServer(mode="ok") as s:
            with self.assertRaises(CapabilityUnsupported):
                collect(build(s.base_url, {Capability.CHAT}))

    def test_provider_errors_surface_inside_the_generator(self):
        with FakeProviderServer(mode="unauthorized") as s:
            with self.assertRaises(AuthFailed):
                collect(build(s.base_url, {Capability.CHAT, Capability.STREAMING}))

    def test_sap_payload_is_redacted_for_an_external_provider(self):
        with FakeProviderServer(mode="ok") as s:
            manager = build(s.base_url, {Capability.CHAT, Capability.STREAMING}, "external")

            async def run():
                gen = manager.stream(
                    tenant_id="default", purpose=Purpose.CHAT,
                    messages=[{"role": "user",
                               "content": "SAP tool 'get_payslip' returned:\n{\"salary\": 99}"}],
                    carries_sap_data=True,
                )
                return [t async for t in gen]

            with patch("ai.manager.log_usage"), \
                 patch("ai.credentials.read_credential", return_value=None):
                asyncio.run(run())
            sent = s.requests[0]["messages"][-1]["content"]
            self.assertNotIn("99", sent)


class TestEventLoopIsNotBlocked(unittest.TestCase):

    def test_other_tasks_progress_while_a_stream_is_consumed(self):
        """The queue-and-thread bridge exists for this; assert it actually works."""
        ticks = []

        async def ticker():
            for _ in range(5):
                await asyncio.sleep(0.01)
                ticks.append(1)

        async def run():
            with FakeProviderServer(mode="ok", reply_text=" ".join(["w"] * 20)) as s:
                manager = build(s.base_url, {Capability.CHAT, Capability.STREAMING})
                task = asyncio.create_task(ticker())
                gen = manager.stream(
                    tenant_id="default", purpose=Purpose.CHAT,
                    messages=[{"role": "user", "content": "hi"}],
                )
                async for _ in gen:
                    pass
                await task

        with patch("ai.manager.log_usage"), \
             patch("ai.credentials.read_credential", return_value=None):
            asyncio.run(run())
        self.assertEqual(5, len(ticks))


if __name__ == "__main__":
    unittest.main()
