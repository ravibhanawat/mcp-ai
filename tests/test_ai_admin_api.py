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


if __name__ == "__main__":
    unittest.main()
