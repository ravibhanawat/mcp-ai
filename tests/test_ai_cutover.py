"""Cutover tests. Two guarantees: no hardcoded model survives, and the prompt a
model receives is decided by its configured prompt_profile."""
import re
import unittest
from unittest.mock import MagicMock, patch

from ai.manager import AIProviderManager
from ai.router import ModelRouter
from ai.types import Capability, Purpose, TenantPolicy
from tests.fakes.fake_store import InMemoryConfigStore, make_model_row, make_provider_row


def manager_with(prompt_profile="registry_tool_json", identifier="cfg-model"):
    store = InMemoryConfigStore()
    store.add_provider(make_provider_row(id="p1", base_url="http://127.0.0.1:1"))
    store.add_model(
        make_model_row(id="m1", provider_id="p1", purpose=Purpose.CHAT,
                       prompt_profile=prompt_profile, model_identifier=identifier),
        capabilities={Capability.CHAT, Capability.STREAMING},
    )
    store.set_policy(TenantPolicy(
        tenant_id="default", allow_user_selection=False, fallback_enabled=False,
        default_chat_model_id="m1", default_embedding_model_id=None,
        default_reranker_model_id=None,
    ))
    return AIProviderManager(store=store, router=ModelRouter(store))


class TestNoHardcodedModels(unittest.TestCase):
    """The core requirement, asserted against the source itself.

    Scoped to the file THIS task cuts over. agent/autonomous_agent.py and
    agent/report_agent.py still carry their own literals until Task 19, and
    api/server.py's ChatRequest.model until Task 22 — so widening this list
    now would assert an end-state the branch has not reached yet. Task 19
    extends SOURCES; Task 27's final grep covers the whole tree.
    """

    SOURCES = [
        "agent/sap_agent.py",
    ]
    # Literals that must not appear as operational defaults after cutover.
    FORBIDDEN = [
        r"llama3\.2", r"gemma\d?:", r"gpt-4o", r"claude-[a-z]+-\d",
        r"localhost:11434", r"localhost:8080",
    ]

    def test_no_model_identifier_or_backend_url_remains(self):
        for path in self.SOURCES:
            with open(path, encoding="utf-8") as f:
                source = f.read()
            for pattern in self.FORBIDDEN:
                with self.subTest(path=path, pattern=pattern):
                    hits = [
                        line for line in source.splitlines()
                        if re.search(pattern, line) and not line.strip().startswith("#")
                    ]
                    self.assertEqual([], hits, f"{path}: {hits}")


class TestPromptProfile(unittest.TestCase):

    def test_registry_profile_lists_tools_from_the_registry(self):
        from agent.sap_agent import SAPAgent
        agent = SAPAgent(manager=manager_with("registry_tool_json"))
        prompt = agent.system_prompt_for("registry_tool_json")
        self.assertIn("MODE 1", prompt)

    def test_trained_profile_uses_the_fixed_tool_name_list(self):
        from agent.sap_agent import SAPAgent
        agent = SAPAgent(manager=manager_with("trained_tool_json"))
        prompt = agent.system_prompt_for("trained_tool_json")
        self.assertIn("get_vendor_info", prompt)
        self.assertNotIn("MODE 1", prompt)

    def test_the_profile_comes_from_configuration_not_from_a_probe(self):
        """Nothing may probe :8080 to decide which prompt to send."""
        from agent import sap_agent
        with open(sap_agent.__file__, encoding="utf-8") as f:
            source = f.read()
        self.assertNotIn("_mlx_available", source)
        self.assertNotIn("_use_mlx", source)


class TestBackendStatusNeverRaises(unittest.TestCase):
    """Verify that backend_status() never raises, even when credentials cannot be decrypted."""

    def test_backend_status_handles_credential_decryption_failure(self):
        """backend_status() must not raise when credential_for() raises CredentialUnavailable.

        This is a critical contract for the /health endpoint — if key rotation breaks
        credential decryption, the health check itself must not fail. It should instead
        return configured=False with the error detail.
        """
        from agent.sap_agent import SAPAgent
        from ai.errors import CredentialUnavailable

        agent = SAPAgent(manager=manager_with())

        # Patch credential_for to raise CredentialUnavailable (e.g., due to key rotation)
        with patch.object(agent.manager, 'credential_for', side_effect=CredentialUnavailable("Key rotated, cannot decrypt stored credential")):
            # Should not raise; should return error dict
            result = agent.backend_status()

        self.assertIsInstance(result, dict)
        self.assertEqual(result["configured"], False)
        self.assertEqual(result["connected"], False)
        self.assertIn("Key rotated", result["detail"])


if __name__ == "__main__":
    unittest.main()
