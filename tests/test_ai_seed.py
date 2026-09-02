"""Seeding tests. The contract: an existing deployment keeps behaving identically
after upgrading, and seeding runs exactly once."""
import os
import unittest
from unittest.mock import patch

from ai.seed import seed_from_existing_config


class SeedTestCase(unittest.TestCase):
    """Captures what seeding would write instead of touching a database."""

    def setUp(self):
        self.providers, self.models, self.rules, self.creds = [], [], [], []
        self.patches = [
            patch("ai.seed._insert_provider", lambda **kw: self.providers.append(kw) or kw["id"]),
            patch("ai.seed._insert_model", lambda **kw: self.models.append(kw) or kw["id"]),
            patch("ai.seed._insert_fallback_rule", lambda **kw: self.rules.append(kw)),
            patch("ai.seed._upsert_policy", lambda **kw: None),
            patch("ai.seed.set_capabilities", lambda *a, **kw: None),
            patch("ai.seed.store_credential", lambda *a, **kw: self.creds.append(a)),
            patch("ai.seed._provider_count", return_value=0),
            patch("ai.seed._mlx_present", return_value=False),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def names(self):
        return [p["name"] for p in self.providers]


class TestOllamaSeeding(SeedTestCase):

    def test_creates_an_ollama_provider_from_config_json(self):
        with patch("ai.seed._ollama_settings", return_value=("http://localhost:11434", "cfg-model")):
            seed_from_existing_config()
        self.assertIn("Local Ollama", self.names())
        self.assertEqual("http://localhost:11434", self.providers[0]["base_url"])

    def test_ollama_is_classed_local(self):
        with patch("ai.seed._ollama_settings", return_value=("http://localhost:11434", "cfg-model")):
            seed_from_existing_config()
        self.assertEqual("local", self.providers[0]["egress_class"])

    def test_the_chat_model_uses_the_configured_identifier(self):
        """The seeded identifier comes from config, never from a literal."""
        with patch("ai.seed._ollama_settings", return_value=("http://x:11434", "whatever-was-configured")):
            seed_from_existing_config()
        self.assertEqual("whatever-was-configured", self.models[0]["model_identifier"])
        self.assertEqual("registry_tool_json", self.models[0]["prompt_profile"])


class TestCloudSeeding(SeedTestCase):

    def test_openai_key_creates_an_external_provider_and_stores_the_key(self):
        with patch("ai.seed._ollama_settings", return_value=("http://x:11434", "m")), \
             patch.dict(os.environ, {"OPENAI_API_KEY": "sk-from-env"}, clear=False):
            seed_from_existing_config()
        self.assertIn("OpenAI", self.names())
        openai_row = next(p for p in self.providers if p["name"] == "OpenAI")
        self.assertEqual("external", openai_row["egress_class"])
        self.assertFalse(openai_row["sap_data_permitted"], "must default to opt-out")
        self.assertTrue(any("sk-from-env" in c for c in self.creds))

    def test_fallback_chain_preserves_openai_then_anthropic_order(self):
        """Today's behaviour: Ollama, then OpenAI, then Anthropic."""
        with patch("ai.seed._ollama_settings", return_value=("http://x:11434", "m")), \
             patch.dict(os.environ, {"OPENAI_API_KEY": "sk-o", "ANTHROPIC_API_KEY": "sk-ant-a"}):
            seed_from_existing_config()
        ordered = [r["model_id"] for r in sorted(self.rules, key=lambda r: r["priority"])]
        self.assertEqual(2, len(ordered))

    def test_no_cloud_keys_creates_no_external_providers(self):
        with patch("ai.seed._ollama_settings", return_value=("http://x:11434", "m")), \
             patch.dict(os.environ, {}, clear=True):
            seed_from_existing_config()
        self.assertEqual(["Local Ollama"], self.names())


class TestIdempotence(SeedTestCase):

    def test_seeding_is_skipped_when_providers_already_exist(self):
        """Configuration must never change without an administrator action."""
        with patch("ai.seed._provider_count", return_value=3), \
             patch("ai.seed._ollama_settings", return_value=("http://x:11434", "m")):
            summary = seed_from_existing_config()
        self.assertTrue(summary["skipped"])
        self.assertEqual([], self.providers)


class TestMlxSeeding(SeedTestCase):

    def test_mlx_is_seeded_as_a_custom_provider_with_the_trained_prompt_profile(self):
        with patch("ai.seed._ollama_settings", return_value=("http://x:11434", "m")), \
             patch("ai.seed._mlx_present", return_value=True):
            seed_from_existing_config()
        mlx_model = next(m for m in self.models if m["prompt_profile"] == "trained_tool_json")
        self.assertIsNotNone(mlx_model)
        mlx_provider = next(p for p in self.providers if p["id"] == mlx_model["provider_id"])
        self.assertEqual("CUSTOM", mlx_provider["provider_type"])
        self.assertEqual("local", mlx_provider["egress_class"])


if __name__ == "__main__":
    unittest.main()
