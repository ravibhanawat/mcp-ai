"""Admin API tests via FastAPI's TestClient with auth dependencies overridden.
The credential-leak assertions are the ones that must never be relaxed."""
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient


def client_as(roles):
    from api import server as server_module
    from api.routes_ai_admin import router

    app = server_module.app
    app.dependency_overrides[server_module.get_current_user] = lambda: {
        "user_id": "tester", "roles": roles
    }
    if roles != ["admin"]:
        def _deny():
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Admin role required")
        app.dependency_overrides[server_module.require_admin] = _deny
    else:
        app.dependency_overrides[server_module.require_admin] = lambda: {
            "user_id": "tester", "roles": ["admin"]
        }
    return TestClient(app)


PROVIDER_ROW = {
    "id": "p1", "tenant_id": "default", "name": "Local", "provider_type": "OLLAMA",
    "base_url": "http://localhost:11434", "organization_id": None,
    "deployment_name": None, "timeout_seconds": 30, "max_retries": 2,
    "egress_class": "local", "sap_data_permitted": False, "is_active": True,
}


class TestProviderAuthorization(unittest.TestCase):

    def test_non_admin_cannot_list_providers(self):
        self.assertEqual(403, client_as(["fi_co_analyst"]).get("/admin/ai/providers").status_code)

    def test_non_admin_cannot_create_a_provider(self):
        resp = client_as(["hr_manager"]).post("/admin/ai/providers", json={"name": "x"})
        self.assertEqual(403, resp.status_code)

    def test_unauthenticated_request_is_rejected(self):
        from api import server as server_module
        server_module.app.dependency_overrides.clear()
        resp = TestClient(server_module.app).get("/admin/ai/providers")
        self.assertIn(resp.status_code, (401, 403))


class TestCredentialNeverLeaves(unittest.TestCase):

    def test_provider_response_contains_no_credential_material(self):
        with patch("api.routes_ai_admin._list_provider_rows", return_value=[PROVIDER_ROW]), \
             patch("api.routes_ai_admin.credential_display", return_value="sk-****wxyz"):
            resp = client_as(["admin"]).get("/admin/ai/providers")
        body = json.dumps(resp.json())
        self.assertEqual(200, resp.status_code)
        self.assertIn("sk-****wxyz", body)
        for forbidden in ("ciphertext", "api_key", "sk-live", "sk-proj"):
            self.assertNotIn(forbidden, body)

    def test_provider_out_model_has_no_secret_carrying_field(self):
        from api.routes_ai_admin import ProviderOut
        for name in ProviderOut.model_fields:
            self.assertNotIn(name, {"api_key", "ciphertext", "secret", "credential", "key"})

    def test_creating_a_provider_stores_the_key_encrypted_and_echoes_only_a_mask(self):
        stored = {}
        with patch("api.routes_ai_admin._insert_provider_row", return_value="p9"), \
             patch("api.routes_ai_admin.store_credential",
                   side_effect=lambda pid, tid, key: stored.update(key=key)), \
             patch("api.routes_ai_admin.credential_display", return_value="sk-****wxyz"), \
             patch("api.routes_ai_admin._get_provider_row", return_value={**PROVIDER_ROW, "id": "p9"}):
            resp = client_as(["admin"]).post("/admin/ai/providers", json={
                "name": "Cloud", "provider_type": "OPENAI",
                "base_url": "https://api.openai.com", "api_key": "sk-live-secret-wxyz",
            })
        self.assertEqual(201, resp.status_code)
        self.assertEqual("sk-live-secret-wxyz", stored["key"])
        self.assertNotIn("sk-live-secret-wxyz", json.dumps(resp.json()))

    def test_the_unchanged_sentinel_does_not_overwrite_a_stored_key(self):
        with patch("api.routes_ai_admin._update_provider_row"), \
             patch("api.routes_ai_admin.store_credential") as store, \
             patch("api.routes_ai_admin.credential_display", return_value="sk-****wxyz"), \
             patch("api.routes_ai_admin._get_provider_row", return_value=PROVIDER_ROW):
            resp = client_as(["admin"]).patch(
                "/admin/ai/providers/p1", json={"api_key": "••••••••"}
            )
        self.assertEqual(200, resp.status_code)
        store.assert_not_called()


class TestEgressClassification(unittest.TestCase):

    def test_a_localhost_ollama_provider_is_classed_local(self):
        from api.routes_ai_admin import derive_egress_class
        self.assertEqual("local", derive_egress_class("OLLAMA", "http://localhost:11434"))
        self.assertEqual("local", derive_egress_class("OLLAMA", "http://127.0.0.1:11434"))
        self.assertEqual("local", derive_egress_class("CUSTOM", "http://192.168.1.9:8080"))

    def test_a_public_endpoint_is_classed_external(self):
        self.assertEqual(
            "external",
            __import__("api.routes_ai_admin", fromlist=["x"]).derive_egress_class(
                "OPENAI", "https://api.openai.com"
            ),
        )

    def test_sap_data_permitted_defaults_to_false(self):
        from api.routes_ai_admin import ProviderIn
        self.assertFalse(ProviderIn(name="x", provider_type="OPENAI").sap_data_permitted)


MODEL_ROW = {
    "id": "m1", "tenant_id": "default", "provider_id": "p1", "model_name": "Chat",
    "model_identifier": "cfg-identifier", "purpose": "CHAT", "context_window": 8192,
    "max_tokens": 1024, "temperature": 0.2, "prompt_profile": "registry_tool_json",
    "is_active": False,
}


class TestModelActivation(unittest.TestCase):
    """`_model_to_out` reads the config store, so inject an in-memory one —
    otherwise these tests reach for PostgreSQL and fail for the wrong reason."""

    def setUp(self):
        from ai.store import set_store
        from tests.fakes.fake_store import InMemoryConfigStore, make_model_row, make_provider_row

        store = InMemoryConfigStore()
        store.add_provider(make_provider_row(id="p1", name="Local"))
        store.add_model(make_model_row(id="m1", provider_id="p1"))
        set_store(store)

    def tearDown(self):
        from ai.store import set_store
        set_store(None)

    def test_activation_is_refused_when_a_validation_check_fails(self):
        """Requirement 22: an invalid configuration must not become active."""
        from ai.validation import CheckResult
        failing = [CheckResult("provider_reachable", False, "unreachable")]
        with patch("api.routes_ai_admin._get_model_row", return_value=MODEL_ROW), \
             patch("ai.credentials.read_credential", return_value="mock-key"), \
             patch("api.routes_ai_admin.validate", return_value=failing), \
             patch("api.routes_ai_admin._set_model_active") as activate:
            resp = client_as(["admin"]).post("/admin/ai/models/m1/activate")
        self.assertEqual(400, resp.status_code)
        activate.assert_not_called()
        self.assertIn("provider_reachable", json.dumps(resp.json()))

    def test_activation_succeeds_when_every_check_passes(self):
        from ai.validation import CheckResult
        passing = [CheckResult("provider_reachable", True, "ok")]
        with patch("api.routes_ai_admin._get_model_row", return_value=MODEL_ROW), \
             patch("ai.credentials.read_credential", return_value="mock-key"), \
             patch("api.routes_ai_admin.validate", return_value=passing), \
             patch("api.routes_ai_admin.probe_capabilities", return_value=None), \
             patch("api.routes_ai_admin._set_model_active") as activate, \
             patch("api.routes_ai_admin._invalidate"):
            resp = client_as(["admin"]).post("/admin/ai/models/m1/activate")
        self.assertEqual(200, resp.status_code)
        activate.assert_called_once_with("m1", "default", True)

    def test_deactivation_needs_no_validation(self):
        with patch("api.routes_ai_admin._get_model_row", return_value=MODEL_ROW), \
             patch("api.routes_ai_admin._set_model_active") as deactivate, \
             patch("api.routes_ai_admin._invalidate"):
            resp = client_as(["admin"]).post("/admin/ai/models/m1/deactivate")
        self.assertEqual(200, resp.status_code)
        deactivate.assert_called_once_with("m1", "default", False)

    def test_validate_returns_every_check_with_its_detail(self):
        from ai.validation import CheckResult
        results = [
            CheckResult("provider_reachable", True, "responded in 12 ms"),
            CheckResult("model_exists", False, "not offered"),
        ]
        with patch("api.routes_ai_admin._get_model_row", return_value=MODEL_ROW), \
             patch("ai.credentials.read_credential", return_value="mock-key"), \
             patch("api.routes_ai_admin.validate", return_value=results):
            resp = client_as(["admin"]).post("/admin/ai/models/m1/validate")
        body = resp.json()
        self.assertFalse(body["all_passed"])
        self.assertEqual(2, len(body["checks"]))
        self.assertEqual("not offered", body["checks"][1]["detail"])

    def test_non_admin_cannot_activate_a_model(self):
        self.assertEqual(
            403, client_as(["sd_analyst"]).post("/admin/ai/models/m1/activate").status_code
        )


class TestModelCreation(unittest.TestCase):

    def setUp(self):
        from ai.store import set_store
        from tests.fakes.fake_store import InMemoryConfigStore, make_model_row, make_provider_row

        store = InMemoryConfigStore()
        store.add_provider(make_provider_row(id="p1", name="Local"))
        store.add_model(make_model_row(id="m1", provider_id="p1"))
        set_store(store)

    def tearDown(self):
        from ai.store import set_store
        set_store(None)

    def test_a_new_model_is_created_inactive(self):
        """Nothing becomes live without passing validation first."""
        captured = {}
        with patch("api.routes_ai_admin._insert_model_row",
                   side_effect=lambda v: captured.update(v) or v["id"]), \
             patch("api.routes_ai_admin.set_capabilities"), \
             patch("api.routes_ai_admin._get_model_row", return_value=MODEL_ROW), \
             patch("api.routes_ai_admin._invalidate"):
            resp = client_as(["admin"]).post("/admin/ai/models", json={
                "provider_id": "p1", "model_name": "Chat",
                "model_identifier": "whatever-admin-typed", "purpose": "CHAT",
            })
        self.assertEqual(201, resp.status_code)
        self.assertFalse(captured["is_active"])
        self.assertEqual("whatever-admin-typed", captured["model_identifier"])

    def test_an_unknown_purpose_is_rejected(self):
        resp = client_as(["admin"]).post("/admin/ai/models", json={
            "provider_id": "p1", "model_name": "x", "model_identifier": "y",
            "purpose": "NOT_A_PURPOSE",
        })
        self.assertEqual(422, resp.status_code)


class TestPolicyAndRouting(unittest.TestCase):

    def test_setting_a_default_model_writes_the_policy_row(self):
        captured = {}
        with patch("api.routes_ai_admin._upsert_policy_row",
                   side_effect=lambda v: captured.update(v)), \
             patch("api.routes_ai_admin._invalidate"), \
             patch("api.routes_ai_admin._policy_out", return_value={}):
            resp = client_as(["admin"]).put("/admin/ai/policy", json={
                "allow_user_selection": True, "fallback_enabled": True,
                "default_chat_model_id": "m1",
            })
        self.assertEqual(200, resp.status_code)
        self.assertEqual("m1", captured["default_chat_model_id"])

    def test_replacing_the_fallback_chain_preserves_the_submitted_order(self):
        written = []
        with patch("api.routes_ai_admin._delete_rules"), \
             patch("api.routes_ai_admin._insert_rule", side_effect=lambda v: written.append(v)), \
             patch("api.routes_ai_admin._invalidate"), \
             patch("api.routes_ai_admin._rules_out", return_value=[]):
            resp = client_as(["admin"]).put("/admin/ai/fallback", json={
                "chains": [{"purpose": "CHAT", "model_ids": ["m2", "m3"]}]
            })
        self.assertEqual(200, resp.status_code)
        self.assertEqual(["m2", "m3"], [w["model_id"] for w in written])
        self.assertEqual([0, 1], [w["priority"] for w in written])


class TestUserFacingModelList(unittest.TestCase):
    """Requirement 9: the list a user sees is the list an admin permitted."""

    def test_returns_nothing_when_user_selection_is_disabled(self):
        from ai.types import TenantPolicy
        policy = TenantPolicy("default", False, True, "m1", None, None)
        with patch("api.routes_ai_admin._store_for_user") as store:
            store.return_value.get_policy.return_value = policy
            resp = client_as(["fi_co_analyst"]).get("/ai/models/available")
        self.assertEqual(200, resp.status_code)
        self.assertEqual([], resp.json()["models"])
        self.assertFalse(resp.json()["selection_enabled"])

    def test_lists_only_models_marked_user_selectable(self):
        from ai.types import Capability, Purpose, TenantPolicy
        from tests.fakes.fake_store import InMemoryConfigStore, make_model_row, make_provider_row

        store = InMemoryConfigStore()
        store.add_provider(make_provider_row(id="p1"))
        for mid in ("open", "restricted"):
            store.add_model(
                make_model_row(id=mid, provider_id="p1", purpose=Purpose.CHAT),
                capabilities={Capability.CHAT},
            )
        store.set_tenant_model("default", "open", user_selectable=True)
        store.set_policy(TenantPolicy("default", True, True, "open", None, None))

        with patch("api.routes_ai_admin._store_for_user", return_value=store):
            resp = client_as(["fi_co_analyst"]).get("/ai/models/available")
        self.assertEqual(["open"], [m["id"] for m in resp.json()["models"]])

    def test_the_response_exposes_no_provider_credentials_or_urls(self):
        """A normal user has no business seeing infrastructure detail."""
        from ai.types import Capability, Purpose, TenantPolicy
        from tests.fakes.fake_store import InMemoryConfigStore, make_model_row, make_provider_row

        store = InMemoryConfigStore()
        store.add_provider(make_provider_row(id="p1", base_url="http://secret-host:11434"))
        store.add_model(make_model_row(id="open", provider_id="p1"), {Capability.CHAT})
        store.set_tenant_model("default", "open", user_selectable=True)
        store.set_policy(TenantPolicy("default", True, True, "open", None, None))

        with patch("api.routes_ai_admin._store_for_user", return_value=store):
            body = json.dumps(client_as(["read_only"]).get("/ai/models/available").json())
        self.assertNotIn("secret-host", body)
        self.assertNotIn("base_url", body)


if __name__ == "__main__":
    unittest.main()
