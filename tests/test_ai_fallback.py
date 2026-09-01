"""Fallback tests. The policy being protected: advance on transport failures,
never on configuration errors, and never onto a model the tenant may not use."""
import unittest

from ai.errors import (
    AuthFailed,
    CapabilityUnsupported,
    ModelNotAuthorized,
    ProviderUnavailable,
    RateLimited,
)
from ai.fallback import FallbackChain
from ai.router import ModelRouter
from ai.types import Capability, Purpose, TenantPolicy
from tests.fakes.fake_store import (
    InMemoryConfigStore,
    make_model_row,
    make_provider_row,
    make_rule,
)


class FallbackTestCase(unittest.TestCase):

    def setUp(self):
        self.store = InMemoryConfigStore()
        for pid, egress in (("local", "local"), ("cloud-a", "external"), ("cloud-b", "external")):
            self.store.add_provider(make_provider_row(id=pid, name=pid, egress_class=egress))
        for mid, pid in (("primary", "local"), ("second", "cloud-a"), ("third", "cloud-b")):
            self.store.add_model(
                make_model_row(id=mid, provider_id=pid, purpose=Purpose.CHAT),
                capabilities={Capability.CHAT},
            )
        self.store.set_policy(TenantPolicy(
            tenant_id="default", allow_user_selection=False, fallback_enabled=True,
            default_chat_model_id="primary", default_embedding_model_id=None,
            default_reranker_model_id=None,
        ))
        for i, mid in enumerate(("second", "third")):
            self.store.add_rule(make_rule(
                id=f"fb{i}", rule_type="fallback", match_key="CHAT", model_id=mid, priority=i
            ))
        self.router = ModelRouter(self.store)
        self.chain = FallbackChain(self.store, self.router)
        self.primary = self.store.resolved("primary", "default")


class TestCandidateSelection(FallbackTestCase):

    def test_returns_chain_members_in_priority_order(self):
        ids = [c.model.id for c in self.chain.candidates(
            "default", Purpose.CHAT, self.primary, frozenset(), False
        )]
        self.assertEqual(["second", "third"], ids)

    def test_excludes_the_primary_from_its_own_chain(self):
        self.store.add_rule(make_rule(
            id="fb-self", rule_type="fallback", match_key="CHAT", model_id="primary", priority=99
        ))
        ids = [c.model.id for c in self.chain.candidates(
            "default", Purpose.CHAT, self.primary, frozenset(), False
        )]
        self.assertNotIn("primary", ids)

    def test_excludes_models_the_tenant_may_not_use(self):
        """Requirement 13: never fail over to an unauthorized model."""
        self.store.set_tenant_model("default", "second", allowed=False)
        ids = [c.model.id for c in self.chain.candidates(
            "default", Purpose.CHAT, self.primary, frozenset(), False
        )]
        self.assertEqual(["third"], ids)

    def test_excludes_models_lacking_a_required_capability(self):
        ids = [c.model.id for c in self.chain.candidates(
            "default", Purpose.CHAT, self.primary,
            frozenset({Capability.TOOL_CALLING}), False,
        )]
        self.assertEqual([], ids)

    def test_excludes_external_models_when_local_only(self):
        ids = [c.model.id for c in self.chain.candidates(
            "default", Purpose.CHAT, self.primary, frozenset(), True
        )]
        self.assertEqual([], ids)

    def test_returns_nothing_when_fallback_is_disabled(self):
        self.store.set_policy(TenantPolicy(
            tenant_id="default", allow_user_selection=False, fallback_enabled=False,
            default_chat_model_id="primary", default_embedding_model_id=None,
            default_reranker_model_id=None,
        ))
        self.assertEqual([], self.chain.candidates(
            "default", Purpose.CHAT, self.primary, frozenset(), False
        ))

    def test_excludes_inactive_models(self):
        # add_model overwrites by (tenant_id, id); never write store.models directly.
        self.store.add_model(
            make_model_row(
                id="second", provider_id="cloud-a", purpose=Purpose.CHAT, is_active=False
            ),
            capabilities={Capability.CHAT},
        )
        ids = [c.model.id for c in self.chain.candidates(
            "default", Purpose.CHAT, self.primary, frozenset(), False
        )]
        self.assertEqual(["third"], ids)


class TestExecution(FallbackTestCase):

    def _candidates(self):
        return self.chain.candidates("default", Purpose.CHAT, self.primary, frozenset(), False)

    def test_primary_success_uses_no_fallback(self):
        result, used, fell_back = self.chain.execute(
            self.primary, self._candidates(), lambda m: f"ok:{m.model.id}"
        )
        self.assertEqual("ok:primary", result)
        self.assertEqual("primary", used.model.id)
        self.assertFalse(fell_back)

    def test_advances_past_a_transport_failure(self):
        def call(m):
            if m.model.id == "primary":
                raise ProviderUnavailable("down")
            return f"ok:{m.model.id}"

        result, used, fell_back = self.chain.execute(self.primary, self._candidates(), call)
        self.assertEqual("ok:second", result)
        self.assertEqual("second", used.model.id)
        self.assertTrue(fell_back)

    def test_advances_through_multiple_failures(self):
        def call(m):
            if m.model.id in ("primary", "second"):
                raise RateLimited("429")
            return "ok:third"

        result, used, _ = self.chain.execute(self.primary, self._candidates(), call)
        self.assertEqual("third", used.model.id)

    def test_auth_failure_is_retryable(self):
        def call(m):
            if m.model.id == "primary":
                raise AuthFailed("401")
            return "ok"

        _, used, _ = self.chain.execute(self.primary, self._candidates(), call)
        self.assertEqual("second", used.model.id)

    def test_capability_error_is_not_retried(self):
        """A configuration error must surface, not be papered over."""
        attempts = []

        def call(m):
            attempts.append(m.model.id)
            raise CapabilityUnsupported("no tools")

        with self.assertRaises(CapabilityUnsupported):
            self.chain.execute(self.primary, self._candidates(), call)
        self.assertEqual(["primary"], attempts)

    def test_authorization_error_is_not_retried(self):
        def call(m):
            raise ModelNotAuthorized("denied")

        with self.assertRaises(ModelNotAuthorized):
            self.chain.execute(self.primary, self._candidates(), call)

    def test_exhausting_the_chain_raises_the_last_transport_error(self):
        def call(m):
            raise ProviderUnavailable(f"{m.model.id} down")

        with self.assertRaises(ProviderUnavailable) as ctx:
            self.chain.execute(self.primary, self._candidates(), call)
        self.assertIn("third", str(ctx.exception))

    def test_on_attempt_receives_the_error_for_a_non_retryable_failure(self):
        """The usage log derives success from `error is None`; a config error
        reported as None would be recorded as a successful request."""
        seen = []

        def call(m):
            raise CapabilityUnsupported("no tools")

        with self.assertRaises(CapabilityUnsupported):
            self.chain.execute(
                self.primary, self._candidates(), call,
                on_attempt=lambda model, error: seen.append(error),
            )
        self.assertEqual(1, len(seen))
        self.assertIsInstance(seen[0], CapabilityUnsupported)

    def test_on_attempt_is_called_for_every_try(self):
        seen = []

        def call(m):
            if m.model.id != "third":
                raise ProviderUnavailable("down")
            return "ok"

        self.chain.execute(
            self.primary, self._candidates(), call,
            on_attempt=lambda model, error: seen.append((model.model.id, type(error).__name__ if error else None)),
        )
        self.assertEqual(
            [("primary", "ProviderUnavailable"), ("second", "ProviderUnavailable"), ("third", None)],
            seen,
        )


if __name__ == "__main__":
    unittest.main()
