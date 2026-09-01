"""
The error taxonomy the fallback chain makes decisions from.

Every adapter maps its vendor exceptions onto these types, which is what lets
`ai.fallback` treat an Ollama connection refusal and an Anthropic 529 the same
way without importing either SDK.

The split that matters is RETRYABLE_ERRORS versus everything else. A transport
failure means "this backend is not answering, try the next one". A capability
gap or a missing configuration means the administrator has set something up
wrong and must be shown the error — silently succeeding on a different model
would hide the misconfiguration indefinitely.
"""
from __future__ import annotations


class AIError(Exception):
    """Base class for every error raised by the ai package."""

    def __init__(
        self,
        message: str,
        *,
        provider_name: str | None = None,
        model_identifier: str | None = None,
    ):
        super().__init__(message)
        self.provider_name = provider_name
        self.model_identifier = model_identifier

    @property
    def code(self) -> str:
        """Stable identifier written to ai_usage_logs.error_code."""
        return type(self).__name__


class ProviderUnavailable(AIError):
    """The provider endpoint could not be reached at all."""


class AuthFailed(AIError):
    """The provider rejected the credential (401/403)."""


class RateLimited(AIError):
    """The provider refused the request for quota reasons (429)."""


class ModelTimeout(AIError):
    """The provider accepted the request but did not answer in time."""


class CapabilityUnsupported(AIError):
    """The resolved model cannot do what the caller requires. Configuration error."""


class NoModelConfigured(AIError):
    """No active model satisfies the requested purpose for this tenant."""


class ModelNotAuthorized(AIError):
    """The tenant or user may not use the requested model."""


class CredentialUnavailable(AIError):
    """The provider needs an API key that cannot be decrypted or is not stored."""


#: Errors that make the fallback chain advance to the next candidate.
#: Deliberately excludes CapabilityUnsupported, NoModelConfigured,
#: ModelNotAuthorized and CredentialUnavailable — all administrator errors.
RETRYABLE_ERRORS: tuple[type[AIError], ...] = (
    ProviderUnavailable,
    AuthFailed,
    RateLimited,
    ModelTimeout,
)
