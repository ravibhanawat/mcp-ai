"""
The single entry point every agent uses to reach a model.

Responsibilities, in order:
  1. resolve a model (delegated to ModelRouter),
  2. decide whether the payload may leave the estate intact,
  3. dispatch, failing over through FallbackChain,
  4. write one ai_usage_logs row per attempt.

Step 2 is the reason this class exists rather than the agents calling adapters
directly. Redaction has to be decided in one place, from the provider's
egress_class and its explicit opt-in — not by each caller remembering to pass a
flag, which is how the previous cloud-fallback path worked and how it could be
forgotten.
"""
from __future__ import annotations

import logging
import time
from typing import Any, AsyncIterator

from ai import credentials
from ai.errors import AIError
from ai.fallback import FallbackChain
from ai.providers.registry import build_provider
from ai.router import ModelRouter, Resolution
from ai.store import ConfigStore, get_store
from ai.types import Capability, ChatResponse, Message, Purpose, ResolvedModel, Usage
from ai.usage import UsageRecord, log_usage
from core.security import sanitize_sap_payload

_logger = logging.getLogger("ai.manager")


class AIProviderManager:

    def __init__(self, store: ConfigStore | None = None, router: ModelRouter | None = None) -> None:
        self.store = store or get_store()
        self.router = router or ModelRouter(self.store)
        self.chain = FallbackChain(self.store, self.router)

    # ── resolution ───────────────────────────────────────────────────────────

    def resolve_only(
        self, *, tenant_id: str, purpose: Purpose | None = None, intent: str | None = None,
        requested_model_id: str | None = None,
        required: frozenset[Capability] = frozenset(), local_only: bool = False,
    ) -> Resolution:
        """Resolve without dispatching.

        Callers need this before building a prompt, because prompt_profile
        determines which system prompt the model expects.
        """
        return self.router.resolve(
            tenant_id=tenant_id, purpose=purpose, intent=intent,
            requested_model_id=requested_model_id, required=required, local_only=local_only,
        )

    # ── egress ───────────────────────────────────────────────────────────────

    @staticmethod
    def _should_redact(resolved: ResolvedModel, carries_sap_data: bool) -> bool:
        """SAP records leave the estate only for a provider explicitly permitted."""
        return bool(
            carries_sap_data
            and resolved.is_external
            and not resolved.provider.sap_data_permitted
        )

    def _prepare(self, resolved: ResolvedModel, messages: list[dict],
                 carries_sap_data: bool) -> tuple[list[Message], bool]:
        redact = self._should_redact(resolved, carries_sap_data)
        prepared = sanitize_sap_payload(messages) if redact else messages
        return [Message(role=m["role"], content=m.get("content", "")) for m in prepared], redact

    # ── dispatch ─────────────────────────────────────────────────────────────

    def chat(
        self, *, tenant_id: str, purpose: Purpose, messages: list[dict],
        user_id: str | None = None, intent: str | None = None,
        requested_model_id: str | None = None,
        required: frozenset[Capability] = frozenset(),
        carries_sap_data: bool = False, local_only: bool = False,
        tools: list[dict[str, Any]] | None = None, request_id: str | None = None,
    ) -> ChatResponse:
        resolution = self.resolve_only(
            tenant_id=tenant_id, purpose=purpose, intent=intent,
            requested_model_id=requested_model_id, required=required, local_only=local_only,
        )
        primary = resolution.resolved
        candidates = self.chain.candidates(
            tenant_id, purpose, primary, required, local_only
        )

        # ResolvedModel is frozen, so each attempt's redaction outcome is tracked
        # here and read back when the attempts are logged.
        redaction_by_model: dict[str, bool] = {}

        def _call(model: ResolvedModel) -> ChatResponse:
            prepared, redacted = self._prepare(model, messages, carries_sap_data)
            redaction_by_model[model.model.id] = redacted
            api_key = self.credential_for(model, tenant_id)
            provider = build_provider(model.provider, api_key)
            return provider.chat(model.model, prepared, tools=tools)

        started = time.monotonic()
        attempts: list[tuple[ResolvedModel, BaseException | None]] = []
        try:
            result, used, fell_back = self.chain.execute(
                primary, candidates, _call,
                on_attempt=lambda m, e: attempts.append((m, e)),
            )
        except AIError:
            self._log_attempts(
                attempts, tenant_id, user_id, purpose, intent, request_id, primary,
                started, redaction_by_model, usage=None,
            )
            raise
        self._log_attempts(
            attempts, tenant_id, user_id, purpose, intent, request_id, primary,
            started, redaction_by_model,
            usage=result.usage, model_used=used, fell_back=fell_back,
        )
        return result

    def stream(
        self, *, tenant_id: str, purpose: Purpose, messages: list[dict],
        user_id: str | None = None, intent: str | None = None,
        requested_model_id: str | None = None, carries_sap_data: bool = False,
        local_only: bool = False, request_id: str | None = None,
    ) -> AsyncIterator[str]:
        """Async token generator. Requires the STREAMING capability.

        No fallback: a stream that switched models mid-answer would emit two
        partial answers to the user. If the primary cannot stream, the caller
        falls back to non-streaming chat.
        """
        resolution = self.resolve_only(
            tenant_id=tenant_id, purpose=purpose, intent=intent,
            requested_model_id=requested_model_id,
            required=frozenset({Capability.STREAMING}), local_only=local_only,
        )
        model = resolution.resolved
        prepared, redacted = self._prepare(model, messages, carries_sap_data)
        api_key = self.credential_for(model, tenant_id)
        log_usage(self._record(
            tenant_id, user_id, model, purpose, intent, request_id,
            latency_ms=None, redacted=redacted, status="ok",
        ))
        return build_provider(model.provider, api_key).stream(model.model, prepared)

    def embed(
        self, *, tenant_id: str, texts: list[str], user_id: str | None = None,
        local_only: bool = False, request_id: str | None = None,
    ) -> list[list[float]]:
        resolution = self.resolve_only(
            tenant_id=tenant_id, purpose=Purpose.EMBEDDING,
            required=frozenset({Capability.EMBEDDING}), local_only=local_only,
        )
        model = resolution.resolved
        api_key = self.credential_for(model, tenant_id)
        return build_provider(model.provider, api_key).embed(model.model, texts)

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def credential_for(model: ResolvedModel, tenant_id: str) -> str | None:
        """Decrypt the provider credential for this dispatch only.

        Public because callers outside dispatch — the health probe in
        SAPAgent.backend_status, for one — need the same short-lived decryption.

        Looked up through the `ai.credentials` module (rather than a
        name imported directly into this module) so that tests can patch
        `ai.credentials.read_credential` and have the patch actually take
        effect here.
        """
        try:
            return credentials.read_credential(model.provider.id, tenant_id)
        except AIError:
            raise
        except Exception as exc:
            _logger.warning("Credential lookup failed for provider %s: %s",
                            model.provider.id, exc)
            return None

    def _record(
        self, tenant_id: str, user_id: str | None, model: ResolvedModel,
        purpose: Purpose | None, intent: str | None, request_id: str | None,
        *, latency_ms: int | None, redacted: bool, status: str,
        error_code: str | None = None, usage: Usage | None = None,
        fallback_used: bool = False, fallback_from: str | None = None,
    ) -> UsageRecord:
        return UsageRecord(
            tenant_id=tenant_id, user_id=user_id,
            provider_id=model.provider.id, model_id=model.model.id,
            request_id=request_id,
            purpose=purpose.value if purpose else None, intent=intent, tool_used=None,
            authorization_result="allowed",
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            latency_ms=latency_ms, fallback_used=fallback_used,
            fallback_from_model_id=fallback_from,
            egress_class=model.provider.egress_class,
            redaction_applied=redacted,
            status=status, error_code=error_code,
        )

    def _log_attempts(
        self, attempts: list[tuple[ResolvedModel, BaseException | None]],
        tenant_id: str, user_id: str | None, purpose: Purpose | None,
        intent: str | None, request_id: str | None, primary: ResolvedModel,
        started: float, redaction_by_model: dict[str, bool], *,
        usage: Usage | None = None, model_used: ResolvedModel | None = None,
        fell_back: bool = False,
    ) -> None:
        elapsed = int((time.monotonic() - started) * 1000)
        for model, error in attempts:
            succeeded = error is None and (model_used is None or model.model.id == model_used.model.id)
            log_usage(self._record(
                tenant_id, user_id, model, purpose, intent, request_id,
                latency_ms=elapsed,
                redacted=redaction_by_model.get(model.model.id, False),
                status="ok" if succeeded else "error",
                error_code=None if error is None else type(error).__name__,
                usage=usage if succeeded else None,
                fallback_used=fell_back and model.model.id != primary.model.id,
                fallback_from=primary.model.id if model.model.id != primary.model.id else None,
            ))


_manager: AIProviderManager | None = None


def get_manager() -> AIProviderManager:
    global _manager
    if _manager is None:
        _manager = AIProviderManager()
    return _manager


def set_manager(manager: AIProviderManager | None) -> None:
    """Replace the process manager. Tests use this; production never calls it."""
    global _manager
    _manager = manager
