"""Seeding tests. The contract: an existing deployment keeps behaving identically
after upgrading, and seeding runs exactly once."""
import contextlib
import os
import unittest
from unittest.mock import patch

from ai.seed import seed_from_existing_config


class SeedTestCase(unittest.TestCase):
    """Captures what seeding would write instead of touching a database.

    `_connect` — the one place seed_from_existing_config opens a real
    connection — is patched to a no-op context manager so these tests never
    reach for PostgreSQL; every write function below accepts and ignores the
    `conn=None` that flows from that.
    """

    def setUp(self):
        self.providers, self.models, self.rules, self.creds = [], [], [], []
        self.patches = [
            patch("ai.seed._connect", lambda: contextlib.nullcontext(None)),
            patch("ai.seed._insert_provider",
                  lambda conn=None, **kw: self.providers.append(kw) or kw["id"]),
            patch("ai.seed._insert_model",
                  lambda conn=None, **kw: self.models.append(kw) or kw["id"]),
            patch("ai.seed._insert_fallback_rule",
                  lambda conn=None, **kw: self.rules.append(kw)),
            patch("ai.seed._upsert_policy", lambda conn=None, **kw: None),
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

    def provider_name_for_model(self, model_id: str) -> str:
        """Look up the provider name for a given model ID."""
        model = next((m for m in self.models if m["id"] == model_id), None)
        if not model:
            return None
        provider = next((p for p in self.providers if p["id"] == model["provider_id"]), None)
        return provider["name"] if provider else None


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
        """Today's behaviour: Ollama, then OpenAI, then Anthropic.

        This test verifies that the first request after upgrade gets the same
        answer from the same model. The order matters: if swapped, failover
        behaviour silently changes on upgrade.
        """
        with patch("ai.seed._ollama_settings", return_value=("http://x:11434", "m")), \
             patch.dict(os.environ, {"OPENAI_API_KEY": "sk-o", "ANTHROPIC_API_KEY": "sk-ant-a"}):
            seed_from_existing_config()

        # Verify exactly two fallback rules were created
        self.assertEqual(2, len(self.rules))

        # Sort by priority and verify ascending order [0, 1]
        sorted_rules = sorted(self.rules, key=lambda r: r["priority"])
        priorities = [r["priority"] for r in sorted_rules]
        self.assertEqual([0, 1], priorities)

        # Verify priority 0 points to OpenAI model and priority 1 to Anthropic
        openai_model_id = sorted_rules[0]["model_id"]
        anthropic_model_id = sorted_rules[1]["model_id"]

        self.assertEqual("OpenAI", self.provider_name_for_model(openai_model_id))
        self.assertEqual("Anthropic", self.provider_name_for_model(anthropic_model_id))

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


class TestTransactionalSeeding(unittest.TestCase):
    """Critical 3, part 2: seeding must run as one connection / one commit,
    not one auto-committed statement per insert — otherwise a failure partway
    through leaves a partial seed that `_provider_count` then treats as
    "already configured", permanently skipping every future seed attempt."""

    def setUp(self):
        self.sentinel_conn = object()
        self.seen_conns = []
        self.connect_calls = 0

        def _fake_connect():
            self.connect_calls += 1
            return contextlib.nullcontext(self.sentinel_conn)

        def _record_conn(conn=None, **kw):
            self.seen_conns.append(conn)
            return kw.get("id", "unused")

        self.patches = [
            patch("ai.seed._connect", _fake_connect),
            patch("ai.seed._insert_provider", _record_conn),
            patch("ai.seed._insert_model", _record_conn),
            patch("ai.seed._insert_fallback_rule", lambda conn=None, **kw: self.seen_conns.append(conn)),
            patch("ai.seed._upsert_policy", lambda conn=None, **kw: self.seen_conns.append(conn)),
            patch("ai.seed.set_capabilities", lambda *a, conn=None, **kw: self.seen_conns.append(conn)),
            patch("ai.seed.store_credential", lambda *a, conn=None, **kw: self.seen_conns.append(conn)),
            patch("ai.seed._provider_count", lambda tenant_id, conn=None: self.seen_conns.append(conn) or 0),
            patch("ai.seed._mlx_present", return_value=False),
            patch("ai.seed._ollama_settings", return_value=("http://x:11434", "m")),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_the_whole_seed_opens_exactly_one_connection(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-o", "ANTHROPIC_API_KEY": "sk-ant-a"}):
            seed_from_existing_config()
        self.assertEqual(1, self.connect_calls)

    def test_every_write_shares_the_same_connection(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-o", "ANTHROPIC_API_KEY": "sk-ant-a"}):
            seed_from_existing_config()
        self.assertTrue(self.seen_conns, "no write ran at all")
        self.assertTrue(
            all(c is self.sentinel_conn for c in self.seen_conns),
            f"a write used a different connection than _connect() provided: {self.seen_conns}",
        )

    def test_a_failure_partway_through_propagates_rather_than_being_absorbed(self):
        """seed_from_existing_config must not catch a mid-sequence failure and
        return a fabricated partial-success summary — the whole point of
        sharing one connection is that the caller's transaction (get_db() in
        production) rolls everything back when this raises. If this function
        swallowed the error instead, the transaction would commit whatever
        happened to run before the failure, and _provider_count would then
        see a non-empty ai_providers on the next boot and skip seeding
        forever — a permanently half-configured deployment."""
        def _boom(conn=None, **kw):
            raise RuntimeError("simulated mid-seed failure")

        with patch("ai.seed._insert_model", _boom), \
             patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                seed_from_existing_config()


class TestLifespanSurvivesASeedFailure(unittest.TestCase):
    """Critical 3, part 1. run_ai_migrations() already swallows every
    exception itself (a WARNING, not a raise) — but before this fix, the
    lifespan block around it and seed_from_existing_config() caught only
    asyncio.TimeoutError. A real seeding failure (UndefinedTable, because the
    migration never actually created ai_providers) is a plain Exception, not
    a TimeoutError, so it escaped lifespan entirely and the application would
    not start. This reproduces exactly that: seed_from_existing_config raises
    a non-timeout error, and lifespan must absorb it and let startup proceed."""

    def test_a_non_timeout_seed_failure_does_not_escape_lifespan(self):
        import asyncio
        from unittest.mock import AsyncMock

        from api.server import app, lifespan

        def _boom():
            raise RuntimeError('relation "ai_providers" does not exist')

        async def _run():
            with patch("api.server._run_migrations", lambda: None), \
                 patch("ai.schema.run_ai_migrations", lambda: None), \
                 patch("ai.seed.seed_from_existing_config", _boom), \
                 patch("db.connection.open_async_pool", new_callable=AsyncMock), \
                 patch("db.connection.close_async_pool", new_callable=AsyncMock):
                # If the fix regresses, RuntimeError propagates out of this
                # `async with` and the test fails with that exception instead
                # of completing normally.
                async with lifespan(app):
                    pass

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
