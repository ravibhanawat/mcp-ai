"""
Turns an existing deployment's implicit configuration into explicit rows.

Runs once, on the first boot after upgrading. An operator who had Ollama plus an
OPENAI_API_KEY gets exactly that: an Ollama provider, an OpenAI provider, and a
fallback chain in the order the old `_call_cloud_fallback` used. The first
request after the upgrade is answered by the same model as the last request
before it.

Two rules that are easy to get wrong:

  * Seeding is skipped entirely once any provider row exists. Configuration must
    never change because of a boot-time probe — requirement 12's "do not
    silently switch" applies to the configuration itself, not only to dispatch.

  * The MLX server is probed here and only here. Previously `_mlx_available()`
    ran on every SAPAgent construction, so whether the fine-tuned model answered
    depended on what happened to be running. Now it is a row an administrator
    can see and turn off.
"""
from __future__ import annotations

import logging
import os
import uuid

from ai.capabilities import DEFAULT_CAPABILITIES, set_capabilities
from ai.credentials import store_credential
from ai.types import Capability, ProviderType, Purpose

_logger = logging.getLogger("ai.seed")

MLX_PROBE_URL = os.environ.get("MLX_PROBE_URL", "http://localhost:8080")

#: Model identifiers previously hardcoded as env-var defaults. They are seeds for
#: an editable row, not application defaults — nothing reads them at request time.
_LEGACY_OPENAI_MODEL = os.environ.get("OPENAI_FALLBACK_MODEL", "gpt-4o-mini")
_LEGACY_ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_FALLBACK_MODEL", "claude-haiku-4-5")


# ── database indirections (patched in tests) ─────────────────────────────────

def _provider_count(tenant_id: str) -> int:
    from db.connection import query_one
    row = query_one("SELECT COUNT(*) AS n FROM ai_providers WHERE tenant_id = %s", (tenant_id,))
    return int(row["n"]) if row else 0


def _insert_provider(**kw) -> str:
    from db.connection import execute
    execute(
        """INSERT INTO ai_providers
               (id, tenant_id, name, provider_type, base_url, timeout_seconds,
                max_retries, egress_class, sap_data_permitted, is_active)
           VALUES (%(id)s, %(tenant_id)s, %(name)s, %(provider_type)s, %(base_url)s,
                   %(timeout_seconds)s, %(max_retries)s, %(egress_class)s,
                   %(sap_data_permitted)s, %(is_active)s)""",
        kw,
    )
    return kw["id"]


def _insert_model(**kw) -> str:
    from db.connection import execute
    execute(
        """INSERT INTO ai_models
               (id, tenant_id, provider_id, model_name, model_identifier, purpose,
                context_window, max_tokens, temperature, prompt_profile, is_active)
           VALUES (%(id)s, %(tenant_id)s, %(provider_id)s, %(model_name)s,
                   %(model_identifier)s, %(purpose)s, %(context_window)s,
                   %(max_tokens)s, %(temperature)s, %(prompt_profile)s, %(is_active)s)""",
        kw,
    )
    return kw["id"]


def _insert_fallback_rule(**kw) -> None:
    from db.connection import execute
    execute(
        """INSERT INTO ai_model_routing
               (id, tenant_id, rule_type, match_key, model_id, priority, is_active)
           VALUES (%(id)s, %(tenant_id)s, 'fallback', %(match_key)s, %(model_id)s,
                   %(priority)s, TRUE)""",
        kw,
    )


def _upsert_policy(**kw) -> None:
    from db.connection import execute
    execute(
        """INSERT INTO ai_tenant_policy
               (tenant_id, allow_user_selection, fallback_enabled, default_chat_model_id)
           VALUES (%(tenant_id)s, FALSE, TRUE, %(default_chat_model_id)s)
           ON CONFLICT (tenant_id) DO UPDATE SET
               default_chat_model_id = EXCLUDED.default_chat_model_id""",
        kw,
    )


def _ollama_settings() -> tuple[str, str]:
    """Read the legacy ollama block from config.json."""
    from core.config_manager import config
    return config.ollama_url, config.default_model


def _mlx_present() -> bool:
    """One-time probe for a running MLX server. Never called after the first seed."""
    try:
        import requests
        resp = requests.get(f"{MLX_PROBE_URL}/v1/models", timeout=2)
        return resp.status_code == 200
    except Exception:
        return False


# ── seeding ───────────────────────────────────────────────────────────────────

def _new_id() -> str:
    return str(uuid.uuid4())


def _register(model_id: str, tenant_id: str, purpose: Purpose,
              extra: set[Capability] | None = None) -> None:
    caps = set(DEFAULT_CAPABILITIES.get(purpose, {Capability.CHAT})) | (extra or set())
    set_capabilities(model_id, tenant_id, {c: True for c in caps}, source="declared")


def seed_from_existing_config(tenant_id: str = "default") -> dict:
    """Create provider and model rows from config.json and the environment.

    Returns a summary. Does nothing at all if any provider already exists.
    """
    if _provider_count(tenant_id) > 0:
        _logger.info("AI configuration already present; seeding skipped.")
        return {"providers_created": 0, "models_created": 0, "skipped": True}

    created_providers = created_models = 0
    fallback: list[str] = []

    # 1. Ollama, from the legacy config.json block.
    ollama_url, ollama_model = _ollama_settings()
    ollama_provider_id = _insert_provider(
        id=_new_id(), tenant_id=tenant_id, name="Local Ollama",
        provider_type=ProviderType.OLLAMA.value, base_url=ollama_url,
        timeout_seconds=30, max_retries=2, egress_class="local",
        sap_data_permitted=False, is_active=True,
    )
    created_providers += 1
    chat_model_id = _insert_model(
        id=_new_id(), tenant_id=tenant_id, provider_id=ollama_provider_id,
        model_name="Local Chat Model", model_identifier=ollama_model,
        purpose=Purpose.CHAT.value, context_window=8192, max_tokens=1024,
        temperature=0.10, prompt_profile="registry_tool_json", is_active=True,
    )
    _register(chat_model_id, tenant_id, Purpose.CHAT)
    created_models += 1

    # 2. The fine-tuned MLX server, if one is running right now.
    if _mlx_present():
        mlx_provider_id = _insert_provider(
            id=_new_id(), tenant_id=tenant_id, name="MLX Local",
            provider_type=ProviderType.CUSTOM.value, base_url=MLX_PROBE_URL,
            timeout_seconds=30, max_retries=1, egress_class="local",
            sap_data_permitted=False, is_active=True,
        )
        created_providers += 1
        mlx_model_id = _insert_model(
            id=_new_id(), tenant_id=tenant_id, provider_id=mlx_provider_id,
            model_name="SAP Fine-Tuned (MLX)",
            model_identifier=os.environ.get("MLX_MODEL_PATH", "training/sap-model-fused"),
            purpose=Purpose.CHAT.value, context_window=4096, max_tokens=256,
            temperature=0.05, prompt_profile="trained_tool_json", is_active=True,
        )
        _register(mlx_model_id, tenant_id, Purpose.CHAT)
        created_models += 1

    # 3. Cloud providers, preserving the old OpenAI-then-Anthropic order.
    for name, ptype, base_url, env_var, identifier in (
        ("OpenAI", ProviderType.OPENAI.value, "https://api.openai.com",
         "OPENAI_API_KEY", _LEGACY_OPENAI_MODEL),
        ("Anthropic", ProviderType.ANTHROPIC.value, "https://api.anthropic.com",
         "ANTHROPIC_API_KEY", _LEGACY_ANTHROPIC_MODEL),
    ):
        key = os.environ.get(env_var, "").strip()
        if not key:
            continue
        provider_id = _insert_provider(
            id=_new_id(), tenant_id=tenant_id, name=name, provider_type=ptype,
            base_url=base_url, timeout_seconds=30, max_retries=2,
            egress_class="external", sap_data_permitted=False, is_active=True,
        )
        created_providers += 1
        try:
            store_credential(provider_id, tenant_id, key)
        except Exception as exc:
            _logger.warning(
                "Seeded provider %s but could not store its key (%s). "
                "Re-enter it in Administration → AI Configuration.", name, exc,
            )
        model_id = _insert_model(
            id=_new_id(), tenant_id=tenant_id, provider_id=provider_id,
            model_name=f"{name} Chat", model_identifier=identifier,
            purpose=Purpose.CHAT.value, context_window=128000, max_tokens=1024,
            temperature=0.10, prompt_profile="registry_tool_json", is_active=True,
        )
        _register(model_id, tenant_id, Purpose.CHAT, extra={Capability.TOOL_CALLING})
        created_models += 1
        fallback.append(model_id)

    for priority, model_id in enumerate(fallback):
        _insert_fallback_rule(
            id=_new_id(), tenant_id=tenant_id, match_key=Purpose.CHAT.value,
            model_id=model_id, priority=priority,
        )

    _upsert_policy(tenant_id=tenant_id, default_chat_model_id=chat_model_id)

    _logger.info(
        "Seeded AI configuration: %d provider(s), %d model(s).",
        created_providers, created_models,
    )
    return {
        "providers_created": created_providers,
        "models_created": created_models,
        "skipped": False,
    }
