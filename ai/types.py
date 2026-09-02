"""
Value types shared across the ai package.

Everything here is frozen. Configuration is read from the database, cached, and
passed down through the router into adapters; making it immutable means a cached
object can be handed to concurrent requests without any risk that one of them
mutates the configuration another is using.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Purpose(str, Enum):
    """What a model is registered to do. A model may be registered once per purpose."""
    CHAT = "CHAT"
    REASONING = "REASONING"
    TOOL_CALLING = "TOOL_CALLING"
    EMBEDDING = "EMBEDDING"
    RERANKING = "RERANKING"
    CLASSIFICATION = "CLASSIFICATION"
    SUMMARIZATION = "SUMMARIZATION"


class Capability(str, Enum):
    """What a model can actually do. Never assumed — declared, then probed."""
    CHAT = "chat"
    STREAMING = "streaming"
    TOOL_CALLING = "tool_calling"
    VISION = "vision"
    EMBEDDING = "embedding"
    JSON_MODE = "json_mode"
    STRUCTURED_OUTPUT = "structured_output"


class ProviderType(str, Enum):
    OLLAMA = "OLLAMA"
    OPENAI = "OPENAI"
    AZURE_OPENAI = "AZURE_OPENAI"
    ANTHROPIC = "ANTHROPIC"
    CUSTOM = "CUSTOM"


class EgressClass(str, Enum):
    LOCAL = "local"
    EXTERNAL = "external"


class PromptProfile(str, Enum):
    """Which system prompt strategy a model needs.

    Fine-tuned models are trained against a fixed tool-name list and hallucinate
    when handed the generated registry JSON, so this is a property of the model,
    not of whichever backend happens to be running.
    """
    REGISTRY_TOOL_JSON = "registry_tool_json"
    TRAINED_TOOL_JSON = "trained_tool_json"


@dataclass(frozen=True)
class Message:
    role: str
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class ProviderConfig:
    id: str
    tenant_id: str
    name: str
    provider_type: ProviderType
    base_url: str
    organization_id: str | None
    deployment_name: str | None
    timeout_seconds: int
    max_retries: int
    egress_class: str
    sap_data_permitted: bool
    is_active: bool


@dataclass(frozen=True)
class ModelConfig:
    id: str
    tenant_id: str
    provider_id: str
    model_name: str
    model_identifier: str
    purpose: Purpose
    context_window: int
    max_tokens: int
    temperature: float
    prompt_profile: str
    is_active: bool


@dataclass(frozen=True)
class ResolvedModel:
    """A model, its provider, and the capabilities recorded for it."""
    model: ModelConfig
    provider: ProviderConfig
    capabilities: frozenset[Capability]

    def supports(self, capability: Capability) -> bool:
        return capability in self.capabilities

    def missing(self, required: frozenset[Capability]) -> set[Capability]:
        return set(required) - set(self.capabilities)

    @property
    def is_external(self) -> bool:
        # Fail closed: only the known-safe "local" value counts as not
        # external. An unrecognised egress_class — a typo written straight to
        # the column, a future value nothing here knows about yet — must still
        # trigger the SAP-data redaction gate rather than silently bypass it,
        # which `== EgressClass.EXTERNAL.value` would have done for anything
        # that wasn't exactly "external".
        return self.provider.egress_class != EgressClass.LOCAL.value


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(frozen=True)
class ChatResponse:
    content: str
    usage: Usage
    model_identifier: str


@dataclass(frozen=True)
class HealthResult:
    status: str          # 'healthy' | 'degraded' | 'unreachable'
    latency_ms: int
    error: str | None = None


@dataclass(frozen=True)
class RoutingRule:
    id: str
    tenant_id: str
    rule_type: str       # 'purpose' | 'intent' | 'fallback'
    match_key: str
    model_id: str
    priority: int
    is_active: bool


@dataclass(frozen=True)
class TenantPolicy:
    tenant_id: str
    allow_user_selection: bool
    fallback_enabled: bool
    default_chat_model_id: str | None
    default_embedding_model_id: str | None
    default_reranker_model_id: str | None
