"""Adapter tests. Every case runs against the fake provider server rather than a
mock, so socket handling, timeouts and error mapping are all exercised for real."""
import asyncio
import unittest

from ai.errors import AuthFailed, ModelTimeout, ProviderUnavailable, RateLimited
from ai.providers.ollama import OllamaProvider
from ai.types import Message, ModelConfig, ProviderConfig, ProviderType, Purpose
from tests.fakes.fake_provider_server import FakeProviderServer


def provider_at(url, **over):
    base = dict(
        id="p1", tenant_id="default", name="Fake Ollama",
        provider_type=ProviderType.OLLAMA, base_url=url, organization_id=None,
        deployment_name=None, timeout_seconds=1, max_retries=0,
        egress_class="local", sap_data_permitted=False, is_active=True,
    )
    base.update(over)
    return ProviderConfig(**base)


def a_model(identifier="configured-test-model"):
    return ModelConfig(
        id="m1", tenant_id="default", provider_id="p1", model_name="Test",
        model_identifier=identifier, purpose=Purpose.CHAT, context_window=4096,
        max_tokens=256, temperature=0.2, prompt_profile="registry_tool_json",
        is_active=True,
    )


MESSAGES = [Message(role="user", content="ping")]


class TestOllamaChat(unittest.TestCase):

    def test_returns_content_and_usage(self):
        with FakeProviderServer(mode="ok", reply_text="pong") as s:
            resp = OllamaProvider(provider_at(s.base_url)).chat(a_model(), MESSAGES)
            self.assertEqual("pong", resp.content)
            self.assertEqual(11, resp.usage.prompt_tokens)
            self.assertEqual(7, resp.usage.completion_tokens)

    def test_sends_the_configured_model_identifier(self):
        """The identifier must come from configuration, never from a literal."""
        with FakeProviderServer(mode="ok") as s:
            OllamaProvider(provider_at(s.base_url)).chat(a_model("whatever-admin-typed"), MESSAGES)
            self.assertEqual("whatever-admin-typed", s.requests[0]["model"])

    def test_sends_configured_temperature_and_max_tokens(self):
        with FakeProviderServer(mode="ok") as s:
            OllamaProvider(provider_at(s.base_url)).chat(a_model(), MESSAGES)
            options = s.requests[0]["options"]
            self.assertAlmostEqual(0.2, options["temperature"])
            self.assertEqual(256, options["num_predict"])

    def test_unreachable_maps_to_provider_unavailable(self):
        provider = provider_at("http://127.0.0.1:1")   # nothing listens on port 1
        with self.assertRaises(ProviderUnavailable):
            OllamaProvider(provider).chat(a_model(), MESSAGES)

    def test_503_maps_to_provider_unavailable(self):
        with FakeProviderServer(mode="unavailable") as s:
            with self.assertRaises(ProviderUnavailable):
                OllamaProvider(provider_at(s.base_url)).chat(a_model(), MESSAGES)

    def test_401_maps_to_auth_failed(self):
        with FakeProviderServer(mode="unauthorized") as s:
            with self.assertRaises(AuthFailed):
                OllamaProvider(provider_at(s.base_url)).chat(a_model(), MESSAGES)

    def test_429_maps_to_rate_limited(self):
        with FakeProviderServer(mode="rate_limited") as s:
            with self.assertRaises(RateLimited):
                OllamaProvider(provider_at(s.base_url)).chat(a_model(), MESSAGES)

    def test_slow_response_maps_to_model_timeout(self):
        with FakeProviderServer(mode="slow") as s:
            with self.assertRaises(ModelTimeout):
                OllamaProvider(provider_at(s.base_url, timeout_seconds=1)).chat(a_model(), MESSAGES)

    def test_malformed_response_maps_to_provider_unavailable(self):
        with FakeProviderServer(mode="malformed") as s:
            with self.assertRaises(ProviderUnavailable):
                OllamaProvider(provider_at(s.base_url)).chat(a_model(), MESSAGES)

    def test_errors_carry_provider_name(self):
        with FakeProviderServer(mode="unauthorized") as s:
            with self.assertRaises(AuthFailed) as ctx:
                OllamaProvider(provider_at(s.base_url)).chat(a_model(), MESSAGES)
            self.assertEqual("Fake Ollama", ctx.exception.provider_name)


class TestOllamaStream(unittest.TestCase):

    def _collect(self, provider, model):
        async def run():
            return [t async for t in provider.stream(model, MESSAGES)]
        return asyncio.run(run())

    def test_yields_plain_string_tokens(self):
        with FakeProviderServer(mode="ok", reply_text="one two three") as s:
            tokens = self._collect(OllamaProvider(provider_at(s.base_url)), a_model())
            self.assertTrue(all(isinstance(t, str) for t in tokens))
            self.assertEqual("one two three ", "".join(tokens))

    def test_stream_failure_raises_inside_the_generator(self):
        with FakeProviderServer(mode="unauthorized") as s:
            with self.assertRaises(AuthFailed):
                self._collect(OllamaProvider(provider_at(s.base_url)), a_model())


class TestOllamaEmbedHealthAndList(unittest.TestCase):

    def test_embed_returns_one_vector_per_text(self):
        with FakeProviderServer(mode="ok") as s:
            vectors = OllamaProvider(provider_at(s.base_url)).embed(a_model(), ["a", "b"])
            self.assertEqual(2, len(vectors))
            self.assertEqual([0.1, 0.2, 0.3], vectors[0])

    def test_health_check_reports_healthy_with_latency(self):
        with FakeProviderServer(mode="ok") as s:
            result = OllamaProvider(provider_at(s.base_url)).health_check()
            self.assertEqual("healthy", result.status)
            self.assertGreaterEqual(result.latency_ms, 0)

    def test_health_check_never_raises(self):
        result = OllamaProvider(provider_at("http://127.0.0.1:1")).health_check()
        self.assertEqual("unreachable", result.status)
        self.assertIsNotNone(result.error)

    def test_list_models_returns_identifiers(self):
        with FakeProviderServer(mode="ok", model_name="some-model:tag") as s:
            self.assertEqual(["some-model:tag"], OllamaProvider(provider_at(s.base_url)).list_models())

    def test_list_models_returns_empty_when_unreachable(self):
        self.assertEqual([], OllamaProvider(provider_at("http://127.0.0.1:1")).list_models())


if __name__ == "__main__":
    unittest.main()
