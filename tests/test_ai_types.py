"""Tests for ai.types and ai.errors — the vocabulary the rest of ai/ shares."""
import unittest

from ai.errors import (
    RETRYABLE_ERRORS,
    AIError,
    AuthFailed,
    CapabilityUnsupported,
    ModelTimeout,
    NoModelConfigured,
    ProviderUnavailable,
    RateLimited,
)
from ai.types import (
    Capability,
    ModelConfig,
    ProviderConfig,
    ProviderType,
    Purpose,
    ResolvedModel,
)


def make_provider(**over):
    base = dict(
        id="p1", tenant_id="default", name="Local", provider_type=ProviderType.OLLAMA,
        base_url="http://localhost:11434", organization_id=None, deployment_name=None,
        timeout_seconds=30, max_retries=2, egress_class="local",
        sap_data_permitted=False, is_active=True,
    )
    base.update(over)
    return ProviderConfig(**base)


def make_model(**over):
    base = dict(
        id="m1", tenant_id="default", provider_id="p1", model_name="Local Chat",
        model_identifier="any-configured-model", purpose=Purpose.CHAT,
        context_window=8192, max_tokens=1024, temperature=0.2,
        prompt_profile="registry_tool_json", is_active=True,
    )
    base.update(over)
    return ModelConfig(**base)


class TestResolvedModel(unittest.TestCase):

    def test_supports_returns_true_for_declared_capability(self):
        r = ResolvedModel(
            model=make_model(), provider=make_provider(),
            capabilities=frozenset({Capability.CHAT, Capability.STREAMING}),
        )
        self.assertTrue(r.supports(Capability.STREAMING))

    def test_supports_returns_false_for_absent_capability(self):
        r = ResolvedModel(
            model=make_model(), provider=make_provider(),
            capabilities=frozenset({Capability.CHAT}),
        )
        self.assertFalse(r.supports(Capability.TOOL_CALLING))

    def test_missing_returns_the_unsatisfied_capabilities(self):
        r = ResolvedModel(
            model=make_model(), provider=make_provider(),
            capabilities=frozenset({Capability.CHAT}),
        )
        self.assertEqual(
            {Capability.TOOL_CALLING},
            r.missing(frozenset({Capability.CHAT, Capability.TOOL_CALLING})),
        )

    def test_is_external_reflects_provider_egress_class(self):
        local = ResolvedModel(make_model(), make_provider(), frozenset())
        cloud = ResolvedModel(make_model(), make_provider(egress_class="external"), frozenset())
        self.assertFalse(local.is_external)
        self.assertTrue(cloud.is_external)

    def test_is_external_fails_closed_on_an_unrecognised_egress_class(self):
        """Important I1: is_external must not silently treat a typo or an
        unknown value as safe. Only the exact string 'local' counts as
        not-external, so anything else — including a value nothing in the
        codebase would ever intentionally write — still triggers the
        SAP-data redaction gate."""
        typo = ResolvedModel(make_model(), make_provider(egress_class="External"), frozenset())
        unknown = ResolvedModel(make_model(), make_provider(egress_class="somewhere-else"), frozenset())
        self.assertTrue(typo.is_external)
        self.assertTrue(unknown.is_external)

    def test_configs_are_immutable(self):
        with self.assertRaises(Exception):
            make_model().temperature = 1.5


class TestErrorTaxonomy(unittest.TestCase):

    def test_all_errors_share_a_base(self):
        for err in (ProviderUnavailable, AuthFailed, RateLimited, ModelTimeout,
                    CapabilityUnsupported, NoModelConfigured):
            self.assertTrue(issubclass(err, AIError), err.__name__)

    def test_retryable_set_is_exactly_the_transport_failures(self):
        """Fallback fires on these and nothing else. Guards the core policy."""
        self.assertEqual(
            {ProviderUnavailable, AuthFailed, RateLimited, ModelTimeout},
            set(RETRYABLE_ERRORS),
        )

    def test_capability_unsupported_is_not_retryable(self):
        """A capability gap is a configuration error the admin must see (spec 6.1)."""
        self.assertNotIn(CapabilityUnsupported, RETRYABLE_ERRORS)

    def test_no_model_configured_is_not_retryable(self):
        self.assertNotIn(NoModelConfigured, RETRYABLE_ERRORS)

    def test_errors_carry_provider_and_model_context(self):
        err = ProviderUnavailable("down", provider_name="Local", model_identifier="x")
        self.assertEqual("Local", err.provider_name)
        self.assertEqual("x", err.model_identifier)


if __name__ == "__main__":
    unittest.main()
