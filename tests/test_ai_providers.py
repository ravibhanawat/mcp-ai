"""Adapter tests. Every case runs against the fake provider server rather than a
mock, so socket handling, timeouts and error mapping are all exercised for real."""
import asyncio
import os
import unittest
from unittest.mock import patch

from ai.errors import AuthFailed, ModelTimeout, ProviderUnavailable, RateLimited
from ai.providers.ollama import OllamaProvider
from ai.providers.openai_compat import OpenAICompatProvider
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


def openai_provider_at(url, ptype=ProviderType.OPENAI, **over):
    base = dict(
        id="p2", tenant_id="default", name="Fake OpenAI", provider_type=ptype,
        base_url=url, organization_id=None, deployment_name=None,
        timeout_seconds=1, max_retries=0, egress_class="external",
        sap_data_permitted=False, is_active=True,
    )
    base.update(over)
    return ProviderConfig(**base)


class TestOpenAICompatChat(unittest.TestCase):

    def test_returns_content_and_usage(self):
        with FakeProviderServer(mode="ok", reply_text="pong") as s:
            p = OpenAICompatProvider(openai_provider_at(s.base_url), api_key="sk-test")
            resp = p.chat(a_model(), MESSAGES)
            self.assertEqual("pong", resp.content)
            self.assertEqual(11, resp.usage.prompt_tokens)

    def test_sends_bearer_credential_from_argument(self):
        with FakeProviderServer(mode="ok") as s:
            OpenAICompatProvider(openai_provider_at(s.base_url), api_key="sk-explicit").chat(
                a_model(), MESSAGES
            )
            self.assertEqual("Bearer sk-explicit", s.headers_seen[0]["Authorization"])

    def test_never_reads_the_ambient_environment_key(self):
        """The reason this codebase does not use litellm. Must stay true."""
        with FakeProviderServer(mode="ok") as s:
            with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-ambient-must-not-leak"}):
                OpenAICompatProvider(openai_provider_at(s.base_url), api_key="sk-explicit").chat(
                    a_model(), MESSAGES
                )
            sent = s.headers_seen[0].get("Authorization", "")
            self.assertNotIn("ambient", sent)

    def test_never_falls_back_to_the_ambient_key_when_none_is_configured(self):
        """Closes the gap in the case above: this must hold even when the
        caller passes no explicit key at all — the exact fallback litellm
        performs and this adapter must never perform."""
        with FakeProviderServer(mode="ok") as s:
            with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-ambient-must-not-leak"}):
                OpenAICompatProvider(openai_provider_at(s.base_url), api_key=None).chat(
                    a_model(), MESSAGES
                )
            headers = s.headers_seen[0]
            self.assertNotIn("Authorization", headers)
            self.assertNotIn("api-key", headers)

    def test_azure_builds_deployment_url_and_api_key_header(self):
        with FakeProviderServer(mode="ok") as s:
            p = OpenAICompatProvider(
                openai_provider_at(s.base_url, ProviderType.AZURE_OPENAI,
                                   deployment_name="my-deployment"),
                api_key="azure-key",
            )
            p.chat(a_model(), MESSAGES)
            self.assertEqual("azure-key", s.headers_seen[0]["api-key"])
            self.assertNotIn("Authorization", s.headers_seen[0])
            path = s.paths_seen[0]
            self.assertIn("/openai/deployments/my-deployment/chat/completions", path)
            self.assertNotIn("/v1/chat/completions", path)
            self.assertIn("api-version=", path)

    def test_azure_model_listing_is_account_scoped_not_deployment_scoped(self):
        """Azure's model listing is not namespaced under a deployment. If
        list_models()/health_check() requested a deployment-scoped URL, a
        real Azure tenant would 404 here and the provider could never pass
        the Task 15 activation gate."""
        with FakeProviderServer(mode="ok", model_name="cfg-model") as s:
            p = OpenAICompatProvider(
                openai_provider_at(s.base_url, ProviderType.AZURE_OPENAI,
                                   deployment_name="my-deployment"),
                api_key="azure-key",
            )
            self.assertEqual(["cfg-model"], p.list_models())
            path = s.paths_seen[0]
            self.assertIn("/openai/models", path)
            self.assertNotIn("/openai/deployments/", path)
            self.assertIn("api-version=", path)

    def test_sends_organization_header_when_configured(self):
        with FakeProviderServer(mode="ok") as s:
            OpenAICompatProvider(
                openai_provider_at(s.base_url, organization_id="org-123"), api_key="k"
            ).chat(a_model(), MESSAGES)
            self.assertEqual("org-123", s.headers_seen[0]["OpenAI-Organization"])

    def test_401_maps_to_auth_failed(self):
        with FakeProviderServer(mode="unauthorized") as s:
            with self.assertRaises(AuthFailed):
                OpenAICompatProvider(openai_provider_at(s.base_url), api_key="k").chat(
                    a_model(), MESSAGES
                )

    def test_429_maps_to_rate_limited(self):
        with FakeProviderServer(mode="rate_limited") as s:
            with self.assertRaises(RateLimited):
                OpenAICompatProvider(openai_provider_at(s.base_url), api_key="k").chat(
                    a_model(), MESSAGES
                )

    def test_timeout_maps_to_model_timeout(self):
        with FakeProviderServer(mode="slow") as s:
            with self.assertRaises(ModelTimeout):
                OpenAICompatProvider(
                    openai_provider_at(s.base_url, timeout_seconds=1), api_key="k"
                ).chat(a_model(), MESSAGES)

    def test_stream_yields_tokens_from_sse(self):
        async def run(p):
            return [t async for t in p.stream(a_model(), MESSAGES)]

        with FakeProviderServer(mode="ok", reply_text="alpha beta") as s:
            p = OpenAICompatProvider(openai_provider_at(s.base_url), api_key="k")
            self.assertEqual("alpha beta ", "".join(asyncio.run(run(p))))

    def test_embed_returns_vectors(self):
        with FakeProviderServer(mode="ok") as s:
            p = OpenAICompatProvider(openai_provider_at(s.base_url), api_key="k")
            self.assertEqual([[0.1, 0.2, 0.3]], p.embed(a_model(), ["text"]))

    def test_list_models_returns_identifiers(self):
        with FakeProviderServer(mode="ok", model_name="cfg-model") as s:
            p = OpenAICompatProvider(openai_provider_at(s.base_url), api_key="k")
            self.assertEqual(["cfg-model"], p.list_models())


from ai.providers.anthropic_provider import AnthropicProvider
from ai.providers.registry import UnsupportedProviderType, build_provider


def anthropic_provider_at(url, **over):
    base = dict(
        id="p3", tenant_id="default", name="Fake Anthropic",
        provider_type=ProviderType.ANTHROPIC, base_url=url, organization_id=None,
        deployment_name=None, timeout_seconds=1, max_retries=0,
        egress_class="external", sap_data_permitted=False, is_active=True,
    )
    base.update(over)
    return ProviderConfig(**base)


class TestAnthropicAdapter(unittest.TestCase):

    def test_returns_content_and_usage(self):
        with FakeProviderServer(mode="ok", reply_text="pong") as s:
            resp = AnthropicProvider(anthropic_provider_at(s.base_url), api_key="sk-ant-x").chat(
                a_model(), MESSAGES
            )
            self.assertEqual("pong", resp.content)
            self.assertEqual(11, resp.usage.prompt_tokens)
            self.assertEqual(7, resp.usage.completion_tokens)

    def test_system_message_is_hoisted_out_of_the_message_list(self):
        with FakeProviderServer(mode="ok") as s:
            AnthropicProvider(anthropic_provider_at(s.base_url), api_key="k").chat(
                a_model(),
                [Message(role="system", content="be terse"), Message(role="user", content="hi")],
            )
            body = s.requests[0]
            self.assertEqual("be terse", body["system"])
            self.assertEqual([{"role": "user", "content": "hi"}], body["messages"])

    def test_sends_x_api_key_header(self):
        with FakeProviderServer(mode="ok") as s:
            AnthropicProvider(anthropic_provider_at(s.base_url), api_key="sk-ant-explicit").chat(
                a_model(), MESSAGES
            )
            self.assertEqual("sk-ant-explicit", s.headers_seen[0]["x-api-key"])

    def test_401_maps_to_auth_failed(self):
        with FakeProviderServer(mode="unauthorized") as s:
            with self.assertRaises(AuthFailed):
                AnthropicProvider(anthropic_provider_at(s.base_url), api_key="k").chat(
                    a_model(), MESSAGES
                )

    def test_embed_raises_capability_unsupported(self):
        """Anthropic has no embeddings API. The registry must not pretend otherwise."""
        from ai.errors import CapabilityUnsupported
        with FakeProviderServer(mode="ok") as s:
            with self.assertRaises(CapabilityUnsupported):
                AnthropicProvider(anthropic_provider_at(s.base_url), api_key="k").embed(
                    a_model(), ["text"]
                )

    def test_list_models_returns_empty(self):
        """No listing endpoint. Empty means 'cannot enumerate', not 'none exist'."""
        with FakeProviderServer(mode="ok") as s:
            self.assertEqual(
                [], AnthropicProvider(anthropic_provider_at(s.base_url), api_key="k").list_models()
            )


class TestProviderRegistry(unittest.TestCase):

    def test_builds_the_right_adapter_for_each_type(self):
        cases = [
            (ProviderType.OLLAMA, OllamaProvider),
            (ProviderType.OPENAI, OpenAICompatProvider),
            (ProviderType.AZURE_OPENAI, OpenAICompatProvider),
            (ProviderType.CUSTOM, OpenAICompatProvider),
            (ProviderType.ANTHROPIC, AnthropicProvider),
        ]
        for ptype, expected in cases:
            with self.subTest(provider_type=ptype):
                built = build_provider(provider_at("http://x", provider_type=ptype), api_key="k")
                self.assertIsInstance(built, expected)

    def test_passes_the_api_key_through(self):
        built = build_provider(provider_at("http://x", provider_type=ProviderType.OPENAI), "sk-1")
        self.assertEqual("sk-1", built.api_key)

    def test_unknown_type_raises(self):
        with self.assertRaises(UnsupportedProviderType):
            build_provider(provider_at("http://x", provider_type="NOT_A_TYPE"), None)


if __name__ == "__main__":
    unittest.main()
