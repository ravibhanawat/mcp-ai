"""
Administration endpoints for AI providers and models.

Every route requires the admin role. The one deliberate design constraint is
that no response model here has a field capable of carrying a credential: the
UI shows `credential_masked`, derived from the stored last four characters, and
the plaintext never travels back to a browser once it has been submitted.
"""
from __future__ import annotations

import ipaddress
import logging
import uuid
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from ai.credentials import credential_display, delete_credential, is_unchanged, store_credential
from ai.errors import CredentialUnavailable
from ai.providers.registry import build_provider, supported_provider_types
from ai.store import get_store, provider_from_row, write_snapshot
from ai.types import ProviderType
from api.deps import get_current_user, require_admin

_logger = logging.getLogger("api.routes_ai_admin")

router = APIRouter(prefix="/admin/ai", tags=["ai-admin"])

DEFAULT_TENANT = "default"


# get_current_user and require_admin come from api/deps.py rather than
# api/server.py: server.py imports this module, so importing back from it would
# be circular. See Task 20 Step 3.


# ── database indirections (patched in tests) ─────────────────────────────────

def _list_provider_rows(tenant_id: str) -> list[dict]:
    from db.connection import query_all
    return query_all(
        "SELECT * FROM ai_providers WHERE tenant_id = %s ORDER BY name", (tenant_id,)
    )


def _get_provider_row(provider_id: str, tenant_id: str) -> dict | None:
    from db.connection import query_one
    return query_one(
        "SELECT * FROM ai_providers WHERE id = %s AND tenant_id = %s", (provider_id, tenant_id)
    )


def _insert_provider_row(values: dict) -> str:
    from db.connection import execute
    execute(
        """INSERT INTO ai_providers
               (id, tenant_id, name, provider_type, base_url, organization_id,
                deployment_name, timeout_seconds, max_retries, egress_class,
                sap_data_permitted, is_active, updated_by)
           VALUES (%(id)s, %(tenant_id)s, %(name)s, %(provider_type)s, %(base_url)s,
                   %(organization_id)s, %(deployment_name)s, %(timeout_seconds)s,
                   %(max_retries)s, %(egress_class)s, %(sap_data_permitted)s,
                   %(is_active)s, %(updated_by)s)""",
        values,
    )
    return values["id"]


def _update_provider_row(provider_id: str, tenant_id: str, values: dict) -> None:
    from db.connection import execute
    assignments = ", ".join(f"{k} = %({k})s" for k in values)
    execute(
        f"UPDATE ai_providers SET {assignments}, updated_at = NOW() "
        "WHERE id = %(id)s AND tenant_id = %(tenant_id)s",
        {**values, "id": provider_id, "tenant_id": tenant_id},
    )


def _delete_provider_row(provider_id: str, tenant_id: str) -> None:
    from db.connection import execute
    execute("DELETE FROM ai_providers WHERE id = %s AND tenant_id = %s", (provider_id, tenant_id))


# ── egress classification ─────────────────────────────────────────────────────

def derive_egress_class(provider_type: str, base_url: str | None) -> str:
    """Classify a provider by where its endpoint actually is.

    Loopback and RFC1918 addresses stay inside the estate; anything else is
    treated as external and its payloads are redacted unless an administrator
    explicitly permits SAP data. Derived rather than asked so a mistyped
    dropdown cannot downgrade the protection.

    Link-local is deliberately NOT part of "inside the estate", even though
    Python's `is_private` says it is. 169.254.169.254 is the cloud instance
    metadata service — the single most valuable exfiltration target on a cloud
    host — and classifying it `local` told `_should_redact` that SAP payloads
    could be sent there unredacted. Reserved and multicast ranges are excluded
    for the same reason: unusual is not trusted.
    """
    if not base_url:
        return "local" if provider_type == ProviderType.OLLAMA.value else "external"
    host = (urlparse(base_url).hostname or "").strip()
    if host in ("localhost", "::1"):
        return "local"
    try:
        address = ipaddress.ip_address(host)
        if address.is_link_local or address.is_reserved or address.is_multicast:
            return "external"
        if address.is_loopback or address.is_private:
            return "local"
    except ValueError:
        pass
    return "external"


# ── schemas ───────────────────────────────────────────────────────────────────

def _validated_base_url(value: str | None) -> str | None:
    """Accept only an http(s) URL with a host — or the empty default.

    base_url had no validation at all, so `javascript:alert(1)`, `file:///etc/
    passwd`, `hello world` and `""` were all stored as *active* providers and
    only failed much later, at dispatch, a long way from the mistake. Ollama
    rows legitimately carry no base_url, so empty stays valid; anything
    non-empty must be a real endpoint.

    Column widths match ai/schema.py, so an over-long value is a 422 here
    rather than an unhandled 500 from the database driver.
    """
    if value is None or value == "":
        return value
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(
            "base_url must be an http:// or https:// URL with a host, "
            f"or empty. Got {value!r}."
        )
    return value


class ProviderIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    provider_type: str = Field(..., max_length=20)
    base_url: str = ""
    organization_id: str | None = Field(default=None, max_length=100)
    deployment_name: str | None = Field(default=None, max_length=100)
    timeout_seconds: int = Field(default=30, ge=1, le=600)
    max_retries: int = Field(default=2, ge=0, le=10)
    #: Raising this lets SAP records reach an external provider unredacted, so it
    #: defaults off and every change is audited.
    sap_data_permitted: bool = False
    #: Constrained to exactly the two values ai.types.EgressClass and
    #: ResolvedModel.is_external understand. A free-form str here (the
    #: original type) let a typo or an unrecognised value pass FastAPI
    #: validation and get written straight to the egress_class column — and
    #: with is_external's OLD "== 'external'" check, anything but that exact
    #: string was treated as not-external, so a misspelled override silently
    #: disabled SAP-data redaction for that provider. Now the API boundary
    #: itself refuses anything else with a 422, before it ever reaches the
    #: database, and is_external separately fails closed on any value that
    #: still finds its way past this (defence in depth).
    egress_class_override: Literal["local", "external"] | None = None
    is_active: bool = True
    api_key: str | None = None

    _check_base_url = field_validator("base_url")(_validated_base_url)


class ProviderUpdate(BaseModel):
    """Schema for PATCH updates; all fields are optional."""
    name: str | None = Field(default=None, min_length=1, max_length=100)
    provider_type: str | None = Field(default=None, max_length=20)
    base_url: str | None = None
    organization_id: str | None = Field(default=None, max_length=100)
    deployment_name: str | None = Field(default=None, max_length=100)
    timeout_seconds: int | None = Field(default=None, ge=1, le=600)
    max_retries: int | None = Field(default=None, ge=0, le=10)
    sap_data_permitted: bool | None = None
    egress_class_override: Literal["local", "external"] | None = None
    is_active: bool | None = None
    api_key: str | None = None

    _check_base_url = field_validator("base_url")(_validated_base_url)


class ProviderOut(BaseModel):
    """No field here can carry a credential. Keep it that way."""
    id: str
    name: str
    provider_type: str
    base_url: str
    organization_id: str | None
    deployment_name: str | None
    timeout_seconds: int
    max_retries: int
    egress_class: str
    sap_data_permitted: bool
    is_active: bool
    credential_masked: str
    has_credential: bool


def _to_out(row: dict) -> ProviderOut:
    masked = credential_display(row["id"], row["tenant_id"])
    return ProviderOut(
        id=row["id"], name=row["name"], provider_type=row["provider_type"],
        base_url=row["base_url"] or "", organization_id=row.get("organization_id"),
        deployment_name=row.get("deployment_name"),
        timeout_seconds=row["timeout_seconds"], max_retries=row["max_retries"],
        egress_class=row["egress_class"], sap_data_permitted=bool(row["sap_data_permitted"]),
        is_active=bool(row["is_active"]), credential_masked=masked,
        has_credential=bool(masked),
    )


# ── routes ────────────────────────────────────────────────────────────────────

@router.get("/provider-types")
def list_provider_types(admin: dict = Depends(require_admin)) -> dict:
    return {"provider_types": supported_provider_types()}


@router.get("/providers", response_model=list[ProviderOut])
def list_providers(admin: dict = Depends(require_admin)):
    return [_to_out(r) for r in _list_provider_rows(DEFAULT_TENANT)]


@router.post("/providers", response_model=ProviderOut, status_code=status.HTTP_201_CREATED)
def create_provider(body: ProviderIn, admin: dict = Depends(require_admin)):
    if body.provider_type not in supported_provider_types():
        raise HTTPException(400, f"Unknown provider type {body.provider_type!r}.")
    provider_id = str(uuid.uuid4())
    egress = body.egress_class_override or derive_egress_class(body.provider_type, body.base_url)
    _insert_provider_row({
        "id": provider_id, "tenant_id": DEFAULT_TENANT, "name": body.name,
        "provider_type": body.provider_type, "base_url": body.base_url,
        "organization_id": body.organization_id, "deployment_name": body.deployment_name,
        "timeout_seconds": body.timeout_seconds, "max_retries": body.max_retries,
        "egress_class": egress, "sap_data_permitted": body.sap_data_permitted,
        "is_active": body.is_active, "updated_by": admin.get("user_id"),
    })
    # The row and its credential are two writes to two stores, so a failure
    # between them has to be undone by hand. Without this, a create that 500'd
    # on an unset AI_CONFIG_KEY still left an *active*, credential-less
    # provider in the routing pool — and every retry added another.
    if body.api_key and not is_unchanged(body.api_key):
        try:
            store_credential(provider_id, DEFAULT_TENANT, body.api_key)
        except CredentialUnavailable as exc:
            _delete_provider_row(provider_id, DEFAULT_TENANT)
            raise HTTPException(503, f"Provider not created: {exc}")
        except Exception:
            _delete_provider_row(provider_id, DEFAULT_TENANT)
            raise
    if body.sap_data_permitted:
        _audit_egress_change(admin, provider_id, body.name, True)
    _invalidate()
    return _to_out(_get_provider_row(provider_id, DEFAULT_TENANT))


@router.patch("/providers/{provider_id}", response_model=ProviderOut)
def update_provider(provider_id: str, body: ProviderUpdate, admin: dict = Depends(require_admin)):
    existing = _get_provider_row(provider_id, DEFAULT_TENANT)
    if not existing:
        raise HTTPException(404, "Provider not found.")

    # Build update dict with only provided fields
    updates = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.provider_type is not None:
        updates["provider_type"] = body.provider_type
    if body.base_url is not None:
        updates["base_url"] = body.base_url
    if body.organization_id is not None:
        updates["organization_id"] = body.organization_id
    if body.deployment_name is not None:
        updates["deployment_name"] = body.deployment_name
    if body.timeout_seconds is not None:
        updates["timeout_seconds"] = body.timeout_seconds
    if body.max_retries is not None:
        updates["max_retries"] = body.max_retries
    if body.sap_data_permitted is not None:
        updates["sap_data_permitted"] = body.sap_data_permitted
    if body.is_active is not None:
        updates["is_active"] = body.is_active

    # Determine egress class based on updated or existing values
    provider_type = updates.get("provider_type", existing["provider_type"])
    base_url = updates.get("base_url", existing["base_url"])
    egress = body.egress_class_override or derive_egress_class(provider_type, base_url)
    updates["egress_class"] = egress
    updates["updated_by"] = admin.get("user_id")

    if updates:  # Only update if there are changes
        _update_provider_row(provider_id, DEFAULT_TENANT, updates)

    # The sentinel means "leave the stored key alone" — same idiom as the SAP
    # credential fields in core/config_manager.py.
    if body.api_key and not is_unchanged(body.api_key):
        store_credential(provider_id, DEFAULT_TENANT, body.api_key)

    # Audit egress changes
    new_sap_data = updates.get("sap_data_permitted", existing["sap_data_permitted"])
    if bool(existing["sap_data_permitted"]) != bool(new_sap_data):
        updated_name = updates.get("name", existing["name"])
        _audit_egress_change(admin, provider_id, updated_name, bool(new_sap_data))

    _invalidate()
    return _to_out(_get_provider_row(provider_id, DEFAULT_TENANT))


@router.delete("/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_provider(provider_id: str, admin: dict = Depends(require_admin)):
    # 204 for an id that never existed told an admin who deleted the wrong
    # thing, or a script holding a stale id, that the delete had worked.
    if not _get_provider_row(provider_id, DEFAULT_TENANT):
        raise HTTPException(404, "Provider not found.")
    delete_credential(provider_id, DEFAULT_TENANT)
    _delete_provider_row(provider_id, DEFAULT_TENANT)
    _invalidate()


@router.post("/providers/{provider_id}/test")
def test_provider(provider_id: str, admin: dict = Depends(require_admin)) -> dict:
    row = _get_provider_row(provider_id, DEFAULT_TENANT)
    if not row:
        raise HTTPException(404, "Provider not found.")
    from ai.credentials import read_credential
    result = build_provider(provider_from_row(row), read_credential(provider_id, DEFAULT_TENANT)).health_check()
    return {"status": result.status, "latency_ms": result.latency_ms, "error": result.error}


@router.get("/providers/{provider_id}/models")
def list_remote_models(provider_id: str, admin: dict = Depends(require_admin)) -> dict:
    """Ask the provider what it currently offers, for the model form's dropdown."""
    row = _get_provider_row(provider_id, DEFAULT_TENANT)
    if not row:
        raise HTTPException(404, "Provider not found.")
    from ai.credentials import read_credential
    identifiers = build_provider(
        provider_from_row(row), read_credential(provider_id, DEFAULT_TENANT)
    ).list_models()
    return {"models": identifiers, "listable": bool(identifiers)}


# ── helpers ───────────────────────────────────────────────────────────────────

def _invalidate() -> None:
    """Drop this worker's cache and refresh the cold-start snapshot."""
    try:
        store = get_store()
        if hasattr(store, "invalidate"):
            store.invalidate()
        write_snapshot(store, DEFAULT_TENANT)
    except Exception:
        _logger.warning("Failed to invalidate store.", exc_info=True)


def _audit_egress_change(admin: dict, provider_id: str, name: str, permitted: bool) -> None:
    """Permitting SAP data to reach an external provider is an audited decision."""
    try:
        from core.audit_logger import log_request
        log_request(
            user_id=admin.get("user_id", "unknown"), user_roles=admin.get("roles", []),
            client_ip="admin-api", endpoint="ai_provider_egress",
            query=(f"sap_data_permitted set to {permitted} for provider "
                   f"{name!r} ({provider_id})"),
            tool_called=None, status="ok",
        )
    except Exception:
        _logger.warning("Failed to audit egress policy change.", exc_info=True)


# ── models ────────────────────────────────────────────────────────────────────

from ai.capabilities import DEFAULT_CAPABILITIES, probe_capabilities, set_capabilities
from ai.health import last_health, probe, record_health
from ai.types import Capability, Purpose, ResolvedModel
from ai.validation import all_passed, validate


def _list_model_rows(tenant_id: str) -> list[dict]:
    from db.connection import query_all
    return query_all(
        "SELECT * FROM ai_models WHERE tenant_id = %s ORDER BY model_name", (tenant_id,)
    )


def _get_model_row(model_id: str, tenant_id: str) -> dict | None:
    from db.connection import query_one
    return query_one(
        "SELECT * FROM ai_models WHERE id = %s AND tenant_id = %s", (model_id, tenant_id)
    )


def _insert_model_row(values: dict) -> str:
    from db.connection import execute
    execute(
        """INSERT INTO ai_models
               (id, tenant_id, provider_id, model_name, model_identifier, purpose,
                context_window, max_tokens, temperature, prompt_profile, is_active)
           VALUES (%(id)s, %(tenant_id)s, %(provider_id)s, %(model_name)s,
                   %(model_identifier)s, %(purpose)s, %(context_window)s, %(max_tokens)s,
                   %(temperature)s, %(prompt_profile)s, %(is_active)s)""",
        values,
    )
    return values["id"]


def _update_model_row(model_id: str, tenant_id: str, values: dict) -> None:
    from db.connection import execute
    assignments = ", ".join(f"{k} = %({k})s" for k in values)
    execute(
        f"UPDATE ai_models SET {assignments}, updated_at = NOW() "
        "WHERE id = %(id)s AND tenant_id = %(tenant_id)s",
        {**values, "id": model_id, "tenant_id": tenant_id},
    )


def _set_model_active(model_id: str, tenant_id: str, active: bool) -> None:
    from db.connection import execute
    execute(
        "UPDATE ai_models SET is_active = %s, updated_at = NOW() "
        "WHERE id = %s AND tenant_id = %s",
        (active, model_id, tenant_id),
    )


def _resolved_for(model_id: str, tenant_id: str) -> ResolvedModel | None:
    return get_store().resolved(model_id, tenant_id)


class ModelIn(BaseModel):
    provider_id: str
    model_name: str
    model_identifier: str
    purpose: Purpose
    context_window: int = Field(default=8192, ge=1)
    max_tokens: int = Field(default=1024, ge=1)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    prompt_profile: str = "registry_tool_json"
    capabilities: list[str] | None = None


class ModelOut(BaseModel):
    id: str
    provider_id: str
    provider_name: str
    model_name: str
    model_identifier: str
    purpose: str
    context_window: int
    max_tokens: int
    temperature: float
    prompt_profile: str
    is_active: bool
    is_default: bool
    capabilities: list[str]
    health: dict[str, Any] | None


def _model_to_out(row: dict) -> ModelOut:
    store = get_store()
    provider = store.get_provider(row["provider_id"], row["tenant_id"])
    policy = store.get_policy(row["tenant_id"])
    return ModelOut(
        id=row["id"], provider_id=row["provider_id"],
        provider_name=provider.name if provider else "(missing provider)",
        model_name=row["model_name"], model_identifier=row["model_identifier"],
        purpose=row["purpose"], context_window=row["context_window"],
        max_tokens=row["max_tokens"], temperature=float(row["temperature"]),
        prompt_profile=row["prompt_profile"], is_active=bool(row["is_active"]),
        is_default=row["id"] in {
            policy.default_chat_model_id, policy.default_embedding_model_id,
            policy.default_reranker_model_id,
        },
        capabilities=sorted(c.value for c in store.get_capabilities(row["id"], row["tenant_id"])),
        health=last_health(row["id"], row["tenant_id"]),
    )


@router.get("/models", response_model=list[ModelOut])
def list_models(admin: dict = Depends(require_admin)):
    return [_model_to_out(r) for r in _list_model_rows(DEFAULT_TENANT)]


@router.post("/models", response_model=ModelOut, status_code=status.HTTP_201_CREATED)
def create_model(body: ModelIn, admin: dict = Depends(require_admin)):
    """Always created inactive — activation requires passing validation."""
    model_id = str(uuid.uuid4())
    _insert_model_row({
        "id": model_id, "tenant_id": DEFAULT_TENANT, "provider_id": body.provider_id,
        "model_name": body.model_name, "model_identifier": body.model_identifier,
        "purpose": body.purpose.value, "context_window": body.context_window,
        "max_tokens": body.max_tokens, "temperature": body.temperature,
        "prompt_profile": body.prompt_profile, "is_active": False,
    })
    declared = (
        {Capability(c) for c in body.capabilities}
        if body.capabilities is not None
        else set(DEFAULT_CAPABILITIES.get(body.purpose, {Capability.CHAT}))
    )
    set_capabilities(model_id, DEFAULT_TENANT, {c: True for c in declared}, source="declared")
    _invalidate()
    return _model_to_out(_get_model_row(model_id, DEFAULT_TENANT))


@router.patch("/models/{model_id}", response_model=ModelOut)
def update_model(model_id: str, body: ModelIn, admin: dict = Depends(require_admin)):
    """Requirement 22's activation gate must survive a PATCH, not just a
    fresh create. `provider_id`, `model_identifier` and `purpose` together
    define WHICH model this row actually resolves to at dispatch time — the
    exact thing `validate()`/`activate_model()` checked. Changing any of them
    on an already-active model, without this guard, would let an admin swap
    what an active row points at (e.g. re-point it at an unreachable provider,
    or one that doesn't offer that identifier) with no revalidation at all,
    bypassing the activation gate entirely. Cosmetic fields (name, tuning
    parameters, prompt_profile) do not affect what gets dispatched to, so they
    do not force deactivation.
    """
    existing = _get_model_row(model_id, DEFAULT_TENANT)
    if not existing:
        raise HTTPException(404, "Model not found.")
    updates = {
        "provider_id": body.provider_id, "model_name": body.model_name,
        "model_identifier": body.model_identifier, "purpose": body.purpose.value,
        "context_window": body.context_window, "max_tokens": body.max_tokens,
        "temperature": body.temperature, "prompt_profile": body.prompt_profile,
    }
    identity_changed = (
        existing["provider_id"] != body.provider_id
        or existing["model_identifier"] != body.model_identifier
        or existing["purpose"] != body.purpose.value
    )
    if identity_changed and bool(existing["is_active"]):
        updates["is_active"] = False
    _update_model_row(model_id, DEFAULT_TENANT, updates)
    if body.capabilities is not None:
        set_capabilities(
            model_id, DEFAULT_TENANT,
            {Capability(c): True for c in body.capabilities}, source="declared",
        )
    _invalidate()
    return _model_to_out(_get_model_row(model_id, DEFAULT_TENANT))


@router.delete("/models/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_model(model_id: str, admin: dict = Depends(require_admin)):
    from db.connection import execute
    execute("DELETE FROM ai_models WHERE id = %s AND tenant_id = %s", (model_id, DEFAULT_TENANT))
    _invalidate()


@router.post("/models/{model_id}/validate")
def validate_model(model_id: str, admin: dict = Depends(require_admin)) -> dict:
    if not _get_model_row(model_id, DEFAULT_TENANT):
        raise HTTPException(404, "Model not found.")
    resolved = _resolved_for(model_id, DEFAULT_TENANT)
    if resolved is None:
        raise HTTPException(400, "Model has no reachable provider configuration.")
    from ai.credentials import read_credential
    results = validate(resolved, read_credential(resolved.provider.id, DEFAULT_TENANT))
    return {
        "all_passed": all_passed(results),
        "checks": [{"name": r.name, "passed": r.passed, "detail": r.detail} for r in results],
    }


@router.post("/models/{model_id}/activate", response_model=ModelOut)
def activate_model(model_id: str, admin: dict = Depends(require_admin)):
    """Refuses activation unless every check passes (requirement 22)."""
    if not _get_model_row(model_id, DEFAULT_TENANT):
        raise HTTPException(404, "Model not found.")
    resolved = _resolved_for(model_id, DEFAULT_TENANT)
    if resolved is None:
        raise HTTPException(400, "Model has no reachable provider configuration.")
    from ai.credentials import read_credential
    api_key = read_credential(resolved.provider.id, DEFAULT_TENANT)
    results = validate(resolved, api_key)
    if not all_passed(results):
        raise HTTPException(400, {
            "message": "Model cannot be activated: validation failed.",
            "checks": [
                {"name": r.name, "passed": r.passed, "detail": r.detail} for r in results
            ],
        })
    probed = probe_capabilities(resolved, api_key)
    if probed:
        set_capabilities(model_id, DEFAULT_TENANT, probed, source="probed")
    _set_model_active(model_id, DEFAULT_TENANT, True)
    _invalidate()
    return _model_to_out(_get_model_row(model_id, DEFAULT_TENANT))


@router.post("/models/{model_id}/deactivate", response_model=ModelOut)
def deactivate_model(model_id: str, admin: dict = Depends(require_admin)):
    if not _get_model_row(model_id, DEFAULT_TENANT):
        raise HTTPException(404, "Model not found.")
    _set_model_active(model_id, DEFAULT_TENANT, False)
    _invalidate()
    return _model_to_out(_get_model_row(model_id, DEFAULT_TENANT))


@router.post("/models/{model_id}/test")
def test_model(model_id: str, admin: dict = Depends(require_admin)) -> dict:
    """Send a real one-token completion and report latency."""
    resolved = _resolved_for(model_id, DEFAULT_TENANT)
    if resolved is None:
        raise HTTPException(404, "Model not found.")
    from ai.credentials import read_credential
    result = probe(resolved, read_credential(resolved.provider.id, DEFAULT_TENANT))
    record_health(model_id, DEFAULT_TENANT, result)
    return {"status": result.status, "latency_ms": result.latency_ms, "error": result.error}


# ── routing, fallback, policy ─────────────────────────────────────────────────

class PolicyIn(BaseModel):
    allow_user_selection: bool = False
    fallback_enabled: bool = True
    default_chat_model_id: str | None = None
    default_embedding_model_id: str | None = None
    default_reranker_model_id: str | None = None


class RuleIn(BaseModel):
    rule_type: str            # 'purpose' | 'intent'
    match_key: str
    model_id: str
    priority: int = 100


class RoutingIn(BaseModel):
    rules: list[RuleIn]


class ChainIn(BaseModel):
    purpose: Purpose
    model_ids: list[str]


class FallbackIn(BaseModel):
    chains: list[ChainIn]


def _upsert_policy_row(values: dict) -> None:
    from db.connection import execute
    execute(
        """INSERT INTO ai_tenant_policy
               (tenant_id, allow_user_selection, fallback_enabled, default_chat_model_id,
                default_embedding_model_id, default_reranker_model_id)
           VALUES (%(tenant_id)s, %(allow_user_selection)s, %(fallback_enabled)s,
                   %(default_chat_model_id)s, %(default_embedding_model_id)s,
                   %(default_reranker_model_id)s)
           ON CONFLICT (tenant_id) DO UPDATE SET
               allow_user_selection       = EXCLUDED.allow_user_selection,
               fallback_enabled           = EXCLUDED.fallback_enabled,
               default_chat_model_id      = EXCLUDED.default_chat_model_id,
               default_embedding_model_id = EXCLUDED.default_embedding_model_id,
               default_reranker_model_id  = EXCLUDED.default_reranker_model_id,
               updated_at                 = NOW()""",
        values,
    )


def _delete_rules(tenant_id: str, rule_types: list[str]) -> None:
    from db.connection import execute
    execute(
        "DELETE FROM ai_model_routing WHERE tenant_id = %s AND rule_type = ANY(%s)",
        (tenant_id, rule_types),
    )


def _insert_rule(values: dict) -> None:
    from db.connection import execute
    execute(
        """INSERT INTO ai_model_routing
               (id, tenant_id, rule_type, match_key, model_id, priority, is_active)
           VALUES (%(id)s, %(tenant_id)s, %(rule_type)s, %(match_key)s, %(model_id)s,
                   %(priority)s, TRUE)""",
        values,
    )


def _rules_out(rule_types: list[str]) -> list[dict]:
    store = get_store()
    out = []
    for rule_type in rule_types:
        for rule in store.get_routing_rules(DEFAULT_TENANT, rule_type):
            out.append({
                "id": rule.id, "rule_type": rule.rule_type, "match_key": rule.match_key,
                "model_id": rule.model_id, "priority": rule.priority,
            })
    return out


def _policy_out() -> dict:
    return get_store().get_policy(DEFAULT_TENANT).__dict__


@router.get("/policy")
def get_policy(admin: dict = Depends(require_admin)) -> dict:
    return _policy_out()


def _assert_usable_default(model_id: str | None, purpose: Purpose, field: str) -> None:
    """Refuse a default that points at a model which cannot serve it.

    Nothing checked these ids, so an id belonging to no model at all saved
    with a 200 and took chat down for every user — reported as a 503 blaming
    the configuration *database*, which sent the operator looking in entirely
    the wrong place. Clearing a default (None) stays valid.
    """
    if model_id is None:
        return
    row = _get_model_row(model_id, DEFAULT_TENANT)
    if row is None:
        raise HTTPException(400, f"{field}: no model with id {model_id!r} exists.")
    if not row["is_active"]:
        raise HTTPException(
            400,
            f"{field}: model {row.get('model_name', model_id)!r} is not active. "
            "Activate it first — activation is what proves it can serve requests.",
        )
    if row["purpose"] != purpose.value:
        raise HTTPException(
            400,
            f"{field}: model {row.get('model_name', model_id)!r} has purpose "
            f"{row['purpose']}, not {purpose.value}.",
        )


@router.put("/policy")
def put_policy(body: PolicyIn, admin: dict = Depends(require_admin)) -> dict:
    _assert_usable_default(body.default_chat_model_id, Purpose.CHAT,
                           "default_chat_model_id")
    _assert_usable_default(body.default_embedding_model_id, Purpose.EMBEDDING,
                           "default_embedding_model_id")
    _assert_usable_default(body.default_reranker_model_id, Purpose.RERANKING,
                           "default_reranker_model_id")
    _upsert_policy_row({"tenant_id": DEFAULT_TENANT, **body.model_dump()})
    _invalidate()
    return _policy_out()


@router.get("/routing")
def get_routing(admin: dict = Depends(require_admin)) -> dict:
    return {"rules": _rules_out(["purpose", "intent"])}


@router.put("/routing")
def put_routing(body: RoutingIn, admin: dict = Depends(require_admin)) -> dict:
    """Replaces all purpose and intent rules. Fallback rules are untouched."""
    _delete_rules(DEFAULT_TENANT, ["purpose", "intent"])
    for rule in body.rules:
        _insert_rule({
            "id": str(uuid.uuid4()), "tenant_id": DEFAULT_TENANT,
            "rule_type": rule.rule_type, "match_key": rule.match_key,
            "model_id": rule.model_id, "priority": rule.priority,
        })
    _invalidate()
    return {"rules": _rules_out(["purpose", "intent"])}


@router.get("/fallback")
def get_fallback(admin: dict = Depends(require_admin)) -> dict:
    return {"rules": _rules_out(["fallback"])}


@router.put("/fallback")
def put_fallback(body: FallbackIn, admin: dict = Depends(require_admin)) -> dict:
    """Replaces every fallback chain. List order is the failover order."""
    _delete_rules(DEFAULT_TENANT, ["fallback"])
    for chain in body.chains:
        for priority, model_id in enumerate(chain.model_ids):
            _insert_rule({
                "id": str(uuid.uuid4()), "tenant_id": DEFAULT_TENANT,
                "rule_type": "fallback", "match_key": chain.purpose.value,
                "model_id": model_id, "priority": priority,
            })
    _invalidate()
    return {"rules": _rules_out(["fallback"])}


@router.get("/health")
def health_overview(admin: dict = Depends(require_admin)) -> dict:
    from db.connection import query_all
    rows = query_all(
        """SELECT h.model_id, m.model_name, p.name AS provider_name, h.status,
                  h.latency_ms, h.checked_at, h.last_success_at, h.last_error
             FROM ai_model_health h
             JOIN ai_models m    ON m.id = h.model_id
             JOIN ai_providers p ON p.id = m.provider_id
            WHERE h.tenant_id = %s
            ORDER BY m.model_name""",
        (DEFAULT_TENANT,),
    )
    return {"models": rows}


@router.get("/usage")
def usage(limit: int = 100, admin: dict = Depends(require_admin)) -> dict:
    from db.connection import query_all
    rows = query_all(
        "SELECT * FROM ai_usage_logs WHERE tenant_id = %s ORDER BY created_at DESC LIMIT %s",
        (DEFAULT_TENANT, min(limit, 500)),
    )
    return {"entries": rows}


# ── user-facing ───────────────────────────────────────────────────────────────

user_router = APIRouter(tags=["ai"])


def _store_for_user():
    return get_store()


@user_router.get("/ai/models/available")
def available_models(current_user: dict = Depends(get_current_user)) -> dict:
    """Models this caller may select.

    Returns an empty list when selection is disabled. Exposes only id, name and
    purpose — a normal user has no reason to see a provider's URL, its type, or
    anything else about the infrastructure.
    """
    store = _store_for_user()
    policy = store.get_policy(DEFAULT_TENANT)
    if not policy.allow_user_selection:
        return {"selection_enabled": False, "models": []}
    models = [
        {"id": m.id, "name": m.model_name, "purpose": m.purpose.value}
        for m in store.list_models(DEFAULT_TENANT, active_only=True)
        if store.is_user_selectable(DEFAULT_TENANT, m.id)
    ]
    return {"selection_enabled": True, "models": models}
