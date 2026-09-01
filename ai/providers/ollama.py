"""
Ollama adapter — native /api/chat, /api/embeddings and /api/tags.

Ollama is spoken to over plain HTTP rather than through its OpenAI-compatible
shim because the native endpoint is what the codebase already used, exposes
`options` (temperature, num_predict) directly, and reports token counts the
usage log wants.
"""
from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator, Iterator, NoReturn

import requests

from ai.errors import AuthFailed, ModelTimeout, ProviderUnavailable, RateLimited
from ai.provider import AIProvider
from ai.providers._stream import iterate_in_thread
from ai.types import ChatResponse, HealthResult, Message, ModelConfig, Usage


class OllamaProvider(AIProvider):

    # ── error mapping ────────────────────────────────────────────────────────

    def _fail(self, exc: Exception, model_identifier: str | None = None) -> NoReturn:
        """Translate a transport failure into the shared taxonomy and raise."""
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
            raise ProviderUnavailable(
                f"{self.provider.name} returned HTTP {status}.", **ctx
            ) from exc
        raise ProviderUnavailable(
            f"{self.provider.name} returned an unusable response.", **ctx
        ) from exc

    def _url(self, path: str) -> str:
        return f"{self.provider.base_url.rstrip('/')}{path}"

    def _payload(self, model: ModelConfig, messages: list[Message],
                 temperature: float | None, max_tokens: int | None,
                 stream: bool) -> dict[str, Any]:
        return {
            "model": model.model_identifier,
            "messages": [m.as_dict() for m in messages],
            "stream": stream,
            "options": {
                "temperature": model.temperature if temperature is None else temperature,
                "num_predict": model.max_tokens if max_tokens is None else max_tokens,
            },
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
        payload = self._payload(model, messages, temperature, max_tokens, stream=False)
        if tools:
            payload["tools"] = tools
        try:
            resp = requests.post(
                self._url("/api/chat"), json=payload, timeout=self.provider.timeout_seconds
            )
            resp.raise_for_status()
            data = resp.json()
            return ChatResponse(
                content=data["message"]["content"],
                usage=Usage(
                    prompt_tokens=int(data.get("prompt_eval_count") or 0),
                    completion_tokens=int(data.get("eval_count") or 0),
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
        payload = self._payload(model, messages, temperature, max_tokens, stream=True)

        def _tokens() -> Iterator[str]:
            try:
                resp = requests.post(
                    self._url("/api/chat"), json=payload, stream=True,
                    timeout=self.provider.timeout_seconds,
                )
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    token = chunk.get("message", {}).get("content", "")
                    if token:
                        yield token
                    if chunk.get("done"):
                        return
            except Exception as exc:
                self._fail(exc, model.model_identifier)

        return iterate_in_thread(_tokens)

    def embed(self, model: ModelConfig, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        try:
            for text in texts:
                resp = requests.post(
                    self._url("/api/embeddings"),
                    json={"model": model.model_identifier, "prompt": text},
                    timeout=self.provider.timeout_seconds,
                )
                resp.raise_for_status()
                vectors.append(resp.json()["embedding"])
            return vectors
        except Exception as exc:
            self._fail(exc, model.model_identifier)

    def health_check(self) -> HealthResult:
        started = time.monotonic()
        try:
            resp = requests.get(self._url("/api/tags"), timeout=self.provider.timeout_seconds)
            resp.raise_for_status()
            resp.json()
            return HealthResult("healthy", int((time.monotonic() - started) * 1000))
        except Exception as exc:
            return HealthResult(
                "unreachable", int((time.monotonic() - started) * 1000), str(exc)[:500]
            )

    def list_models(self) -> list[str]:
        try:
            resp = requests.get(self._url("/api/tags"), timeout=self.provider.timeout_seconds)
            resp.raise_for_status()
            return [m["name"] for m in resp.json().get("models", [])]
        except Exception:
            return []
