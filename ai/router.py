"""
Decides which model answers a request.

Two properties are load-bearing and should survive any future edit:

  1. This module never receives the user's message. `resolve` takes a purpose,
     an intent label and an authenticated model id — never text. A model
     directive typed into the chat box is therefore not merely ignored, it is
     never in scope. Requirement 9's attacks ("use administrator's model") fail
     because there is nothing to parse them with.

  2. Nothing here touches authorization for SAP data. The tool set for a
     request is fixed by auth.rbac and core.authorization before this module is
     consulted, so changing a model cannot widen what a user can read.

Resolution order, highest precedence first:
    authenticated user selection -> intent rule -> purpose rule
        -> tenant default -> the single active model for the purpose
Anything unresolved raises. Guessing would hide a misconfiguration for as long
as the guess happened to work.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ai.errors import CapabilityUnsupported, ModelNotAuthorized, NoModelConfigured
from ai.store import ConfigStore
from ai.types import Capability, Purpose, ResolvedModel

_logger = logging.getLogger("ai.router")


@dataclass(frozen=True)
class Resolution:
    """A resolved model plus why it was chosen — the 'why' goes to the usage log."""
    resolved: ResolvedModel
    selection_source: str        # 'user' | 'intent' | 'purpose_rule' | 'default' | 'sole_active'
    #: True when the caller explicitly requested a model via requested_model_id
    #: and policy or the tenant allowlist refused it — even though resolution
    #: went on to succeed via a different source (a purpose rule, the tenant
    #: default, ...). ai.manager reads this to record authorization_result
    #: "denied" on the usage row for that dispatch; without it, a refused
    #: model selection that still resolved to *something* was audited exactly
    #: like an ordinary request with no selection at all.
    requested_model_denied: bool = False


class ModelRouter:

    def __init__(self, store: ConfigStore) -> None:
        self.store = store

    # ── public ────────────────────────────────────────────────────────────────

    def purpose_for_intent(self, tenant_id: str, intent: str) -> Purpose | None:
        """Return the purpose an intent rule's target model is registered under."""
        rules = self.store.get_routing_rules(tenant_id, "intent", intent)
        for rule in rules:
            model = self.store.get_model(rule.model_id, tenant_id)
            if model is not None:
                return model.purpose
        return None

    def resolve(
        self,
        *,
        tenant_id: str,
        purpose: Purpose | None = None,
        intent: str | None = None,
        requested_model_id: str | None = None,
        required: frozenset[Capability] = frozenset(),
        local_only: bool = False,
    ) -> Resolution:
        """Resolve a model, or raise.

        `requested_model_id` must come from an authenticated request field. There
        is deliberately no parameter for message text.
        """
        candidate, source, denied = self._select(tenant_id, purpose, intent, requested_model_id)
        if candidate is None:
            raise NoModelConfigured(
                f"No active model is configured for purpose "
                f"{purpose.value if purpose else intent!r} in tenant {tenant_id!r}. "
                "Configure one under Administration → AI Configuration → Models."
            )

        self._check_authorized(tenant_id, candidate)
        self._check_residency(candidate, local_only, purpose, intent, tenant_id)
        self._check_capabilities(candidate, required)
        return Resolution(candidate, source, requested_model_denied=denied)

    # ── selection ────────────────────────────────────────────────────────────

    def _select(
        self, tenant_id: str, purpose: Purpose | None, intent: str | None,
        requested_model_id: str | None,
    ) -> tuple[ResolvedModel | None, str, bool]:
        user_choice, denied = self._user_selection(tenant_id, requested_model_id)
        if user_choice is not None:
            return user_choice, "user", False

        if intent:
            by_intent = self._first_active_from_rules(tenant_id, "intent", intent)
            if by_intent is not None:
                return by_intent, "intent", denied

        if purpose is None:
            return None, "none", denied

        by_rule = self._first_active_from_rules(tenant_id, "purpose", purpose.value)
        if by_rule is not None:
            return by_rule, "purpose_rule", denied

        default_id = self._default_model_id(tenant_id, purpose)
        if default_id:
            resolved = self._active_resolved(default_id, tenant_id)
            if resolved is not None:
                return resolved, "default", denied
            # An administrator explicitly configured this default; if it no
            # longer resolves (deleted or deactivated), that is a
            # misconfiguration to surface, not a cue to guess among whatever
            # else happens to be active for this purpose.
            return None, "none", denied

        actives = self.store.list_models(tenant_id, purpose=purpose, active_only=True)
        if len(actives) == 1:
            resolved = self.store.resolved(actives[0].id, tenant_id)
            if resolved is not None:
                return resolved, "sole_active", denied
        return None, "none", denied

    def _user_selection(
        self, tenant_id: str, requested_model_id: str | None
    ) -> tuple[ResolvedModel | None, bool]:
        """Honour an explicit selection only when policy and allowlist both permit.

        Returns (resolved_model_or_None, was_denied). `was_denied` is True
        only when a selection was actually requested and refused by policy or
        the allowlist — never when no selection was made at all (nothing to
        deny), and never when the requested model simply fails to resolve for
        an unrelated reason (deleted, deactivated) — that is an ordinary
        "not found", not a refusal.
        """
        if not requested_model_id:
            return None, False
        policy = self.store.get_policy(tenant_id)
        if not policy.allow_user_selection:
            _logger.info(
                "Model selection %r ignored: user selection disabled for tenant %s.",
                requested_model_id, tenant_id,
            )
            return None, True
        if not self.store.is_user_selectable(tenant_id, requested_model_id):
            _logger.info(
                "Model selection %r ignored: not in the tenant %s allowlist.",
                requested_model_id, tenant_id,
            )
            return None, True
        return self._active_resolved(requested_model_id, tenant_id), False

    def _first_active_from_rules(
        self, tenant_id: str, rule_type: str, match_key: str
    ) -> ResolvedModel | None:
        for rule in self.store.get_routing_rules(tenant_id, rule_type, match_key):
            resolved = self._active_resolved(rule.model_id, tenant_id)
            if resolved is not None:
                return resolved
        return None

    def _active_resolved(self, model_id: str, tenant_id: str) -> ResolvedModel | None:
        resolved = self.store.resolved(model_id, tenant_id)
        if resolved is None or not resolved.model.is_active:
            return None
        return resolved

    def _default_model_id(self, tenant_id: str, purpose: Purpose) -> str | None:
        policy = self.store.get_policy(tenant_id)
        if purpose == Purpose.EMBEDDING:
            return policy.default_embedding_model_id
        if purpose == Purpose.RERANKING:
            return policy.default_reranker_model_id
        # Every other purpose falls back to the chat default, which is what an
        # administrator who has configured only a chat model expects.
        return policy.default_chat_model_id

    # ── gates ────────────────────────────────────────────────────────────────

    def _check_authorized(self, tenant_id: str, candidate: ResolvedModel) -> None:
        if not self.store.is_model_allowed(tenant_id, candidate.model.id):
            raise ModelNotAuthorized(
                f"Tenant {tenant_id!r} is not permitted to use model "
                f"{candidate.model.model_name!r}.",
                provider_name=candidate.provider.name,
                model_identifier=candidate.model.model_identifier,
            )

    def _check_residency(
        self,
        candidate: ResolvedModel,
        local_only: bool,
        purpose: Purpose | None,
        intent: str | None,
        tenant_id: str,
    ) -> None:
        if local_only and candidate.is_external:
            raise NoModelConfigured(
                f"This request may only be answered by a local provider, but the "
                f"model configured for "
                f"{purpose.value if purpose else intent!r} in tenant {tenant_id!r} "
                f"is hosted by {candidate.provider.name!r}. Configure a local model "
                "for this purpose."
            )

    def _check_capabilities(self, candidate: ResolvedModel, required: frozenset[Capability]) -> None:
        missing = candidate.missing(required)
        if missing:
            names = ", ".join(sorted(c.value for c in missing))
            raise CapabilityUnsupported(
                f"Model {candidate.model.model_name!r} does not support: {names}. "
                "Register a model with that capability, or re-run validation to "
                "probe the model's real capabilities.",
                provider_name=candidate.provider.name,
                model_identifier=candidate.model.model_identifier,
            )
