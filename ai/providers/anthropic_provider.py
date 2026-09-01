"""
Anthropic Messages API adapter.

Two shape differences the adapter absorbs so the router never sees them:
the system prompt is a top-level field rather than a message with role
"system", and there is no endpoint that lists available models, so
`list_models` returns [] and validation falls back to a probe request.
"""
from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator, Iterator, NoReturn

import requests

from ai.errors import (
    AuthFailed,
    CapabilityUnsupported,
    ModelTimeout,
    ProviderUnavailable,
    RateLimited,
)
from ai.provider import AIProvider
from ai.providers._stream import iterate_in_thread
from ai.types import ChatResponse, HealthResult, Message, ModelConfig, Usage

ANTHROPIC_VERSION = "2023-06-01"

#: Sent only to elicit a response. Anthropic has no cheap ping and no model
#: listing, so reachability is proven by ANY parsed reply — including the
#: 404 "unknown model" this deliberately provokes. Never a real model id.
_HEALTH_PROBE_MODEL = "__health_probe__"


class AnthropicProvider(AIProvider):

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": ANTHROPIC_VERSION,
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    def _url(self, path: str) -> str:
        return f"{self.provider.base_url.rstrip('/')}{path}"

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

    @staticmethod
    def _split_system(messages: list[Message]) -> tuple[str, list[dict[str, str]]]:
        """Anthropic takes the system prompt as a top-level field."""
        system = " ".join(m.content for m in messages if m.role == "system")
        rest = [m.as_dict() for m in messages if m.role != "system"]
        return system, rest

    def _body(self, model: ModelConfig, messages: list[Message],
              temperature: float | None, max_tokens: int | None,
              stream: bool) -> dict[str, Any]:
        system, rest = self._split_system(messages)
        body: dict[str, Any] = {
            "model": model.model_identifier,
            "messages": rest,
            "max_tokens": model.max_tokens if max_tokens is None else max_tokens,
            "temperature": model.temperature if temperature is None else temperature,
        }
        if system:
            body["system"] = system
        if stream:
            body["stream"] = True
        return body

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
                self._url("/v1/messages"), json=body, headers=self._headers(),
                timeout=self.provider.timeout_seconds,
            )
            resp.raise_for_status()
            data = resp.json()
            text = "".join(
                block.get("text", "") for block in data.get("content", [])
                if block.get("type") == "text"
            )
            usage = data.get("usage") or {}
            return ChatResponse(
                content=text,
                usage=Usage(
                    prompt_tokens=int(usage.get("input_tokens") or 0),
                    completion_tokens=int(usage.get("output_tokens") or 0),
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
                    self._url("/v1/messages"), json=body, headers=self._headers(),
                    stream=True, timeout=self.provider.timeout_seconds,
                )
                resp.raise_for_status()
                for raw in resp.iter_lines():
                    if not raw or not raw.startswith(b"data:"):
                        continue
                    payload = raw[len(b"data:"):].strip()
                    if payload == b"[DONE]":
                        return
                    event = json.loads(payload)
                    # Non-streaming fake server replies with the full body; handle both.
                    if event.get("type") == "content_block_delta":
                        token = event.get("delta", {}).get("text")
                        if token:
                            yield token
                    elif "content" in event:
                        for block in event["content"]:
                            if block.get("type") == "text" and block.get("text"):
                                yield block["text"]
            except Exception as exc:
                self._fail(exc, model.model_identifier)

        return iterate_in_thread(_tokens)

    def embed(self, model: ModelConfig, texts: list[str]) -> list[list[float]]:
        raise CapabilityUnsupported(
            "Anthropic does not provide an embeddings endpoint. Configure a "
            "separate EMBEDDING-purpose model on another provider.",
            provider_name=self.provider.name,
            model_identifier=model.model_identifier,
        )

    def health_check(self) -> HealthResult:
        """No cheap ping exists, so send a one-token message and classify by
        outcome rather than HTTP status.

        This method answers one question — "is the endpoint reachable and is
        the credential accepted?" — not "does this model exist?". A 404
        "unknown model" for `_HEALTH_PROBE_MODEL` is therefore a *successful*
        answer: it proves the request reached the server, was parsed, and was
        authenticated. Only a transport failure or a rejected credential make
        this unhealthy.
        """
        started = time.monotonic()
        try:
            resp = requests.post(
                self._url("/v1/messages"),
                json={"model": _HEALTH_PROBE_MODEL, "max_tokens": 1,
                      "messages": [{"role": "user", "content": "hi"}]},
                headers=self._headers(), timeout=self.provider.timeout_seconds,
            )
        except Exception as exc:
            return HealthResult(
                "unreachable", int((time.monotonic() - started) * 1000), str(exc)[:500]
            )
        latency_ms = int((time.monotonic() - started) * 1000)
        if resp.status_code in (401, 403):
            return HealthResult("unreachable", latency_ms, "credential rejected")
        return HealthResult("healthy", latency_ms)

    def list_models(self) -> list[str]:
        return []
