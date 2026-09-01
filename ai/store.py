"""
Reads AI configuration.

`ConfigStore` is an interface rather than a set of module functions for one
practical reason: the router, the fallback chain and the manager all consume
configuration, and every one of their tests would otherwise need a live
PostgreSQL. With the interface in place they take an in-memory store and the
logic that actually decides which model answers a user is testable in
milliseconds.

Caching: a 30-second process cache keeps the chat hot path off the database.
Admin writes invalidate it in the writing worker; other workers converge within
the TTL. That staleness is acceptable because nothing the cache serves is a
security boundary — RBAC, operation authorization and the confirmation gate are
all evaluated outside this module.

Snapshot: after every successful admin write the active configuration is mirrored
into the `ai` block of config.json, credentials excluded. If PostgreSQL is
unreachable at boot the snapshot is loaded read-only so conversational traffic
still resolves a model instead of the whole product failing on a database blip.
"""
from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod

from ai.types import (
    Capability,
    ModelConfig,
    ProviderConfig,
    ProviderType,
    Purpose,
    ResolvedModel,
    RoutingRule,
    TenantPolicy,
)

_logger = logging.getLogger("ai.store")

CACHE_TTL_SECONDS = 30
DEFAULT_TENANT = "default"


class ConfigStore(ABC):
    """Read access to AI configuration for one or more tenants."""

    @abstractmethod
    def get_provider(self, provider_id: str, tenant_id: str) -> ProviderConfig | None: ...

    @abstractmethod
    def list_providers(self, tenant_id: str) -> list[ProviderConfig]: ...

    @abstractmethod
    def get_model(self, model_id: str, tenant_id: str) -> ModelConfig | None: ...

    @abstractmethod
    def list_models(
        self, tenant_id: str, purpose: Purpose | None = None, active_only: bool = True
    ) -> list[ModelConfig]: ...

    @abstractmethod
    def get_capabilities(self, model_id: str) -> frozenset[Capability]: ...

    @abstractmethod
    def get_routing_rules(
        self, tenant_id: str, rule_type: str, match_key: str | None = None
    ) -> list[RoutingRule]: ...

    @abstractmethod
    def get_policy(self, tenant_id: str) -> TenantPolicy: ...

    @abstractmethod
    def is_model_allowed(self, tenant_id: str, model_id: str) -> bool: ...

    @abstractmethod
    def is_user_selectable(self, tenant_id: str, model_id: str) -> bool: ...

    def resolved(self, model_id: str, tenant_id: str) -> ResolvedModel | None:
        """Join a model with its provider and capabilities. Shared by all stores."""
        model = self.get_model(model_id, tenant_id)
        if model is None:
            return None
        provider = self.get_provider(model.provider_id, tenant_id)
        if provider is None:
            return None
        return ResolvedModel(model, provider, self.get_capabilities(model_id))


def default_policy(tenant_id: str) -> TenantPolicy:
    """The policy used when no row exists.

    Chosen to fail closed on the one control that matters: users cannot select
    models unless an administrator has said they may.
    """
    return TenantPolicy(
        tenant_id=tenant_id,
        allow_user_selection=False,
        fallback_enabled=True,
        default_chat_model_id=None,
        default_embedding_model_id=None,
        default_reranker_model_id=None,
    )


# ── Row mapping ───────────────────────────────────────────────────────────────

def provider_from_row(row: dict) -> ProviderConfig:
    return ProviderConfig(
        id=row["id"],
        tenant_id=row["tenant_id"],
        name=row["name"],
        provider_type=ProviderType(row["provider_type"]),
        base_url=row["base_url"] or "",
        organization_id=row.get("organization_id"),
        deployment_name=row.get("deployment_name"),
        timeout_seconds=int(row["timeout_seconds"]),
        max_retries=int(row["max_retries"]),
        egress_class=row["egress_class"],
        sap_data_permitted=bool(row["sap_data_permitted"]),
        is_active=bool(row["is_active"]),
    )


def model_from_row(row: dict) -> ModelConfig:
    return ModelConfig(
        id=row["id"],
        tenant_id=row["tenant_id"],
        provider_id=row["provider_id"],
        model_name=row["model_name"],
        model_identifier=row["model_identifier"],
        purpose=Purpose(row["purpose"]),
        context_window=int(row["context_window"]),
        max_tokens=int(row["max_tokens"]),
        temperature=float(row["temperature"]),
        prompt_profile=row["prompt_profile"],
        is_active=bool(row["is_active"]),
    )


# ── Postgres implementation ───────────────────────────────────────────────────

class PostgresConfigStore(ConfigStore):
    """Reads the ai_* tables, cached for CACHE_TTL_SECONDS."""

    def __init__(self, ttl: int = CACHE_TTL_SECONDS):
        self._ttl = ttl
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, object]] = {}

    # -- cache plumbing --

    def _cached(self, key: str, loader):
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(key)
            if hit and now - hit[0] < self._ttl:
                return hit[1]
        value = loader()
        with self._lock:
            self._cache[key] = (now, value)
        return value

    def invalidate(self) -> None:
        """Drop everything. Called after any admin write in this worker."""
        with self._lock:
            self._cache.clear()

    # -- reads --

    def list_providers(self, tenant_id: str) -> list[ProviderConfig]:
        def load():
            from db.connection import query_all
            rows = query_all(
                "SELECT * FROM ai_providers WHERE tenant_id = %s ORDER BY name", (tenant_id,)
            )
            return [provider_from_row(r) for r in rows]
        return self._cached(f"providers:{tenant_id}", load)

    def get_provider(self, provider_id: str, tenant_id: str) -> ProviderConfig | None:
        return next(
            (p for p in self.list_providers(tenant_id) if p.id == provider_id), None
        )

    def list_models(self, tenant_id, purpose=None, active_only=True) -> list[ModelConfig]:
        def load():
            from db.connection import query_all
            rows = query_all(
                "SELECT * FROM ai_models WHERE tenant_id = %s ORDER BY model_name", (tenant_id,)
            )
            return [model_from_row(r) for r in rows]
        models = self._cached(f"models:{tenant_id}", load)
        if purpose is not None:
            models = [m for m in models if m.purpose == purpose]
        if active_only:
            models = [m for m in models if m.is_active]
        return list(models)

    def get_model(self, model_id: str, tenant_id: str) -> ModelConfig | None:
        return next(
            (m for m in self.list_models(tenant_id, active_only=False) if m.id == model_id), None
        )

    def get_capabilities(self, model_id: str) -> frozenset[Capability]:
        def load():
            from db.connection import query_all
            rows = query_all(
                "SELECT capability FROM ai_model_capabilities "
                "WHERE model_id = %s AND supported IS TRUE",
                (model_id,),
            )
            out = set()
            for r in rows:
                try:
                    out.add(Capability(r["capability"]))
                except ValueError:
                    _logger.warning("Unknown capability %r on model %s", r["capability"], model_id)
            return frozenset(out)
        return self._cached(f"caps:{model_id}", load)

    def get_routing_rules(self, tenant_id, rule_type, match_key=None) -> list[RoutingRule]:
        def load():
            from db.connection import query_all
            rows = query_all(
                "SELECT * FROM ai_model_routing WHERE tenant_id = %s AND rule_type = %s "
                "AND is_active IS TRUE ORDER BY priority ASC",
                (tenant_id, rule_type),
            )
            return [
                RoutingRule(
                    id=r["id"], tenant_id=r["tenant_id"], rule_type=r["rule_type"],
                    match_key=r["match_key"], model_id=r["model_id"],
                    priority=int(r["priority"]), is_active=bool(r["is_active"]),
                )
                for r in rows
            ]
        rules = self._cached(f"routing:{tenant_id}:{rule_type}", load)
        if match_key is not None:
            rules = [r for r in rules if r.match_key == match_key]
        return list(rules)

    def get_policy(self, tenant_id: str) -> TenantPolicy:
        def load():
            from db.connection import query_one
            row = query_one("SELECT * FROM ai_tenant_policy WHERE tenant_id = %s", (tenant_id,))
            if not row:
                return default_policy(tenant_id)
            return TenantPolicy(
                tenant_id=row["tenant_id"],
                allow_user_selection=bool(row["allow_user_selection"]),
                fallback_enabled=bool(row["fallback_enabled"]),
                default_chat_model_id=row["default_chat_model_id"],
                default_embedding_model_id=row["default_embedding_model_id"],
                default_reranker_model_id=row["default_reranker_model_id"],
            )
        return self._cached(f"policy:{tenant_id}", load)

    def _tenant_model_flags(self, tenant_id: str) -> dict[str, dict]:
        def load():
            from db.connection import query_all
            rows = query_all(
                "SELECT model_id, allowed, user_selectable FROM ai_tenant_models "
                "WHERE tenant_id = %s",
                (tenant_id,),
            )
            return {r["model_id"]: r for r in rows}
        return self._cached(f"tenantmodels:{tenant_id}", load)

    def is_model_allowed(self, tenant_id: str, model_id: str) -> bool:
        row = self._tenant_model_flags(tenant_id).get(model_id)
        if row is None:
            # No explicit grant row: a model belonging to this tenant is usable.
            return self.get_model(model_id, tenant_id) is not None
        return bool(row["allowed"])

    def is_user_selectable(self, tenant_id: str, model_id: str) -> bool:
        row = self._tenant_model_flags(tenant_id).get(model_id)
        return bool(row["user_selectable"]) if row else False


# ── Snapshot ──────────────────────────────────────────────────────────────────

def snapshot_payload(store: ConfigStore, tenant_id: str = DEFAULT_TENANT) -> dict:
    """Serialize the active configuration, credentials excluded."""
    return {
        "tenant_id": tenant_id,
        "providers": [
            {
                "id": p.id, "tenant_id": p.tenant_id, "name": p.name,
                "provider_type": p.provider_type.value, "base_url": p.base_url,
                "organization_id": p.organization_id, "deployment_name": p.deployment_name,
                "timeout_seconds": p.timeout_seconds, "max_retries": p.max_retries,
                "egress_class": p.egress_class, "sap_data_permitted": p.sap_data_permitted,
                "is_active": p.is_active,
            }
            for p in store.list_providers(tenant_id)
        ],
        "models": [
            {
                "id": m.id, "tenant_id": m.tenant_id, "provider_id": m.provider_id,
                "model_name": m.model_name, "model_identifier": m.model_identifier,
                "purpose": m.purpose.value, "context_window": m.context_window,
                "max_tokens": m.max_tokens, "temperature": m.temperature,
                "prompt_profile": m.prompt_profile, "is_active": m.is_active,
                "capabilities": sorted(c.value for c in store.get_capabilities(m.id)),
            }
            for m in store.list_models(tenant_id, active_only=False)
        ],
        "policy": store.get_policy(tenant_id).__dict__,
    }


def snapshot_to_store(payload: dict) -> ConfigStore:
    """Rebuild a read-only store from a snapshot. Used only when PostgreSQL is down."""
    # Imported lazily: ai/memory_store.py imports from this module.
    from ai.memory_store import InMemoryConfigStore
    store = InMemoryConfigStore()
    store.load_snapshot(payload)
    return store


def write_snapshot(store: ConfigStore, tenant_id: str = DEFAULT_TENANT) -> None:
    """Mirror the active configuration into the `ai` block of config.json."""
    try:
        from core.config_manager import config
        config.update({"ai": snapshot_payload(store, tenant_id)})
    except Exception as exc:
        _logger.warning("Failed to write AI config snapshot: %s", exc)


def load_snapshot() -> dict | None:
    try:
        from core.config_manager import config
        return config.get().get("ai") or None
    except Exception:
        return None


# ── Module singleton ──────────────────────────────────────────────────────────

_store: ConfigStore | None = None


def get_store() -> ConfigStore:
    global _store
    if _store is None:
        _store = PostgresConfigStore()
    return _store


def set_store(store: ConfigStore | None) -> None:
    """Replace the process store. Tests use this; production never calls it."""
    global _store
    _store = store
