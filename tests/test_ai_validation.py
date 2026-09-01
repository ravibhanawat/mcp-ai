"""Validation tests. Activation must be refused for anything that would fail at
request time — discovering a bad model when a user asks a question is too late."""
import unittest

from ai.types import Capability, ProviderType, Purpose
from ai.validation import all_passed, validate
from tests.fakes.fake_provider_server import FakeProviderServer
from tests.fakes.fake_store import InMemoryConfigStore, make_model_row, make_provider_row


def resolved_for(url, **model_over):
    store = InMemoryConfigStore()
    store.add_provider(make_provider_row(id="p1", base_url=url, timeout_seconds=2))
    store.add_model(
        make_model_row(id="m1", provider_id="p1", **model_over),
        capabilities={Capability.CHAT},
    )
    return store.resolved("m1", "default")


def check(results, name):
    return next(r for r in results if r.name == name)


class TestReachabilityChecks(unittest.TestCase):

    def test_all_checks_pass_for_a_healthy_model(self):
        with FakeProviderServer(mode="ok", model_name="configured-identifier") as s:
            results = validate(resolved_for(s.base_url), api_key=None)
            self.assertTrue(all_passed(results), [r for r in results if not r.passed])

    def test_unreachable_provider_fails_the_reachability_check(self):
        results = validate(resolved_for("http://127.0.0.1:1"), api_key=None)
        self.assertFalse(check(results, "provider_reachable").passed)
        self.assertFalse(all_passed(results))

    def test_invalid_credential_fails_the_authentication_check(self):
        with FakeProviderServer(mode="unauthorized") as s:
            results = validate(resolved_for(s.base_url), api_key="bad")
            self.assertFalse(check(results, "authentication_valid").passed)

    def test_model_absent_from_the_listing_fails_model_exists(self):
        with FakeProviderServer(mode="ok", model_name="a-different-model") as s:
            results = validate(resolved_for(s.base_url), api_key=None)
            self.assertFalse(check(results, "model_exists").passed)


class TestParameterChecks(unittest.TestCase):

    def test_max_tokens_above_context_window_fails(self):
        with FakeProviderServer(mode="ok", model_name="configured-identifier") as s:
            results = validate(
                resolved_for(s.base_url, context_window=1000, max_tokens=4000), api_key=None
            )
            self.assertFalse(check(results, "context_window_valid").passed)

    def test_zero_context_window_fails(self):
        with FakeProviderServer(mode="ok", model_name="configured-identifier") as s:
            results = validate(resolved_for(s.base_url, context_window=0), api_key=None)
            self.assertFalse(check(results, "context_window_valid").passed)

    def test_out_of_range_temperature_fails(self):
        with FakeProviderServer(mode="ok", model_name="configured-identifier") as s:
            results = validate(resolved_for(s.base_url, temperature=3.5), api_key=None)
            self.assertFalse(check(results, "temperature_valid").passed)

    def test_embedding_purpose_without_embedding_capability_fails(self):
        """Requirement 22: a model may not be activated for a job it cannot do."""
        with FakeProviderServer(mode="ok", model_name="configured-identifier") as s:
            store = InMemoryConfigStore()
            store.add_provider(make_provider_row(id="p1", base_url=s.base_url, timeout_seconds=2))
            store.add_model(
                make_model_row(id="m1", provider_id="p1", purpose=Purpose.EMBEDDING),
                capabilities={Capability.CHAT},          # no EMBEDDING
            )
            results = validate(store.resolved("m1", "default"), api_key=None)
            self.assertFalse(check(results, "purpose_capability_coherent").passed)


class TestResultShape(unittest.TestCase):

    def test_every_check_carries_a_human_readable_detail(self):
        results = validate(resolved_for("http://127.0.0.1:1"), api_key=None)
        for r in results:
            self.assertTrue(r.detail, r.name)

    def test_check_names_are_stable_for_the_ui(self):
        expected = {
            "provider_reachable", "model_exists", "authentication_valid",
            "context_window_valid", "temperature_valid", "purpose_capability_coherent",
        }
        results = validate(resolved_for("http://127.0.0.1:1"), api_key=None)
        self.assertTrue(expected.issubset({r.name for r in results}))


class TestAzureDeploymentCheck(unittest.TestCase):
    """OpenAICompatProvider._url() only applies Azure's
    /openai/deployments/{name} rewrite when deployment_name is set. An Azure
    provider row without one silently falls through to the plain {base}{path}
    form and fails confusingly at request time instead of at validation."""

    def test_azure_provider_without_deployment_name_fails_the_check(self):
        store = InMemoryConfigStore()
        store.add_provider(make_provider_row(
            id="p1", provider_type=ProviderType.AZURE_OPENAI,
            base_url="http://127.0.0.1:1", deployment_name=None, timeout_seconds=2,
        ))
        store.add_model(
            make_model_row(id="m1", provider_id="p1"), capabilities={Capability.CHAT}
        )
        results = validate(store.resolved("m1", "default"), api_key=None)
        self.assertFalse(check(results, "azure_deployment_configured").passed)

    def test_non_azure_provider_passes_the_check_trivially(self):
        results = validate(resolved_for("http://127.0.0.1:1"), api_key=None)
        self.assertTrue(check(results, "azure_deployment_configured").passed)


if __name__ == "__main__":
    unittest.main()
