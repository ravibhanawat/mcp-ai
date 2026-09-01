"""
DDL for the AI configuration tables.

Follows the pattern already established in db/activity_log.py: a flat list of
idempotent statements applied at startup. The project has no migration
framework and adding one for nine tables would be a larger change than the
feature.

Two shapes are worth explaining because they differ from the requirement's
sketch:

  * `is_default` is not a column on ai_models. Defaults are pointers on the
    single ai_tenant_policy row, so setting one is an atomic UPDATE and two rows
    can never both claim to be the default.

  * Fallback chains are rows in ai_model_routing with rule_type='fallback'.
    They have the same shape as routing rules — ordered entries keyed by
    purpose — so a separate table would only duplicate the queries.
"""
from __future__ import annotations

import logging

_logger = logging.getLogger("ai.schema")

AI_TABLES: tuple[str, ...] = (
    "ai_providers",
    "ai_provider_credentials",
    "ai_models",
    "ai_model_capabilities",
    "ai_model_routing",
    "ai_tenant_models",
    "ai_tenant_policy",
    "ai_model_health",
    "ai_usage_logs",
)

AI_MIGRATION_SQL: list[str] = [
    """CREATE TABLE IF NOT EXISTS ai_providers (
        id                 VARCHAR(36)  PRIMARY KEY,
        tenant_id          VARCHAR(64)  NOT NULL DEFAULT 'default',
        name               VARCHAR(100) NOT NULL,
        provider_type      VARCHAR(20)  NOT NULL,
        base_url           TEXT         NOT NULL DEFAULT '',
        organization_id    VARCHAR(100),
        deployment_name    VARCHAR(100),
        timeout_seconds    INT          NOT NULL DEFAULT 30,
        max_retries        INT          NOT NULL DEFAULT 2,
        egress_class       VARCHAR(10)  NOT NULL DEFAULT 'external',
        sap_data_permitted BOOLEAN      NOT NULL DEFAULT FALSE,
        is_active          BOOLEAN      NOT NULL DEFAULT FALSE,
        created_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        updated_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        updated_by         VARCHAR(50)
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_prov_name ON ai_providers(tenant_id, name)",

    # Credentials are separated from ai_providers so no ordinary provider query
    # can return one, however carelessly written.
    """CREATE TABLE IF NOT EXISTS ai_provider_credentials (
        provider_id VARCHAR(36) PRIMARY KEY REFERENCES ai_providers(id) ON DELETE CASCADE,
        tenant_id   VARCHAR(64) NOT NULL DEFAULT 'default',
        ciphertext  BYTEA       NOT NULL,
        key_version INT         NOT NULL DEFAULT 1,
        last4       VARCHAR(4)  NOT NULL DEFAULT '',
        rotated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",

    """CREATE TABLE IF NOT EXISTS ai_models (
        id               VARCHAR(36)  PRIMARY KEY,
        tenant_id        VARCHAR(64)  NOT NULL DEFAULT 'default',
        provider_id      VARCHAR(36)  NOT NULL REFERENCES ai_providers(id) ON DELETE CASCADE,
        model_name       VARCHAR(100) NOT NULL,
        model_identifier VARCHAR(200) NOT NULL,
        purpose          VARCHAR(20)  NOT NULL,
        context_window   INT          NOT NULL DEFAULT 4096,
        max_tokens       INT          NOT NULL DEFAULT 1024,
        temperature      NUMERIC(3,2) NOT NULL DEFAULT 0.20,
        prompt_profile   VARCHAR(30)  NOT NULL DEFAULT 'registry_tool_json',
        is_active        BOOLEAN      NOT NULL DEFAULT FALSE,
        created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
    )""",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_model_ident
       ON ai_models(tenant_id, provider_id, model_identifier, purpose)""",
    "CREATE INDEX IF NOT EXISTS idx_ai_model_purpose ON ai_models(tenant_id, purpose, is_active)",

    """CREATE TABLE IF NOT EXISTS ai_model_capabilities (
        model_id    VARCHAR(36) NOT NULL REFERENCES ai_models(id) ON DELETE CASCADE,
        tenant_id   VARCHAR(64) NOT NULL DEFAULT 'default',
        capability  VARCHAR(30) NOT NULL,
        supported   BOOLEAN     NOT NULL DEFAULT FALSE,
        source      VARCHAR(10) NOT NULL DEFAULT 'declared',
        verified_at TIMESTAMPTZ,
        PRIMARY KEY (model_id, capability)
    )""",

    """CREATE TABLE IF NOT EXISTS ai_model_routing (
        id         VARCHAR(36) PRIMARY KEY,
        tenant_id  VARCHAR(64) NOT NULL DEFAULT 'default',
        rule_type  VARCHAR(10) NOT NULL,
        match_key  VARCHAR(50) NOT NULL,
        model_id   VARCHAR(36) NOT NULL REFERENCES ai_models(id) ON DELETE CASCADE,
        priority   INT         NOT NULL DEFAULT 100,
        is_active  BOOLEAN     NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    """CREATE INDEX IF NOT EXISTS idx_ai_routing_lookup
       ON ai_model_routing(tenant_id, rule_type, match_key, priority)""",

    """CREATE TABLE IF NOT EXISTS ai_tenant_models (
        tenant_id       VARCHAR(64) NOT NULL DEFAULT 'default',
        model_id        VARCHAR(36) NOT NULL REFERENCES ai_models(id) ON DELETE CASCADE,
        allowed         BOOLEAN     NOT NULL DEFAULT TRUE,
        user_selectable BOOLEAN     NOT NULL DEFAULT FALSE,
        PRIMARY KEY (tenant_id, model_id)
    )""",

    """CREATE TABLE IF NOT EXISTS ai_tenant_policy (
        tenant_id                  VARCHAR(64) NOT NULL DEFAULT 'default' PRIMARY KEY,
        allow_user_selection       BOOLEAN     NOT NULL DEFAULT FALSE,
        fallback_enabled           BOOLEAN     NOT NULL DEFAULT TRUE,
        default_chat_model_id      VARCHAR(36),
        default_embedding_model_id VARCHAR(36),
        default_reranker_model_id  VARCHAR(36),
        updated_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",

    """CREATE TABLE IF NOT EXISTS ai_model_health (
        model_id        VARCHAR(36) PRIMARY KEY REFERENCES ai_models(id) ON DELETE CASCADE,
        tenant_id       VARCHAR(64) NOT NULL DEFAULT 'default',
        status          VARCHAR(15) NOT NULL DEFAULT 'unknown',
        latency_ms      INT,
        checked_at      TIMESTAMPTZ,
        last_success_at TIMESTAMPTZ,
        last_error      TEXT
    )""",

    """CREATE TABLE IF NOT EXISTS ai_usage_logs (
        id                     BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        tenant_id              VARCHAR(64)  NOT NULL DEFAULT 'default',
        user_id                VARCHAR(50),
        provider_id            VARCHAR(36),
        model_id               VARCHAR(36),
        request_id             VARCHAR(36),
        purpose                VARCHAR(20),
        intent                 VARCHAR(50),
        tool_used              VARCHAR(100),
        authorization_result   VARCHAR(20),
        prompt_tokens          INT          NOT NULL DEFAULT 0,
        completion_tokens      INT          NOT NULL DEFAULT 0,
        latency_ms             INT,
        fallback_used          BOOLEAN      NOT NULL DEFAULT FALSE,
        fallback_from_model_id VARCHAR(36),
        egress_class           VARCHAR(10),
        redaction_applied      BOOLEAN      NOT NULL DEFAULT FALSE,
        status                 VARCHAR(10)  NOT NULL DEFAULT 'ok',
        error_code             VARCHAR(50),
        created_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_ai_usage_ts ON ai_usage_logs(tenant_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_ai_usage_model ON ai_usage_logs(model_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_ai_usage_fallback ON ai_usage_logs(fallback_used, created_at DESC)",
]


def run_ai_migrations() -> None:
    """Create the ai_* tables if absent. Called at server startup.

    Mirrors db.activity_log.run_migrations: a database that is not up must not
    stop the server from starting.
    """
    try:
        from db.connection import get_db
        with get_db() as conn:
            with conn.cursor() as cur:
                for ddl in AI_MIGRATION_SQL:
                    cur.execute(ddl)
        _logger.info("AI configuration migrations applied.")
    except Exception as exc:
        _logger.warning("AI migration failed (DB may not be available): %s", exc)
