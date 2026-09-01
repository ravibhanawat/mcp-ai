"""
Adapter for every OpenAI-compatible endpoint: OpenAI, Azure OpenAI, and any
self-hosted server that speaks /v1/chat/completions — vLLM, LM Studio, llama.cpp,
the MLX server this project used to special-case.

Written against the HTTP surface rather than the openai SDK for one reason that
matters more than the convenience the SDK offers: the SDK resolves credentials
from the environment when none is passed, and a partially-configured provider
row would then silently authenticate with a stray OPENAI_API_KEY and send
SAP-adjacent prompts somewhere nobody configured. Here the credential can only
come from the decrypted database row.
"""
from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator, Iterator, NoReturn

import requests

from ai.errors import AuthFailed, ModelTimeout, ProviderUnavailable, RateLimited
from ai.provider import AIProvider
from ai.providers._stream import iterate_in_thread
from ai.types import ChatResponse, HealthResult, Message, ModelConfig, ProviderType, Usage

#: Azure requires an explicit API version on every request. ProviderConfig has
#: no field for it yet, so this is the default until an ai_providers.api_version
#: column exists; see the hand-off notes.
AZURE_API_VERSION = "2024-02-01"


class OpenAICompatProvider(AIProvider):

    #: Paths Azure namespaces under a deployment (inference calls). Its model
    #: listing is account-scoped, not deployment-scoped, so /v1/models must
    #: not be rewritten the same way or a configured Azure provider would
    #: 404 on health_check()/list_models() and could never pass validation.
    _AZURE_DEPLOYMENT_PATHS = ("/v1/chat/completions", "/v1/embeddings")

    # ── request construction ─────────────────────────────────────────────────

    @property
    def _is_azure(self) -> bool:
        return self.provider.provider_type == ProviderType.AZURE_OPENAI

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            if self._is_azure:
                headers["api-key"] = self.api_key
            else:
                headers["Authorization"] = f"Bearer {self.api_key}"
        if self.provider.organization_id:
            headers["OpenAI-Organization"] = self.provider.organization_id
        return headers

    def _url(self, path: str) -> str:
        base = self.provider.base_url.rstrip("/")
        if not (self._is_azure and self.provider.deployment_name):
            return f"{base}{path}"
        # Azure does not use the /v1 prefix on any of its paths.
        suffix = path[len("/v1"):] if path.startswith("/v1") else path
        if path in self._AZURE_DEPLOYMENT_PATHS:
            # Inference calls are namespaced by deployment:
            #   {base}/openai/deployments/{deployment}/chat/completions
            return (
                f"{base}/openai/deployments/{self.provider.deployment_name}"
                f"{suffix}?api-version={AZURE_API_VERSION}"
            )
        # Control-plane paths (model listing) are account-scoped, not
        # deployment-scoped: {base}/openai/models
        return f"{base}/openai{suffix}?api-version={AZURE_API_VERSION}"

    def _fail(self, exc: Exception, model_identifier: str | None = None) -> NoReturn:
        ctx = {"provider_name": self.provider.name, "model_identifier": model_identifier}
        if isinstance(exc, requests.exceptions.Timeout):
            raise ModelTimeout(f"{self.provider.name} did not respond in time.", **ctx) from exc
        if isinstance(exc, requests.exceptions.ConnectionError):
            raise ProviderUnavailable(
                f"Cannot reach {self.provider.name} at {self.provider.base_url}.", **ctx
            ) from exc
        if isinstance(exc, requests.exceptions.HTTPError):
            status = exc.response.status_code if exc.response is not None else 0
            if status in (401, 403):
                raise AuthFailed(f"{self.provider.name} rejected the credential.", **ctx) from exc
            if status == 429:
                raise RateLimited(f"{self.provider.name} rate limit exceeded.", **ctx) from exc
            raise ProviderUnavailable(f"{self.provider.name} returned HTTP {status}.", **ctx) from exc
        raise ProviderUnavailable(
            f"{self.provider.name} returned an unusable response.", **ctx
        ) from exc

    def _body(self, model: ModelConfig, messages: list[Message],
              temperature: float | None, max_tokens: int | None,
              stream: bool) -> dict[str, Any]:
        return {
            "model": model.model_identifier,
            "messages": [m.as_dict() for m in messages],
            "temperature": model.temperature if temperature is None else temperature,
            "max_tokens": model.max_tokens if max_tokens is None else max_tokens,
            "stream": stream,
        }

    # ── AIProvider ───────────────────────────────────────────────────────────

    def chat(
        self,
        model: ModelConfig,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        body = self._body(model, messages, temperature, max_tokens, stream=False)
        if tools:
            body["tools"] = tools
        try:
            resp = requests.post(
                self._url("/v1/chat/completions"), json=body, headers=self._headers(),
                timeout=self.provider.timeout_seconds,
            )
            resp.raise_for_status()
            data = resp.json()
            usage = data.get("usage") or {}
            return ChatResponse(
                content=data["choices"][0]["message"]["content"] or "",
                usage=Usage(
                    prompt_tokens=int(usage.get("prompt_tokens") or 0),
                    completion_tokens=int(usage.get("completion_tokens") or 0),
                ),
                model_identifier=model.model_identifier,
            )
        except Exception as exc:
            self._fail(exc, model.model_identifier)

    def stream(
        self,
        model: ModelConfig,
        messages: list[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        body = self._body(model, messages, temperature, max_tokens, stream=True)

        def _tokens() -> Iterator[str]:
            try:
                resp = requests.post(
                    self._url("/v1/chat/completions"), json=body, headers=self._headers(),
                    stream=True, timeout=self.provider.timeout_seconds,
                )
                resp.raise_for_status()
                for raw in resp.iter_lines():
                    if not raw or not raw.startswith(b"data:"):
                        continue
                    payload = raw[len(b"data:"):].strip()
                    if payload == b"[DONE]":
                        return
                    delta = json.loads(payload)["choices"][0].get("delta", {})
                    token = delta.get("content")
                    if token:
                        yield token
            except Exception as exc:
                self._fail(exc, model.model_identifier)

        return iterate_in_thread(_tokens)

    def embed(self, model: ModelConfig, texts: list[str]) -> list[list[float]]:
        try:
            resp = requests.post(
                self._url("/v1/embeddings"),
                json={"model": model.model_identifier, "input": texts},
                headers=self._headers(), timeout=self.provider.timeout_seconds,
            )
            resp.raise_for_status()
            return [row["embedding"] for row in resp.json()["data"]]
        except Exception as exc:
            self._fail(exc, model.model_identifier)

    def health_check(self) -> HealthResult:
        started = time.monotonic()
        try:
            resp = requests.get(
                self._url("/v1/models"), headers=self._headers(),
                timeout=self.provider.timeout_seconds,
            )
            resp.raise_for_status()
            resp.json()
            return HealthResult("healthy", int((time.monotonic() - started) * 1000))
        except Exception as exc:
            return HealthResult(
                "unreachable", int((time.monotonic() - started) * 1000), str(exc)[:500]
            )

    def list_models(self) -> list[str]:
        try:
            resp = requests.get(
                self._url("/v1/models"), headers=self._headers(),
                timeout=self.provider.timeout_seconds,
            )
            resp.raise_for_status()
            return [m["id"] for m in resp.json().get("data", [])]
        except Exception:
            return []
