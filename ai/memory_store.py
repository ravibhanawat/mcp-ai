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
        # Keyed by (tenant_id, id): an id is only unique within a tenant, the
        # same way it is in PostgreSQL, where two tenants' rows have distinct
        # primary keys even if an admin reuses a human-friendly id string.
        self.providers: dict[tuple[str, str], ProviderConfig] = {}
        self.models: dict[tuple[str, str], ModelConfig] = {}
        self.capabilities: dict[tuple[str, str], frozenset[Capability]] = {}
        self.rules: list[RoutingRule] = []
        self.policies: dict[str, TenantPolicy] = {}
        self.tenant_models: dict[tuple[str, str], dict] = {}

    # -- population --

    def add_provider(self, provider: ProviderConfig) -> None:
        self.providers[(provider.tenant_id, provider.id)] = provider

    def add_model(self, model: ModelConfig, capabilities: set[Capability] | None = None) -> None:
        key = (model.tenant_id, model.id)
        self.models[key] = model
        self.capabilities[key] = frozenset(capabilities or set())

    def add_rule(self, rule: RoutingRule) -> None:
        self.rules.append(rule)

    def set_policy(self, policy: TenantPolicy) -> None:
        self.policies[policy.tenant_id] = policy

    def set_tenant_model(
        self, tenant_id: str, model_id: str, *, allowed: bool = True, user_selectable: bool = False
    ) -> None:
        self.tenant_models[(tenant_id, model_id)] = {
            "allowed": allowed, "user_selectable": user_selectable
        }

    def load_snapshot(self, payload: dict) -> None:
        for row in payload.get("providers", []):
            self.add_provider(provider_from_row(row))
        for row in payload.get("models", []):
            caps = {Capability(c) for c in row.get("capabilities", [])}
            self.add_model(model_from_row(row), caps)
        for row in payload.get("routing_rules", []):
            self.add_rule(RoutingRule(
                id=row["id"], tenant_id=row["tenant_id"], rule_type=row["rule_type"],
                match_key=row["match_key"], model_id=row["model_id"],
                priority=int(row["priority"]), is_active=bool(row["is_active"]),
            ))
        policy = payload.get("policy")
        if policy:
            self.set_policy(TenantPolicy(**policy))

    # -- ConfigStore --

    def get_provider(self, provider_id: str, tenant_id: str) -> ProviderConfig | None:
        return self.providers.get((tenant_id, provider_id))

    def list_providers(self, tenant_id: str) -> list[ProviderConfig]:
        return [p for (t, _pid), p in self.providers.items() if t == tenant_id]

    def get_model(self, model_id: str, tenant_id: str) -> ModelConfig | None:
        return self.models.get((tenant_id, model_id))

    def list_models(
        self, tenant_id: str, purpose: Purpose | None = None, active_only: bool = True
    ) -> list[ModelConfig]:
        out = [m for (t, _mid), m in self.models.items() if t == tenant_id]
        if purpose is not None:
            out = [m for m in out if m.purpose == purpose]
        if active_only:
            out = [m for m in out if m.is_active]
        return out

    def get_capabilities(self, model_id: str, tenant_id: str) -> frozenset[Capability]:
        return self.capabilities.get((tenant_id, model_id), frozenset())

    def get_routing_rules(
        self, tenant_id: str, rule_type: str, match_key: str | None = None
    ) -> list[RoutingRule]:
        out = [
            r for r in self.rules
            if r.tenant_id == tenant_id and r.rule_type == rule_type and r.is_active
        ]
        if match_key is not None:
            out = [r for r in out if r.match_key == match_key]
        return sorted(out, key=lambda r: r.priority)

    def get_policy(self, tenant_id: str) -> TenantPolicy:
        return self.policies.get(tenant_id) or default_policy(tenant_id)

    def is_model_allowed(self, tenant_id: str, model_id: str) -> bool:
        row = self.tenant_models.get((tenant_id, model_id))
        if row is None:
            return self.get_model(model_id, tenant_id) is not None
        return bool(row["allowed"])

    def is_user_selectable(self, tenant_id: str, model_id: str) -> bool:
        row = self.tenant_models.get((tenant_id, model_id))
        return bool(row["user_selectable"]) if row else False
