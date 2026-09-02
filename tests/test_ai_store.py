"""Store tests. Cache and snapshot behaviour is tested through the in-memory
implementation and a stubbed clock; the Postgres implementation is exercised in
tests/test_ai_admin_api.py, which needs a database anyway."""
import json
import unittest
from unittest.mock import patch

from ai.types import Capability, Purpose
from tests.fakes.fake_store import (
    InMemoryConfigStore,
    make_model_row,
    make_provider_row,
    make_rule,
)


class TestInMemoryStoreContract(unittest.TestCase):

    def setUp(self):
        self.store = InMemoryConfigStore()
        self.store.add_provider(make_provider_row(id="p1", name="Local"))
        self.store.add_model(
            make_model_row(id="m1", provider_id="p1", purpose=Purpose.CHAT),
            capabilities={Capability.CHAT, Capability.STREAMING},
        )

    def test_get_model_returns_the_model(self):
        self.assertEqual("m1", self.store.get_model("m1", "default").id)

    def test_get_model_from_another_tenant_returns_none(self):
        self.assertIsNone(self.store.get_model("m1", "other-tenant"))

    def test_list_models_filters_by_purpose(self):
        self.store.add_model(make_model_row(id="m2", provider_id="p1", purpose=Purpose.EMBEDDING))
        chat = self.store.list_models("default", purpose=Purpose.CHAT)
        self.assertEqual(["m1"], [m.id for m in chat])

    def test_list_models_excludes_inactive_by_default(self):
        self.store.add_model(
            make_model_row(id="m3", provider_id="p1", purpose=Purpose.CHAT, is_active=False)
        )
        self.assertEqual(["m1"], [m.id for m in self.store.list_models("default", Purpose.CHAT)])

    def test_resolved_joins_model_provider_and_capabilities(self):
        resolved = self.store.resolved("m1", "default")
        self.assertEqual("m1", resolved.model.id)
        self.assertEqual("Local", resolved.provider.name)
        self.assertTrue(resolved.supports(Capability.STREAMING))
        self.assertFalse(resolved.supports(Capability.TOOL_CALLING))

    def test_resolved_across_tenants_returns_none(self):
        self.assertIsNone(self.store.resolved("m1", "other-tenant"))

    def test_policy_defaults_are_safe_when_no_row_exists(self):
        """No policy row must mean: users cannot pick models, fallback is on."""
        policy = self.store.get_policy("never-configured")
        self.assertFalse(policy.allow_user_selection)
        self.assertTrue(policy.fallback_enabled)
        self.assertIsNone(policy.default_chat_model_id)

    def test_is_model_allowed_defaults_true_for_same_tenant(self):
        self.assertTrue(self.store.is_model_allowed("default", "m1"))

    def test_is_user_selectable_defaults_false(self):
        """Users must not be able to select a model nobody marked selectable."""
        self.assertFalse(self.store.is_user_selectable("default", "m1"))

    def test_get_capabilities_from_another_tenant_returns_empty(self):
        """Capabilities carry no secrets, but the tenant filter has no exceptions."""
        self.assertEqual(frozenset(), self.store.get_capabilities("m1", "other-tenant"))

    def test_same_id_across_tenants_does_not_collide(self):
        """A provider or model id is only unique within a tenant, not globally."""
        store = InMemoryConfigStore()
        store.add_provider(make_provider_row(id="p1", tenant_id="tenant-a", name="Provider A"))
        store.add_provider(make_provider_row(id="p1", tenant_id="tenant-b", name="Provider B"))
        store.add_model(
            make_model_row(id="m1", tenant_id="tenant-a", provider_id="p1", model_name="Model A")
        )
        store.add_model(
            make_model_row(id="m1", tenant_id="tenant-b", provider_id="p1", model_name="Model B")
        )

        self.assertEqual("Provider A", store.get_provider("p1", "tenant-a").name)
        self.assertEqual("Provider B", store.get_provider("p1", "tenant-b").name)
        self.assertEqual("Model A", store.get_model("m1", "tenant-a").model_name)
        self.assertEqual("Model B", store.get_model("m1", "tenant-b").model_name)


class TestSnapshot(unittest.TestCase):

    def test_snapshot_roundtrips_without_credentials(self):
        from ai.store import snapshot_payload, snapshot_to_store

        store = InMemoryConfigStore()
        store.add_provider(make_provider_row(id="p1", name="Local"))
        store.add_model(make_model_row(id="m1", provider_id="p1"), capabilities={Capability.CHAT})

        payload = snapshot_payload(store, "default")
        text = json.dumps(payload)
        for forbidden in ("ciphertext", "api_key", "sk-"):
            self.assertNotIn(forbidden, text)

        restored = snapshot_to_store(payload)
        self.assertEqual("m1", restored.get_model("m1", "default").id)
        self.assertEqual("Local", restored.get_provider("p1", "default").name)

    def test_snapshot_roundtrips_routing_rules_and_fallback_chains(self):
        """A system running from the snapshot must reproduce the same routing
        and failover decisions the live database would have made — losing
        these rows would silently drop every purpose/intent rule and fallback
        chain during an outage."""
        from ai.store import snapshot_payload, snapshot_to_store

        store = InMemoryConfigStore()
        store.add_provider(make_provider_row(id="p1", name="Local"))
        store.add_model(
            make_model_row(id="m1", provider_id="p1", purpose=Purpose.CHAT),
            capabilities={Capability.CHAT},
        )
        store.add_model(
            make_model_row(id="m2", provider_id="p1", purpose=Purpose.CHAT),
            capabilities={Capability.CHAT},
        )
        store.add_rule(make_rule(
            id="r1", rule_type="purpose", match_key="CHAT", model_id="m1", priority=0,
        ))
        store.add_rule(make_rule(
            id="r2", rule_type="intent", match_key="complex_reasoning", model_id="m1", priority=0,
        ))
        store.add_rule(make_rule(
            id="r3", rule_type="fallback", match_key="CHAT", model_id="m2", priority=0,
        ))

        payload = snapshot_payload(store, "default")
        self.assertEqual(3, len(payload["routing_rules"]))

        restored = snapshot_to_store(payload)
        self.assertEqual(
            ["m1"],
            [r.model_id for r in restored.get_routing_rules("default", "purpose", "CHAT")],
        )
        self.assertEqual(
            ["m1"],
            [r.model_id for r in restored.get_routing_rules("default", "intent", "complex_reasoning")],
        )
        self.assertEqual(
            ["m2"],
            [r.model_id for r in restored.get_routing_rules("default", "fallback", "CHAT")],
        )


class TestGetStoreFallback(unittest.TestCase):
    """The promise in ai/store.py's own module docstring: if PostgreSQL is
    unreachable at boot, get_store() falls back to the read-only config.json
    snapshot so conversational traffic still resolves a model, instead of
    every caller getting a PostgresConfigStore that blows up on first use.

    Before this fix, get_store() unconditionally returned PostgresConfigStore()
    with no probe and no fallback — this class fails without the fix in
    ai.store.get_store() (verified: reverting it reproduces a store that raises
    on first real read rather than one backed by the snapshot)."""

    def setUp(self):
        import ai.store as store_module
        self._store_module = store_module
        self._saved_store = store_module._store
        store_module._store = None

    def tearDown(self):
        self._store_module._store = self._saved_store

    def test_falls_back_to_the_snapshot_when_postgres_is_unreachable(self):
        import ai.store as store_module

        snapshot = {
            "tenant_id": "default",
            "providers": [{
                "id": "p1", "tenant_id": "default", "name": "Snapshot Provider",
                "provider_type": "OLLAMA", "base_url": "http://localhost:11434",
                "organization_id": None, "deployment_name": None,
                "timeout_seconds": 30, "max_retries": 2, "egress_class": "local",
                "sap_data_permitted": False, "is_active": True,
            }],
            "models": [], "routing_rules": [],
            "policy": {
                "tenant_id": "default", "allow_user_selection": False,
                "fallback_enabled": True, "default_chat_model_id": None,
                "default_embedding_model_id": None, "default_reranker_model_id": None,
            },
        }

        with patch.object(
            store_module.PostgresConfigStore, "list_providers",
            side_effect=RuntimeError("connection refused"),
        ), patch.object(store_module, "load_snapshot", return_value=snapshot):
            result = store_module.get_store()

        # Must actually be serving the snapshot's content, not merely some
        # store instance that happened not to raise on this one call.
        self.assertEqual("Snapshot Provider", result.get_provider("p1", "default").name)
        self.assertNotIsInstance(result, store_module.PostgresConfigStore)

    def test_fallback_is_cached_not_retried_per_request(self):
        import ai.store as store_module

        calls = {"n": 0}

        def _boom(*a, **kw):
            calls["n"] += 1
            raise RuntimeError("connection refused")

        with patch.object(store_module.PostgresConfigStore, "list_providers", side_effect=_boom), \
             patch.object(store_module, "load_snapshot", return_value={}):
            first = store_module.get_store()
            second = store_module.get_store()

        self.assertIs(first, second)
        self.assertEqual(1, calls["n"], "the probe read must run once, not per get_store() call")

    def test_postgres_is_used_when_reachable(self):
        import ai.store as store_module
        with patch.object(store_module.PostgresConfigStore, "list_providers", return_value=[]):
            result = store_module.get_store()
        self.assertIsInstance(result, store_module.PostgresConfigStore)


if __name__ == "__main__":
    unittest.main()
