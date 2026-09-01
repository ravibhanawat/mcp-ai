"""
The interface every backend is reached through.

The agent depends on this ABC, never on Ollama, OpenAI or Anthropic. Adding a
provider means adding one file under ai/providers/ and one registry entry — no
change anywhere else in the codebase.

`generate` and `tool_call` have working defaults expressed in terms of `chat`,
because most providers implement them the same way. Overriding them is for
backends that genuinely differ.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

from ai.types import ChatResponse, HealthResult, Message, ModelConfig, ProviderConfig


class AIProvider(ABC):
    """Adapter for one configured provider row.

    Instances are cheap and short-lived: one is constructed per dispatch with the
    decrypted credential, so a key never lives longer than the request.
    """

    def __init__(self, provider: ProviderConfig, api_key: str | None = None):
        self.provider = provider
        self.api_key = api_key

    @abstractmethod
    def chat(
        self,
        model: ModelConfig,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        """Single-shot completion. Raises an ai.errors type on any failure."""

    @abstractmethod
    def stream(
        self,
        model: ModelConfig,
        messages: list[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """Async generator yielding token strings.

        The chat UI consumes this through SSE, so the shape is fixed: plain
        string tokens, no envelope, terminating by exhaustion.
        """

    @abstractmethod
    def embed(self, model: ModelConfig, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text."""

    @abstractmethod
    def health_check(self) -> HealthResult:
        """Probe reachability. Must never raise — failures are reported in the result."""

    @abstractmethod
    def list_models(self) -> list[str]:
        """Model identifiers the provider currently offers.

        Return [] when the provider has no listing endpoint; callers treat an
        empty list as "cannot enumerate", not as "no models".
        """

    def generate(
        self,
        model: ModelConfig,
        prompt: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        """Completion from a bare prompt."""
        return self.chat(
            model,
            [Message(role="user", content=prompt)],
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def tool_call(
        self,
        model: ModelConfig,
        messages: list[Message],
        tools: list[dict[str, Any]],
    ) -> ChatResponse:
        """Completion with tool definitions attached."""
        return self.chat(model, messages, tools=tools)
