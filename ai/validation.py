"""
The gate a model must pass before it can be activated.

Requirement 22 in one function. Every check returns a named result rather than
raising, so the admin UI can render the whole list at once and the administrator
sees every problem in one pass instead of fixing them one error at a time.
"""
from __future__ import annotations

from dataclasses import dataclass

from ai.provider import AIProvider
from ai.providers.registry import build_provider
from ai.types import Capability, ProviderType, Purpose, ResolvedModel

#: Purposes that cannot be fulfilled without a specific capability.
_PURPOSE_REQUIREMENTS: dict[Purpose, Capability] = {
    Purpose.EMBEDDING: Capability.EMBEDDING,
    Purpose.RERANKING: Capability.EMBEDDING,
    Purpose.TOOL_CALLING: Capability.TOOL_CALLING,
}


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str


def validate(resolved: ResolvedModel, api_key: str | None) -> list[CheckResult]:
    """Run every pre-activation check. Never raises.

    Building the adapter is itself wrapped: an unsupported provider_type or any
    other construction failure must surface as failed checks, not as an
    exception escaping this function — the same "never raises" guarantee that
    applies to every check below.
    """
    results: list[CheckResult] = []
    model = resolved.model

    provider: AIProvider | None = None
    build_error: Exception | None = None
    try:
        provider = build_provider(resolved.provider, api_key)
    except Exception as exc:  # noqa: BLE001 — deliberately broad, see docstring
        build_error = exc

    if provider is None:
        detail = f"Could not construct the provider adapter: {build_error}"
        results.append(CheckResult("provider_reachable", False, detail))
        results.append(CheckResult(
            "authentication_valid", False,
            "Cannot check: provider adapter could not be built.",
        ))
        results.append(CheckResult(
            "model_exists", False,
            "Cannot check: provider adapter could not be built.",
        ))
        reachable = False
    else:
        health = provider.health_check()
        reachable = health.status == "healthy"
        results.append(CheckResult(
            "provider_reachable", reachable,
            f"{resolved.provider.name} responded in {health.latency_ms} ms"
            if reachable else f"{resolved.provider.name} unreachable: {health.error}",
        ))

        results.append(CheckResult(
            "authentication_valid", reachable,
            "Credential accepted." if reachable
            else "Provider rejected the request. Check the API key.",
        ))

        listed = provider.list_models() if reachable else []
        if not reachable:
            exists, detail = False, "Cannot check: provider unreachable."
        elif not listed:
            exists, detail = True, "Provider cannot list models; identifier accepted unverified."
        else:
            exists = model.model_identifier in listed
            detail = (
                f"{model.model_identifier!r} is offered by the provider." if exists
                else f"{model.model_identifier!r} is not in the provider's model list."
            )
        results.append(CheckResult("model_exists", exists, detail))

    window_ok = model.context_window > 0 and model.context_window >= model.max_tokens
    results.append(CheckResult(
        "context_window_valid", window_ok,
        f"context_window={model.context_window}, max_tokens={model.max_tokens}"
        if window_ok else
        f"context_window ({model.context_window}) must be positive and at least "
        f"max_tokens ({model.max_tokens}).",
    ))

    temp_ok = 0.0 <= model.temperature <= 2.0
    results.append(CheckResult(
        "temperature_valid", temp_ok,
        f"temperature={model.temperature}" if temp_ok
        else f"temperature must be between 0.0 and 2.0, got {model.temperature}.",
    ))

    needed = _PURPOSE_REQUIREMENTS.get(model.purpose)
    coherent = needed is None or resolved.supports(needed)
    results.append(CheckResult(
        "purpose_capability_coherent", coherent,
        f"Purpose {model.purpose.value} is satisfied." if coherent
        else f"Purpose {model.purpose.value} requires the {needed.value} capability, "
             "which this model is not marked as supporting.",
    ))

    # OpenAICompatProvider._url() only applies Azure's /openai/deployments/{name}
    # rewrite when deployment_name is set. An Azure provider row without one
    # silently falls through to the plain {base}{path} form — no /openai
    # prefix, no api-version — and fails confusingly at request time instead
    # of here.
    is_azure = resolved.provider.provider_type == ProviderType.AZURE_OPENAI
    if not is_azure:
        azure_ok, azure_detail = True, "Not an Azure OpenAI provider; this check does not apply."
    else:
        deployment_name = resolved.provider.deployment_name
        azure_ok = bool(deployment_name) and bool(deployment_name.strip())
        azure_detail = (
            f"deployment_name={deployment_name!r}" if azure_ok
            else "Azure OpenAI providers must set deployment_name, or requests silently fall "
                 "back to a URL with no /openai prefix and no api-version."
        )
    results.append(CheckResult("azure_deployment_configured", azure_ok, azure_detail))

    return results


def all_passed(results: list[CheckResult]) -> bool:
    return all(r.passed for r in results)
