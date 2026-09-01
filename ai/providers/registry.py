"""
Maps a configured provider_type onto its adapter class.

This is the single place that knows which types exist. Adding a provider means
adding one adapter file and one line here.
"""
from __future__ import annotations

from ai.errors import AIError
from ai.provider import AIProvider
from ai.providers.anthropic_provider import AnthropicProvider
from ai.providers.ollama import OllamaProvider
from ai.providers.openai_compat import OpenAICompatProvider
from ai.types import ProviderConfig, ProviderType


class UnsupportedProviderType(AIError):
    """The stored provider_type has no adapter in this build."""


_ADAPTERS: dict[str, type[AIProvider]] = {
    ProviderType.OLLAMA.value: OllamaProvider,
    ProviderType.OPENAI.value: OpenAICompatProvider,
    ProviderType.AZURE_OPENAI.value: OpenAICompatProvider,
    ProviderType.CUSTOM.value: OpenAICompatProvider,
    ProviderType.ANTHROPIC.value: AnthropicProvider,
}


def build_provider(provider: ProviderConfig, api_key: str | None) -> AIProvider:
    """Construct the adapter for `provider`, with the credential passed explicitly.

    The credential is an argument rather than something the adapter fetches, so a
    decrypted key exists only for the lifetime of one dispatch.
    """
    ptype = provider.provider_type
    key = ptype.value if isinstance(ptype, ProviderType) else str(ptype)
    adapter = _ADAPTERS.get(key)
    if adapter is None:
        raise UnsupportedProviderType(
            f"No adapter for provider type {key!r}. Supported: {sorted(_ADAPTERS)}.",
            provider_name=provider.name,
        )
    return adapter(provider, api_key)


def supported_provider_types() -> list[str]:
    """Used by the admin UI to populate the provider-type dropdown."""
    return sorted(_ADAPTERS)
