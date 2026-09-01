"""Row builders for store-backed tests, plus a re-export of the in-memory store."""
from ai.memory_store import InMemoryConfigStore  # noqa: F401  (re-exported)
from ai.types import ModelConfig, ProviderConfig, ProviderType, Purpose, RoutingRule


def make_provider_row(**over) -> ProviderConfig:
    base = dict(
        id="p1", tenant_id="default", name="Test Provider",
        provider_type=ProviderType.OLLAMA, base_url="http://localhost:11434",
        organization_id=None, deployment_name=None, timeout_seconds=30,
        max_retries=2, egress_class="local", sap_data_permitted=False, is_active=True,
    )
    base.update(over)
    return ProviderConfig(**base)


def make_model_row(**over) -> ModelConfig:
    base = dict(
        id="m1", tenant_id="default", provider_id="p1", model_name="Test Model",
        model_identifier="configured-identifier", purpose=Purpose.CHAT,
        context_window=8192, max_tokens=1024, temperature=0.2,
        prompt_profile="registry_tool_json", is_active=True,
    )
    base.update(over)
    return ModelConfig(**base)


def make_rule(**over) -> RoutingRule:
    base = dict(
        id="r1", tenant_id="default", rule_type="purpose", match_key="CHAT",
        model_id="m1", priority=100, is_active=True,
    )
    base.update(over)
    return RoutingRule(**base)
