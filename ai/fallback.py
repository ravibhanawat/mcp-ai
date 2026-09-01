"""
Ordered failover between configured models.

Two rules define the behaviour, and both are requirements rather than
conveniences:

  * Advance only on RETRYABLE_ERRORS — the transport failures. A capability gap
    or an authorization refusal means the configuration is wrong, and quietly
    succeeding on a different model would hide that for as long as the substitute
    kept working.

  * Filter candidates before trying them, not after. A model the tenant may not
    use, or that lacks a required capability, or that would send data outside a
    local-only request, is never attempted at all. Discovering that after the
    request has already been sent would be too late.

Every attempt is surfaced through `on_attempt` so the caller can write one
ai_usage_logs row per try, which is what makes a fallback visible in the audit
trail rather than an invisible degradation.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from ai.errors import RETRYABLE_ERRORS, AIError
from ai.router import ModelRouter
from ai.store import ConfigStore
from ai.types import Capability, Purpose, ResolvedModel

_logger = logging.getLogger("ai.fallback")


class FallbackChain:

    def __init__(self, store: ConfigStore, router: ModelRouter) -> None:
        self.store = store
        self.router = router

    def candidates(
        self,
        tenant_id: str,
        purpose: Purpose,
        primary: ResolvedModel,
        required: frozenset[Capability],
        local_only: bool,
    ) -> list[ResolvedModel]:
        """Return the models that may be tried after `primary`, in order."""
        if not self.store.get_policy(tenant_id).fallback_enabled:
            return []

        out: list[ResolvedModel] = []
        for rule in self.store.get_routing_rules(tenant_id, "fallback", purpose.value):
            if rule.model_id == primary.model.id:
                continue
            resolved = self.store.resolved(rule.model_id, tenant_id)
            if resolved is None or not resolved.model.is_active:
                continue
            if not self.store.is_model_allowed(tenant_id, rule.model_id):
                _logger.info(
                    "Fallback candidate %s skipped: tenant %s is not authorized for it.",
                    rule.model_id, tenant_id,
                )
                continue
            if resolved.missing(required):
                continue
            if local_only and resolved.is_external:
                continue
            out.append(resolved)
        return out

    def execute(
        self,
        primary: ResolvedModel,
        candidates: list[ResolvedModel],
        call: Callable[[ResolvedModel], Any],
        on_attempt: Callable[[ResolvedModel, BaseException | None], None] | None = None,
    ) -> tuple[Any, ResolvedModel, bool]:
        """Call `call` against primary then each candidate until one succeeds.

        Returns (result, model_used, fallback_used). Raises the last retryable
        error when the chain is exhausted, or immediately re-raises any
        non-retryable error.
        """
        last_error: BaseException | None = None
        for index, model in enumerate([primary, *candidates]):
            try:
                result = call(model)
            except RETRYABLE_ERRORS as exc:
                last_error = exc
                if on_attempt:
                    on_attempt(model, exc)
                _logger.warning(
                    "Model %s failed (%s); %d candidate(s) remaining.",
                    model.model.model_name, type(exc).__name__, len(candidates) - index,
                )
                continue
            except AIError as exc:
                # Report the exception, not None: the caller derives success from
                # `error is None`, so passing None here would write a failed
                # request to the usage log as status="ok".
                if on_attempt:
                    on_attempt(model, exc)
                raise                      # configuration error: surface it
            else:
                if on_attempt:
                    on_attempt(model, None)
                return result, model, index > 0

        assert last_error is not None      # loop always runs at least once
        raise last_error
