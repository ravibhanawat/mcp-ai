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
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ai.credentials import credential_display, delete_credential, is_unchanged, store_credential
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
    """
    if not base_url:
        return "local" if provider_type == ProviderType.OLLAMA.value else "external"
    host = (urlparse(base_url).hostname or "").strip()
    if host in ("localhost", "::1"):
        return "local"
    try:
        address = ipaddress.ip_address(host)
        if address.is_loopback or address.is_private:
            return "local"
    except ValueError:
        pass
    return "external"


# ── schemas ───────────────────────────────────────────────────────────────────

class ProviderIn(BaseModel):
    name: str
    provider_type: str
    base_url: str = ""
    organization_id: str | None = None
    deployment_name: str | None = None
    timeout_seconds: int = Field(default=30, ge=1, le=600)
    max_retries: int = Field(default=2, ge=0, le=10)
    #: Raising this lets SAP records reach an external provider unredacted, so it
    #: defaults off and every change is audited.
    sap_data_permitted: bool = False
    egress_class_override: str | None = None
    is_active: bool = True
    api_key: str | None = None


class ProviderUpdate(BaseModel):
    """Schema for PATCH updates; all fields are optional."""
    name: str | None = None
    provider_type: str | None = None
    base_url: str | None = None
    organization_id: str | None = None
    deployment_name: str | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=600)
    max_retries: int | None = Field(default=None, ge=0, le=10)
    sap_data_permitted: bool | None = None
    egress_class_override: str | None = None
    is_active: bool | None = None
    api_key: str | None = None


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
    if body.api_key and not is_unchanged(body.api_key):
        store_credential(provider_id, DEFAULT_TENANT, body.api_key)
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
