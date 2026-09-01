"""Store tests. Cache and snapshot behaviour is tested through the in-memory
implementation and a stubbed clock; the Postgres implementation is exercised in
tests/test_ai_admin_api.py, which needs a database anyway."""
import json
import unittest

from ai.types import Capability, Purpose
from tests.fakes.fake_store import InMemoryConfigStore, make_model_row, make_provider_row


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


if __name__ == "__main__":
    unittest.main()
