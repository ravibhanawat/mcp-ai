"""
What a model can actually do.

Capabilities are declared by the administrator and then, where a probe is cheap,
verified against the model itself. Never inferred from the model's name — a
model called "llama3.2-tools" may or may not support tool calling, and guessing
wrong produces a runtime failure in front of a user.
"""
from __future__ import annotations

import logging

from ai.providers.registry import build_provider
from ai.types import Capability, Message, Purpose, ResolvedModel

_logger = logging.getLogger("ai.capabilities")

#: Sensible starting points the admin form pre-ticks. Conservative on purpose:
#: tool calling and vision are off until someone confirms them.
DEFAULT_CAPABILITIES: dict[Purpose, set[Capability]] = {
    Purpose.CHAT: {Capability.CHAT, Capability.STREAMING},
    Purpose.REASONING: {Capability.CHAT, Capability.STREAMING},
    Purpose.TOOL_CALLING: {Capability.CHAT, Capability.TOOL_CALLING},
    Purpose.EMBEDDING: {Capability.EMBEDDING},
    Purpose.RERANKING: {Capability.EMBEDDING},
    Purpose.CLASSIFICATION: {Capability.CHAT},
    Purpose.SUMMARIZATION: {Capability.CHAT},
}


def _execute(sql: str, params: tuple, conn=None) -> int:
    from db.connection import execute
    return execute(sql, params, conn=conn)


def set_capabilities(
    model_id: str, tenant_id: str, caps: dict[Capability, bool], source: str = "declared",
    conn=None,
) -> None:
    """Replace the capability records for a model.

    `conn`, when given, runs every insert on that connection instead of a
    fresh pooled one per call — ai.seed uses this so a model's capability rows
    commit or roll back atomically with the provider/model rows they reference
    (ai_model_capabilities.model_id is a foreign key to ai_models.id, so
    writing it on a *different*, already-committed connection while the model
    row is still part of an open transaction elsewhere would fail outright).
    """
    for capability, supported in caps.items():
        _execute(
            """INSERT INTO ai_model_capabilities
                   (model_id, tenant_id, capability, supported, source, verified_at)
               VALUES (%s, %s, %s, %s, %s, NOW())
               ON CONFLICT (model_id, capability) DO UPDATE SET
                   supported   = EXCLUDED.supported,
                   source      = EXCLUDED.source,
                   verified_at = NOW()""",
            (model_id, tenant_id, capability.value, supported, source),
            conn=conn,
        )


def probe_capabilities(resolved: ResolvedModel, api_key: str | None) -> dict[Capability, bool]:
    """Verify the capabilities that can be checked with one cheap request each.

    Only CHAT, TOOL_CALLING and EMBEDDING are probed. VISION would need an image
    payload and STRUCTURED_OUTPUT a schema round-trip; both stay declared-only
    until something needs them.
    """
    provider = build_provider(resolved.provider, api_key)
    model = resolved.model
    out: dict[Capability, bool] = {}

    try:
        provider.chat(model, [Message(role="user", content="ping")], max_tokens=1)
        out[Capability.CHAT] = True
    except Exception:
        out[Capability.CHAT] = False

    if Capability.TOOL_CALLING in resolved.capabilities:
        probe_tool = [{
            "type": "function",
            "function": {
                "name": "probe", "description": "capability probe",
                "parameters": {"type": "object", "properties": {}},
            },
        }]
        try:
            provider.chat(model, [Message(role="user", content="ping")],
                          tools=probe_tool, max_tokens=1)
            out[Capability.TOOL_CALLING] = True
        except Exception:
            out[Capability.TOOL_CALLING] = False

    if Capability.EMBEDDING in resolved.capabilities:
        try:
            provider.embed(model, ["probe"])
            out[Capability.EMBEDDING] = True
        except Exception:
            out[Capability.EMBEDDING] = False

    return out
