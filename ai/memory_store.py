"""
An in-memory ConfigStore.

Two production uses and one test use:
  * cold start, when PostgreSQL is unreachable and the config.json snapshot is
    all the configuration that exists;
  * seeding, before the first write;
  * and every router/fallback/manager test, which is why the logic that picks a
    model is testable without a database.
"""
from __future__ import annotations

from ai.store import ConfigStore, default_policy, model_from_row, provider_from_row
from ai.types import (
    Capability,
    ModelConfig,
    ProviderConfig,
    Purpose,
    RoutingRule,
    TenantPolicy,
)


class InMemoryConfigStore(ConfigStore):

    def __init__(self):
        self.providers: dict[str, ProviderConfig] = {}
        self.models: dict[str, ModelConfig] = {}
        self.capabilities: dict[str, frozenset[Capability]] = {}
        self.rules: list[RoutingRule] = []
        self.policies: dict[str, TenantPolicy] = {}
        self.tenant_models: dict[tuple[str, str], dict] = {}

    # -- population --

    def add_provider(self, provider: ProviderConfig) -> None:
        self.providers[provider.id] = provider

    def add_model(self, model: ModelConfig, capabilities: set[Capability] | None = None) -> None:
        self.models[model.id] = model
        self.capabilities[model.id] = frozenset(capabilities or set())

    def add_rule(self, rule: RoutingRule) -> None:
        self.rules.append(rule)

    def set_policy(self, policy: TenantPolicy) -> None:
        self.policies[policy.tenant_id] = policy

    def set_tenant_model(self, tenant_id: str, model_id: str, *, allowed=True, user_selectable=False):
        self.tenant_models[(tenant_id, model_id)] = {
            "allowed": allowed, "user_selectable": user_selectable
        }

    def load_snapshot(self, payload: dict) -> None:
        for row in payload.get("providers", []):
            self.add_provider(provider_from_row(row))
        for row in payload.get("models", []):
            caps = {Capability(c) for c in row.get("capabilities", [])}
            self.add_model(model_from_row(row), caps)
        policy = payload.get("policy")
        if policy:
            self.set_policy(TenantPolicy(**policy))

    # -- ConfigStore --

    def get_provider(self, provider_id, tenant_id):
        p = self.providers.get(provider_id)
        return p if p and p.tenant_id == tenant_id else None

    def list_providers(self, tenant_id):
        return [p for p in self.providers.values() if p.tenant_id == tenant_id]

    def get_model(self, model_id, tenant_id):
        m = self.models.get(model_id)
        return m if m and m.tenant_id == tenant_id else None

    def list_models(self, tenant_id, purpose=None, active_only=True):
        out = [m for m in self.models.values() if m.tenant_id == tenant_id]
        if purpose is not None:
            out = [m for m in out if m.purpose == purpose]
        if active_only:
            out = [m for m in out if m.is_active]
        return out

    def get_capabilities(self, model_id):
        return self.capabilities.get(model_id, frozenset())

    def get_routing_rules(self, tenant_id, rule_type, match_key=None):
        out = [
            r for r in self.rules
            if r.tenant_id == tenant_id and r.rule_type == rule_type and r.is_active
        ]
        if match_key is not None:
            out = [r for r in out if r.match_key == match_key]
        return sorted(out, key=lambda r: r.priority)

    def get_policy(self, tenant_id):
        return self.policies.get(tenant_id) or default_policy(tenant_id)

    def is_model_allowed(self, tenant_id, model_id):
        row = self.tenant_models.get((tenant_id, model_id))
        if row is None:
            return self.get_model(model_id, tenant_id) is not None
        return bool(row["allowed"])

    def is_user_selectable(self, tenant_id, model_id):
        row = self.tenant_models.get((tenant_id, model_id))
        return bool(row["user_selectable"]) if row else False
