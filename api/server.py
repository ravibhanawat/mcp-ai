"""
DeepResearch AI - REST API Server
Run: uvicorn api.server:app --reload --port 8000

Enterprise security hardening:
  - JWT authentication (1-hour access tokens + refresh token rotation)
  - Refresh token endpoint for seamless token renewal
  - Role-based access control (RBAC) per SAP module
  - SOX/GDPR-compliant audit logging (PII-redacted, 90-day retention)
  - Rate limiting: 30 req/min per IP on all chat endpoints
  - Per-session agent instances (no cross-user conversation leakage)
  - CORS restricted to explicitly configured origins
  - DISABLE_AUTH only permitted when APP_ENV=development
  - Startup validation: fatal errors if required env vars are absent in production
  - Generic error messages to clients; full tracebacks only in server logs
  - Default bind: 127.0.0.1 (override via HOST env var)
"""
import contextlib
import contextvars
import hashlib
import logging
import os
import secrets
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime
from threading import Lock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env file if present (local development convenience)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from typing import Any

from agent.sap_agent import SAPAgent, _DecimalEncoder as _JsonEncoder
from ai.errors import AIError
from tools.tool_registry import TOOLS, get_sap_source
from core.config_manager import config
from core.audit_logger import get_recent_logs, list_log_files, log_request
from auth.jwt_handler import (
    create_token, create_refresh_token,
    decode_token, decode_refresh_token,
    is_dev_secret,
)
from auth.rbac import ALL_ROLES, check_tool_access, get_allowed_tools
from auth import users as user_store
from api.oauth import router as _oauth_router, verify_mcp_token
from api.deps import get_current_user, require_admin, _AUTH_ENABLED
import jwt as _jwt
import json

# Chat history persistence (gracefully degrades if DB is unavailable)
try:
    from db.chat_history import (
        get_or_create_conversation,
        save_message as _save_msg,
        list_conversations as _list_conversations,
        get_messages as _get_messages,
        delete_conversation as _delete_conversation,
        clear_messages as _clear_messages,
        async_get_or_create_conversation as _async_get_or_create_conv,
        async_save_message as _async_save_msg,
    )
    _HISTORY_ENABLED = True
except Exception as _hist_err:
    _HISTORY_ENABLED = False

# Activity / audit log (DB-backed, gracefully degrades)
try:
    from db.activity_log import (
        write_log as _write_activity,
        query_logs as _query_activity,
        count_logs as _count_activity,
        get_stats  as _activity_stats,
        run_migrations as _run_migrations,
    )
    _ACTIVITY_DB = True
except Exception:
    _ACTIVITY_DB = False
    def _run_migrations(): pass

logging.basicConfig(level=logging.INFO)
_logger = logging.getLogger("api.server")

# ── Environment & security constants ─────────────────────────────────────────
_APP_ENV = os.environ.get("APP_ENV", "development").lower()
_IS_DEV  = _APP_ENV == "development"

# ── DISABLE_AUTH: only permitted in development ────────────────────────────────
# The production guard and _AUTH_ENABLED computation are now in api/deps.py to
# ensure they are the single source of truth. api/server.py imports _AUTH_ENABLED
# from there so edits to either location do not silently diverge.

# ── CORS ───────────────────────────────────────────────────────────────────────
_cors_raw = os.environ.get("CORS_ORIGINS", "").strip()
if not _cors_raw:
    if _IS_DEV:
        _allowed_origins = ["http://localhost:5173", "http://localhost:3000", "http://localhost:4173"]
    else:
        print(
            "FATAL: CORS_ORIGINS env var is required in non-development environments. "
            "Example: CORS_ORIGINS=https://sap-agent.mycompany.com",
            file=sys.stderr,
        )
        sys.exit(1)
else:
    _allowed_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]
    if "*" in _allowed_origins and not _IS_DEV:
        # Starlette reflects the request Origin (rather than sending "*") when
        # allow_credentials=True, so a wildcard here accepts every origin.
        print(
            "FATAL: CORS_ORIGINS=* is not permitted outside development. "
            "With allow_credentials=True the middleware reflects any origin. "
            "List your real origins, e.g. CORS_ORIGINS=https://sap-agent.example.com",
            file=sys.stderr,
        )
        sys.exit(1)


# ── Startup checks ─────────────────────────────────────────────────────────────
def _startup_checks() -> None:
    if not _IS_DEV:
        errors = []
        if not os.environ.get("JWT_SECRET_KEY"):
            errors.append("JWT_SECRET_KEY must be set in non-development environments.")
        if not os.environ.get("JWT_REFRESH_SECRET"):
            errors.append("JWT_REFRESH_SECRET must be set in non-development environments.")
        from core.scoping import startup_report, tenancy_model, TENANCY_COLUMN
        report = startup_report()
        if report["unenforceable"]:
            errors.append(
                f"RECORD_SCOPING=owner but these tables have no owner column and "
                f"would return all rows: {', '.join(report['unenforceable'])}. "
                f"Run scripts/add_row_scoping.sql and backfill before enabling."
            )
        published = user_store.uses_published_credentials()
        if published:
            errors.append(
                f"These accounts still use passwords published in this repository: "
                f"{', '.join(published)}. Run scripts/setup_admin.py to set new ones."
            )
        if errors:
            for e in errors:
                print(f"FATAL: {e}", file=sys.stderr)
            sys.exit(1)
        _logger.info("Row-scoping posture: %s", report)
    else:
        from core.scoping import startup_report as _sr
        _logger.info("Row-scoping posture: %s", _sr())
        if is_dev_secret():
            _logger.warning(
                "Running with insecure dev JWT secret. "
                "Set JWT_SECRET_KEY before deploying to production."
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _startup_checks()
    import asyncio as _aio
    try:
        await _aio.wait_for(_aio.to_thread(_run_migrations), timeout=5.0)
        from ai.schema import run_ai_migrations as _run_ai_migrations
        await _aio.wait_for(_aio.to_thread(_run_ai_migrations), timeout=5.0)
        from ai.seed import seed_from_existing_config as _seed_ai
        await _aio.wait_for(_aio.to_thread(_seed_ai), timeout=10.0)
    except Exception as _mig_exc:
        # Broad on purpose: run_ai_migrations() already swallows every exception
        # itself (a warning, not a raise), but seed_from_existing_config() does
        # not — it runs a real SELECT COUNT(*) against ai_providers, which
        # raises UndefinedTable when the migration above never actually ran
        # (e.g. Postgres was down). Catching only TimeoutError let that escape
        # lifespan and kill the whole process on a database that "must not stop
        # the server from starting", per this same block's own migration step.
        _logger.warning(
            "DB migration/seed step failed or timed out at startup — DB may not "
            "be available: %s", _mig_exc,
        )
    # Open async PostgreSQL pool (used by streaming event_generator)
    # Hard 5-second timeout so a missing DB never stalls server startup.
    _async_pool_closer = None
    try:
        from db.connection import open_async_pool, close_async_pool
        await _aio.wait_for(open_async_pool(), timeout=5.0)
        _async_pool_closer = close_async_pool
    except _aio.TimeoutError:
        _logger.warning("Async DB pool timed out during startup — streaming DB writes disabled.")
    except Exception as _e:
        _logger.warning("Async DB pool failed to open (streaming DB writes disabled): %s", _e)
    yield
    if _async_pool_closer:
        try:
            await _async_pool_closer()
        except Exception:
            pass


# ── FastAPI app ────────────────────────────────────────────────────────────────
app = FastAPI(
    title="DeepResearch AI API",
    description="Natural language interface to SAP ERP modules",
    version="4.0.0",
    lifespan=lifespan,
)

# Mount OAuth 2.1 endpoints (RFC 9728, RFC 8414, RFC 7591, PKCE)
app.include_router(_oauth_router)

# Mount AI provider administration endpoints
from api.routes_ai_admin import router as _ai_admin_router, user_router as _ai_user_router
app.include_router(_ai_admin_router)
app.include_router(_ai_user_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-MCP-Key"],
)

# ── Activity logging middleware (logs EVERY request to DB) ─────────────────────
from starlette.middleware.base import BaseHTTPMiddleware
import uuid as _uuid

# Endpoints whose detailed info is already captured by log_request() (audit source).
# Middleware still logs them but marks them 'middleware' so they don't duplicate.
_AUDIT_ENDPOINTS = {"/chat", "/research", "/autonomous", "/chat/stream"}


class _ActivityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.monotonic()
        rid   = str(_uuid.uuid4())
        request.state.request_id = rid

        response    = None
        status_code = 500
        error_msg   = None
        try:
            response    = await call_next(request)
            status_code = response.status_code
        except Exception as exc:
            error_msg = str(exc)
            raise
        finally:
            if _ACTIVITY_DB:
                duration = int((time.monotonic() - start) * 1000)
                path = request.url.path

                # Skip endpoints handled with full detail by log_request()
                # (they already dual-write via audit_logger)
                if not any(path.startswith(ep) for ep in _AUDIT_ENDPOINTS):
                    user_id = None
                    try:
                        from auth.jwt_handler import decode_token as _dt
                        auth = request.headers.get("Authorization", "")
                        if auth.startswith("Bearer "):
                            payload = _dt(auth[7:])
                            user_id = payload.get("sub")
                    except Exception:
                        pass

                    client_ip = _client_ip(request)

                    # _write_activity is a *synchronous* psycopg call. Awaiting
                    # it on the event loop — which is what calling it directly
                    # from this async method did — blocked the whole worker for
                    # as long as the pool took to hand over a connection. With
                    # the database unreachable that was the pool's full acquire
                    # timeout, on every request, so a database outage became a
                    # total outage: /health and / stopped answering too, and the
                    # process no longer responded to SIGTERM.
                    #
                    # to_thread keeps it off the loop; the shield-free await
                    # still lets a caller disconnect without stranding the
                    # write. Activity logging is best-effort, so a failure here
                    # is logged and swallowed rather than raised into a
                    # response that has already been produced.
                    import asyncio as _aio
                    try:
                        await _aio.to_thread(
                            _write_activity,
                            request_id=rid,
                            user_id=user_id,
                            client_ip=client_ip,
                            method=request.method,
                            endpoint=path,
                            status_code=status_code,
                            status="error" if (error_msg or status_code >= 400) else "ok",
                            duration_ms=duration,
                            error_message=error_msg,
                            log_source="middleware",
                        )
                    except Exception as _log_exc:
                        _logger.warning(
                            "Activity log write failed for %s %s: %s",
                            request.method, path, _log_exc,
                        )
        return response


class _SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline transport and content hardening on every response (finding F-09).

    HSTS is only meaningful over TLS, so it is emitted outside development where
    a TLS-terminating proxy is expected.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        # The API serves JSON, not markup, so it can afford a strict policy:
        # nothing loads, nothing frames it, nothing is posted anywhere. This is
        # the layer that contains an injected-content bug rather than relying on
        # every renderer downstream being careful for ever.
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; "
            "form-action 'none'",
        )
        if not _IS_DEV:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response


app.add_middleware(_SecurityHeadersMiddleware)
app.add_middleware(_ActivityMiddleware)

# ── Rate limiting ──────────────────────────────────────────────────────────────
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Peers whose X-Forwarded-For header we believe. Anything else is spoofable:
# the header is client-controlled, so trusting it unconditionally let a caller
# reset the rate-limit counter every request (finding F-08).
_TRUSTED_PROXIES: frozenset[str] = frozenset(
    p.strip() for p in os.environ.get("TRUSTED_PROXY_IPS", "").split(",") if p.strip()
)


def _client_ip(request: Request) -> str:
    """The caller's IP, honouring X-Forwarded-For only from a trusted proxy."""
    peer = request.client.host if request.client else "unknown"
    if peer in _TRUSTED_PROXIES:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return peer


def _get_rate_limit_key(request: Request) -> str:
    """Rate-limit bucket: the authenticated user when known, else the client IP.

    Keying on identity means a shared NAT egress cannot be used to exhaust
    another tenant's budget, and a single account cannot multiply its budget by
    rotating headers.
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            return f"user:{decode_token(auth[7:])['sub']}"
        except Exception:
            pass
    return f"ip:{_client_ip(request)}"

limiter = Limiter(key_func=_get_rate_limit_key)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── Per-session agent pool ─────────────────────────────────────────────────────
_MAX_SESSIONS  = 500          # evict oldest when pool exceeds this
_session_agents: dict[str, SAPAgent] = {}
_session_order: list[str] = []   # insertion order for eviction
_session_lock  = Lock()

def _agent_key(user_id: str, session_id: str) -> str:
    """The one place a session-pool key is built.

    Every caller must agree on this. /chat composed it inline while
    DELETE /conversations used the bare session_id, so the delete never
    matched and a conversation's transcript outlived its deletion.
    """
    return f"{user_id}:{session_id}"


def _make_agent() -> SAPAgent:
    return SAPAgent(tenant_id="default")


def _get_agent(session_id: str) -> SAPAgent:
    """Return (or create) the agent for a session. Evicts oldest if pool is full.
    Lock hold-time is now O(1) since MLX probe is cached at startup."""
    if session_id in _session_agents:   # fast path — no lock needed for read check
        return _session_agents[session_id]
    with _session_lock:
        # Re-check inside lock (double-checked locking pattern)
        if session_id not in _session_agents:
            if len(_session_agents) >= _MAX_SESSIONS:
                oldest = _session_order.pop(0)
                _session_agents.pop(oldest, None)
            _session_agents[session_id] = _make_agent()
            _session_order.append(session_id)
        return _session_agents[session_id]


def _clear_all_sessions() -> None:
    with _session_lock:
        _session_agents.clear()
        _session_order.clear()


# ── Auth bearer ────────────────────────────────────────────────────────────────
# get_current_user and require_admin are now in api/deps.py (extracted so
# route modules can import them without circular imports)


# ── Pydantic models ────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    # Length caps keep a single request from occupying a worker (finding F-10)
    # and bound every downstream regex, LLM call and log write.
    message: str = Field(..., max_length=8000)
    # An id from GET /ai/models/available, not a free-text model name. The
    # router validates it against the tenant allowlist and ignores it when user
    # selection is disabled, so a client cannot reach an unoffered model.
    model_id: str | None = Field(None, max_length=36)
    session_id: str = Field("default", max_length=200)
    clarification_answer: str | None = Field(None, max_length=2000)
    confirm_token: str | None = Field(None, max_length=256)   # confirms a pending write
    ticket_status: str | None = None   # Kutty ticket-backlog status filter (UI dropdown)

class ChatResponse(BaseModel):
    response: str
    tool_called: str | None = None
    tool_result: dict | None = None
    action_plan: dict | None = None
    sap_source: dict | None = None
    request_id: str | None = None
    status: str = "ok"
    pending_action: dict | None = None   # write awaiting confirmation
    confirm_token: str | None = None     # replay this to execute the pending action
    report: dict | None = None      # inline chart/table widget payload
    abap_check: dict | None = None  # inline ABAP code review widget payload
    abap_code: dict | None = None   # inline ABAP code generation widget payload

class KuttyAskRequest(BaseModel):
    query: str = Field(..., max_length=4000)
    k: int = Field(8, ge=1, le=50)
    status: str | None = None   # optional status filter (open/completed/wip/…)

class KuttyAskResponse(BaseModel):
    answer: str
    tickets: list[dict] = []
    status: str = "ok"

class ResearchRequest(BaseModel):
    query: str = Field(..., max_length=4000)

class ResearchResponse(BaseModel):
    report: str
    anomalies: list[dict] = []
    tools_used: list[str] = []
    sap_sources: list[str] = []
    entity_type: str | None = None
    entity_id: str | None = None
    duration_ms: int = 0
    request_id: str | None = None
    success: bool = True

class AutonomousRequest(BaseModel):
    query: str = Field(..., max_length=4000)

class AutonomousResponse(BaseModel):
    report: str
    reasoning: str = ""
    tool_calls: list[dict] = []
    tools_used: list[str] = []
    iterations: int = 0
    duration_ms: int = 0
    request_id: str | None = None
    success: bool = True

class ConfigPatch(BaseModel):
    sap: dict[str, Any] | None = None
    mcp: dict[str, Any] | None = None
    ollama: dict[str, Any] | None = None

class MCPServer(BaseModel):
    name: str
    url: str
    transport: str = "sse"
    enabled: bool = True

class LoginRequest(BaseModel):
    user_id: str
    password: str

class RefreshRequest(BaseModel):
    refresh_token: str

class CreateUserRequest(BaseModel):
    user_id: str
    password: str
    full_name: str
    email: str
    roles: list[str]

class UpdatePasswordRequest(BaseModel):
    new_password: str


# ── Auth endpoints ─────────────────────────────────────────────────────────────

@app.post("/auth/login")
def login(body: LoginRequest):
    """Authenticate and receive access + refresh JWT tokens."""
    # Check lockout before authenticate() to give a clear message
    if user_store._is_locked(body.user_id):
        raise HTTPException(
            status_code=429,
            detail="Account temporarily locked due to too many failed attempts. Try again in 15 minutes.",
        )
    user = user_store.authenticate(body.user_id, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials.")
    access_tok  = create_token(user["user_id"], user["roles"])
    refresh_tok = create_refresh_token(user["user_id"])
    # Register this session's refresh token so /auth/refresh can tell a live
    # token from one it has already rotated away.
    user_store.record_refresh_jti(
        user["user_id"], _jwt.decode(refresh_tok, options={"verify_signature": False})["jti"]
    )
    response = {
        "access_token":  access_tok,
        "refresh_token": refresh_tok,
        "token_type":    "bearer",
        "user_id":       user["user_id"],
        "roles":         user["roles"],
        "full_name":     user.get("full_name"),
    }
    # Only surface the dev-secret warning in development environments
    if _IS_DEV and is_dev_secret():
        response["warning"] = "Insecure dev secret key in use — set JWT_SECRET_KEY env var"
    return response


@app.post("/auth/refresh")
def refresh_token_endpoint(body: RefreshRequest):
    """Exchange a valid refresh token for a new access token + rotated refresh token."""
    try:
        payload     = decode_refresh_token(body.refresh_token)
        user        = user_store.get_user(payload["sub"])
        if not user or not user.get("active", True):
            raise HTTPException(status_code=401, detail="User not found or inactive.")

        new_refresh = create_refresh_token(user["user_id"])
        new_jti     = _jwt.decode(new_refresh, options={"verify_signature": False})["jti"]

        # Rotation only contains a stolen token if the token it replaces stops
        # working. Previously both remained valid, so a captured refresh token
        # was good for its full lifetime and reuse of a superseded one — the
        # canonical theft signal — was invisible.
        if not user_store.rotate_refresh_jti(user["user_id"], payload["jti"], new_jti):
            user_store.revoke_all_refresh_tokens(user["user_id"])
            _logger.warning(
                "Refresh token replay for user %s — every refresh token for "
                "this account has been revoked.", user["user_id"],
            )
            raise HTTPException(
                status_code=401,
                detail="This refresh token has already been used. All sessions "
                       "have been signed out; please log in again.",
            )

        new_access  = create_token(user["user_id"], user["roles"])
        return {
            "access_token":  new_access,
            "refresh_token": new_refresh,
            "token_type":    "bearer",
        }
    except HTTPException:
        raise
    except _jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Refresh token expired. Please log in again.")
    except _jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid refresh token.")


@app.get("/auth/me")
def me(current_user: dict = Depends(get_current_user)):
    """Return the current authenticated user's profile."""
    user = user_store.get_user(current_user["user_id"])
    if not user:
        return current_user
    from auth.rbac import ROLE_MODULES
    # Only this caller's modules. Returning the union of every role's modules
    # misreports the user's access and becomes an access-control defect the
    # moment a client uses it for menu gating (finding F-04).
    my_modules = sorted({m for r in user.get("roles", []) for m in ROLE_MODULES.get(r, [])})
    return {**user, "allowed_modules": my_modules}


@app.get("/auth/users")
def list_users(admin: dict = Depends(require_admin)):
    """List all users (admin only)."""
    return {"users": user_store.list_users()}


@app.post("/auth/users")
def create_user(body: CreateUserRequest, admin: dict = Depends(require_admin)):
    """Create a new user account (admin only). Automatically generates an MCP API key."""
    try:
        new_user = user_store.create_user(
            body.user_id, body.password, body.full_name, body.email, body.roles
        )
        # Auto-generate MCP key so the user has zero manual setup
        mcp_raw  = "mcp_" + secrets.token_hex(24)
        keys     = _load_mcp_keys()
        label    = f"user:{body.user_id}"
        keys[label] = _hash_key(mcp_raw)
        _save_mcp_keys(keys)
        return {"status": "ok", "user": new_user, "mcp_key": mcp_raw}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/auth/users/{user_id}/password")
def update_password(
    user_id: str,
    body: UpdatePasswordRequest,
    admin: dict = Depends(require_admin),
):
    """Reset a user's password (admin only)."""
    try:
        user_store.update_password(user_id, body.new_password)
        return {"status": "ok", "message": f"Password updated for '{user_id}'"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.patch("/auth/users/{user_id}/deactivate")
def deactivate_user(user_id: str, admin: dict = Depends(require_admin)):
    """Deactivate a user account and revoke their MCP key (admin only)."""
    try:
        user_store.set_active(user_id, False)
        # "No lingering access" means every credential, not just the MCP key:
        # the refresh tokens go too, and get_current_user re-checks `active` on
        # every request so the access token already issued stops working now
        # rather than whenever it happens to expire.
        user_store.revoke_all_refresh_tokens(user_id)
        # Revoke MCP key automatically — no lingering access
        keys  = _load_mcp_keys()
        label = f"user:{user_id}"
        if label in keys:
            del keys[label]
            _save_mcp_keys(keys)
        return {"status": "ok", "message": f"User '{user_id}' deactivated and MCP access revoked"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


_MCP_INSTRUCTIONS = [
    "1. Open: ~/Library/Application Support/Claude/claude_desktop_config.json",
    "2. Merge the 'mcpServers' block into that file.",
    "3. Fully quit and reopen Claude Desktop (Cmd+Q).",
    "4. Click the hammer icon in Claude Desktop chat — SAP tools will appear.",
]


def _mcp_setup_payload(user_id: str, *, rotate: bool) -> dict:
    """Build a Claude Desktop config, minting a key only when asked to.

    Only the key's hash is stored, so an existing key can never be shown
    again — the page can either display a key or preserve the one already in
    use, not both. Reading used to silently choose "display", which meant a
    refresh, a back-button or a browser prefetch revoked the key the user had
    just finished pasting into Claude Desktop, with nothing to indicate it had
    happened. Reading now preserves; rotating is an explicit POST.
    """
    keys    = _load_mcp_keys()
    label   = f"user:{user_id}"
    existed = label in keys
    mcp_raw = None
    if rotate or not existed:
        mcp_raw     = "mcp_" + secrets.token_hex(24)
        keys[label] = _hash_key(mcp_raw)
        _save_mcp_keys(keys)

    server_url = os.environ.get("SERVER_URL", "http://localhost:8000").rstrip("/")
    headers    = {"X-MCP-Key": mcp_raw or "<your existing key>"}
    return {
        "user_id":    user_id,
        "mcp_key":    mcp_raw,
        "has_key":    existed or mcp_raw is not None,
        "rotated":    rotate and existed,
        "server_url": server_url,
        "claude_desktop_config": {
            "mcpServers": {"sap-ai-agent": {"url": f"{server_url}/mcp/sse",
                                            "headers": headers}}
        },
        "message": (
            "A new key was generated. The previous one no longer works."
            if rotate and existed else
            "Your key is stored as a hash and cannot be shown again. "
            "Generate a new one if you have lost it."
            if mcp_raw is None else
            "This is your MCP key. Copy it now — it cannot be shown again."
        ),
        "instructions": _MCP_INSTRUCTIONS,
    }


@app.get("/auth/users/{user_id}/mcp-setup")
def get_user_mcp_setup(user_id: str, admin: dict = Depends(require_admin)):
    """Show a user's Claude Desktop config, without disturbing their key."""
    return _mcp_setup_payload(user_id, rotate=False)


@app.post("/auth/users/{user_id}/mcp-setup")
def rotate_user_mcp_key(user_id: str, admin: dict = Depends(require_admin)):
    """Issue a new MCP key for a user. Revokes the previous one."""
    return _mcp_setup_payload(user_id, rotate=True)


@app.get("/mcp/my-setup")
def get_my_mcp_setup(current_user: dict = Depends(get_current_user)):
    """Self-service: your own Claude Desktop config. Does not touch your key."""
    return _mcp_setup_payload(current_user["user_id"], rotate=False)


@app.post("/mcp/my-setup")
def rotate_my_mcp_key(current_user: dict = Depends(get_current_user)):
    """Issue yourself a new MCP key. Revokes the previous one."""
    return _mcp_setup_payload(current_user["user_id"], rotate=True)


def _resolve_chat_model_or_503(agent, model_id: str | None):
    """Resolve the model for a chat request, translating a resolution failure
    into a 503 an operator can act on.

    `resolve_only` can raise `AIError` for reasons that have nothing to do with
    a database outage (no model configured, the requested model not
    authorized, ...), but it can also surface a `ConfigStore` failure — and
    with PostgreSQL down this is the one call on the request path most likely
    to hit that. Before AI provider configuration existed the agent talked to
    Ollama directly, so a database outage never touched chat at all; letting
    this raise unhandled here would turn that into an unstyled 500 and a real
    regression. 503 (not 500) tells a caller — and a monitoring dashboard —
    that the service is transiently unavailable, not broken.

    Two failure shapes, two branches: `AIError` is a configuration-layer
    decision (no model, unauthorized, capability gap) and gets its specific,
    actionable message. Everything else — `psycopg.OperationalError`,
    `psycopg_pool.PoolTimeout`, or any other exception `resolve_only` did not
    wrap — is an unexpected failure of the ConfigStore itself. `get_store()`'s
    boot-time probe only proves PostgreSQL was reachable at process start; an
    outage that begins later, once the store's 30s cache expires, raises a
    raw driver exception here, on the request path, not at boot. Both
    branches still answer 503, not 500 — the caller only needs to know
    "try again later", and an operator gets the exception type at ERROR to
    tell a misconfiguration from a genuine outage.
    """
    from ai.errors import AIError
    from ai.types import Purpose
    try:
        return agent.manager.resolve_only(
            tenant_id="default", purpose=Purpose.CHAT, requested_model_id=model_id
        )
    except AIError as exc:
        _logger.warning("Model resolution failed for chat: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=(
                "No AI model could be resolved right now. This usually means the "
                "AI configuration database is unreachable or no chat model is "
                "configured yet. Contact your administrator; this is not caused "
                "by your request."
            ),
        )
    except Exception as exc:
        _logger.error(
            "Unexpected error resolving the chat model (%s: %s). Treating as a "
            "configuration store outage rather than letting it 500.",
            type(exc).__name__, exc,
        )
        raise HTTPException(
            status_code=503,
            detail=(
                "The AI configuration store is temporarily unavailable. This is "
                "usually a database connectivity issue; contact your "
                "administrator if it persists."
            ),
        )


# ── Core chat endpoint ─────────────────────────────────────────────────────────

@app.post("/chat", response_model=ChatResponse)
@limiter.limit("30/minute")
async def chat(
    request: Request,
    body: ChatRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Main chat endpoint.
    - RBAC: tool calls blocked if user lacks module access.
    - Per-session agent (no cross-user conversation leak).
    - Audit log written for every request (PII-redacted).
    - SAP source attribution returned with every tool result.
    """
    user_id    = current_user["user_id"]
    user_roles = current_user.get("roles", [])
    client_ip  = request.client.host if request.client else "unknown"

    # ── Resolve the model through the router (applies policy gate) ──
    agent_session_id = _agent_key(user_id, body.session_id)
    import asyncio as _aio
    agent = await _aio.to_thread(_get_agent, agent_session_id)
    agent.requested_model_id = body.model_id
    resolution = _resolve_chat_model_or_503(agent, body.model_id)
    resolved_model_id = resolution.resolved.model.id

    # ── Cache lookup (per-user; skipped for clarification follow-ups) ──
    from core import redis_cache
    from core.security import redact_secrets, classify_for_cache
    _cache_key = redis_cache.make_key("chat", body.message, resolved_model_id, ",".join(sorted(user_roles)))
    if not body.clarification_answer:
        _cached = redis_cache.get("chat", user_id, _cache_key)
        if _cached:
            return ChatResponse(**_cached)

    t_start       = time.monotonic()
    tool_called   = None
    tool_result   = None
    action_plan   = None
    sap_source    = None
    response_text = ""
    err_status    = "ok"
    rid           = None
    report_payload = None
    abap_check_payload = None
    abap_code_payload = None

    # ── ABAP code generation — detect "Generate ABAP code for:" prefix ──────────
    import re as _re
    _gen_match = _re.match(r'(?i)generate\s+abap\s+code\s+for\s*:\s*(.+)', body.message.strip(), _re.DOTALL)
    if _gen_match:
        _gen_description = _gen_match.group(1).strip()
        try:
            from modules.abap import generate_abap_code
            abap_code_payload = await _aio.to_thread(generate_abap_code, _gen_description)
            tool_called = "generate_abap_code"
            code_type = abap_code_payload.get("code_type", "ABAP Code")
            response_text = (
                f"**Generated ABAP Code — {code_type}**\n\n"
                f"Here is the generated ABAP code for: *{_gen_description}*\n\n"
                f"See the code panel below. Copy it and paste into SE38."
            )
        except Exception:
            logger.exception("ABAP code generation failed")
            abap_code_payload = None

    # ── ABAP code check — detect fenced ```abap blocks or explicit check intent ─
    _abap_fence = _re.search(r'```abap\s*([\s\S]+?)```', body.message, _re.IGNORECASE)
    _check_intent = any(kw in body.message.lower() for kw in
                        ["check this", "check code", "analyze code", "review code",
                         "code review", "syntax check", "check abap", "analyse code"])
    if not abap_code_payload and (_abap_fence or _check_intent):
        _code_to_check = _abap_fence.group(1).strip() if _abap_fence else None
        if not _code_to_check:
            # Try to extract a bare code block (no fence) if the message looks like code
            _lines = body.message.strip().splitlines()
            _code_lines = [l for l in _lines if re.match(
                r'^\s*(DATA|SELECT|LOOP|IF|FORM|METHOD|REPORT|TABLES|CALL|ENDLOOP|ENDIF|ENDFORM|ENDMETHOD)\b',
                l, re.IGNORECASE)]
            if len(_code_lines) >= 2:
                _code_to_check = body.message.strip()
        if _code_to_check:
            try:
                from modules.abap import analyze_abap_syntax
                abap_check_payload = await _aio.to_thread(analyze_abap_syntax, _code_to_check)
                abap_check_payload["code"] = _code_to_check
                tool_called = "analyze_abap_syntax"
                score = abap_check_payload.get("quality_score", 0)
                rating = abap_check_payload.get("rating", "")
                ec = abap_check_payload.get("error_count", 0)
                wc = abap_check_payload.get("warning_count", 0)
                sc = abap_check_payload.get("suggestion_count", 0)
                response_text = (
                    f"**ABAP Code Review — {rating}** (Quality score: {score}/100)\n\n"
                    f"Found **{ec} error(s)**, **{wc} warning(s)**, **{sc} suggestion(s)** "
                    f"across {abap_check_payload.get('lines_analyzed', 0)} lines. "
                    f"See the review panel below."
                )
            except Exception:
                logger.exception("ABAP syntax check failed")
                abap_check_payload = None

    # ── Report / visualization intent ─────────────────────────────────────────
    from agent.report_agent import (is_report_query, generate as gen_report,
                                    reply_text as report_reply, is_access_denied)
    if is_report_query(body.message):
        try:
            # The report agent reaches SAP data directly, so it gets the same
            # allow-list the tool path gets. Without this, asking for a "chart"
            # bypasses RBAC entirely.
            report_payload = await _aio.to_thread(
                gen_report, body.message,
                get_allowed_tools(user_roles) if _AUTH_ENABLED else None,
            )
            if is_access_denied(report_payload):
                raise HTTPException(
                    status_code=403,
                    detail="Access denied: your role does not permit reporting on "
                           "this data. Contact your SAP administrator to request access.",
                )
            if report_payload:
                response_text = report_reply(body.message, report_payload)
                tool_called   = "report_agent"
        except HTTPException:
            raise
        except Exception:
            logger.exception("Report agent failed; falling back to normal chat")
            report_payload = None

    from core.authorization import execution_context

    def _run_agent():
        # Binds the acting user so execute_tool() can enforce the confirmation
        # gate on destructive actions, below the model.
        with execution_context(user_id=user_id, confirm_token=body.confirm_token,
                               enforce=_AUTH_ENABLED):
            return agent.chat(
                body.message,
                get_allowed_tools(user_roles) if _AUTH_ENABLED else None,
                body.ticket_status,
            )

    try:
        if not report_payload and not abap_check_payload and not abap_code_payload:
            response_text, tool_called, tool_result = await _aio.to_thread(_run_agent)

        if tool_called in ("action_plan", "autonomous_agent", "auto_research", "report_agent", "analyze_abap_syntax", "generate_abap_code") and isinstance(tool_result, dict):
            action_plan = tool_result if tool_called == "action_plan" else None
            tool_result = None

        if (
            tool_called
            and tool_called not in ("action_plan", "autonomous_agent", "auto_research",
                                    "report_agent", "analyze_abap_syntax", "generate_abap_code")
            and _AUTH_ENABLED
            and not check_tool_access(tool_called, user_roles)
        ):
            raise HTTPException(
                status_code=403,
                detail=f"Access denied: your role does not permit '{tool_called}'. "
                       f"Contact your SAP administrator to request access.",
            )

        if tool_result:
            sap_source = tool_result.get("sap_source") or get_sap_source(tool_called or "")

    except HTTPException:
        raise
    except AIError as exc:
        # Every model in the fallback chain failed. That is the AI service
        # being unavailable, not this server being broken, and answering 500
        # told the user "internal error" while telling a dashboard nothing
        # actionable. _resolve_chat_model_or_503 already draws this
        # distinction for *resolution* failures; dispatch failures get the
        # same treatment. The provider's own message is logged but not
        # returned — it carries endpoint URLs and credential detail.
        err_status = "error"
        _logger.error(
            "All AI providers failed for user %s (%s: %s)", user_id, exc.code, exc
        )
        raise HTTPException(
            status_code=503,
            detail="No AI model is currently able to answer. Every configured "
                   "provider failed. Contact your administrator; this is not "
                   "caused by your request.",
        )
    except Exception:
        err_status = "error"
        _logger.exception("Unhandled error in /chat for user %s", user_id)
        raise HTTPException(status_code=500, detail="An internal error occurred. Contact your administrator.")
    finally:
        duration_ms = int((time.monotonic() - t_start) * 1000)
        rid = log_request(
            user_id=user_id,
            user_roles=user_roles,
            client_ip=client_ip,
            endpoint="/chat",
            query=body.message,
            tool_called=tool_called,
            tool_parameters={k: v for k, v in (tool_result or {}).items()
                             if k not in ("sap_source",)} if tool_called else None,
            sap_source=sap_source,
            response_text=response_text,
            duration_ms=duration_ms,
            status=err_status,
        )

    # ── Field-level masking ─────────────────────────────────────────────────────
    # Module access grants rows, not every column. Applied before the result is
    # cached, logged or returned.
    if _AUTH_ENABLED:
        from core.authorization import mask_fields
        tool_result = mask_fields(tool_result, user_roles)

    # ── Outbound secret/PII redaction (defense-in-depth) ─────────────────────────
    # The local model's answer is returned to the user verbatim; scrub any secret
    # it may have surfaced (tool data, ticket free-text, prompt-injected content).
    response_text = redact_secrets(response_text)

    # ── Persist messages to DB ──────────────────────────────────────────────────
    if _HISTORY_ENABLED and err_status == "ok" and response_text:
        _conv_id = get_or_create_conversation(user_id, body.session_id, body.message)
        if _conv_id:
            _save_msg(_conv_id, "user", body.message)
            _save_msg(
                _conv_id, "bot", response_text,
                tool_called=tool_called,
                tool_result=tool_result,
                sap_source=sap_source,
                abap_check=abap_check_payload,
                abap_code=abap_code_payload,
                report=report_payload,
            )

    # A write that needs confirmation is not an error and not a result — it is a
    # question back to the user, carrying the token that will execute it.
    pending_action = None
    confirm_token  = None
    if isinstance(tool_result, dict) and tool_result.get("status") == "CONFIRMATION_REQUIRED":
        pending_action = tool_result.get("pending_action")
        confirm_token  = tool_result.get("confirm_token")
        response_text  = tool_result.get("message") or response_text
        tool_result    = None

    _resp = ChatResponse(
        response=response_text,
        pending_action=pending_action,
        confirm_token=confirm_token,
        tool_called=tool_called,
        tool_result=tool_result,
        action_plan=action_plan,
        sap_source=sap_source,
        request_id=rid,
        report=report_payload,
        abap_check=abap_check_payload,
        abap_code=abap_code_payload,
        status="ok",
    )

    # ── Cache store (only classified-safe, successful, non-clarification) ─────────
    if err_status == "ok" and not body.clarification_answer and not pending_action:
        _cacheable, _ = classify_for_cache(tool_called=tool_called, text=response_text)
        if _cacheable:
            redis_cache.set("chat", user_id, _cache_key, _resp.model_dump())

    return _resp


# ── Streaming chat endpoint ────────────────────────────────────────────────────

@app.post("/chat/stream")
@limiter.limit("30/minute")
async def chat_stream(
    request: Request,
    body: ChatRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    SSE streaming version of /chat.
    Yields server-sent events: status, answer, done, error.
    Compatible with fetch() ReadableStream on the frontend.
    """
    import asyncio

    user_id    = current_user["user_id"]
    user_roles = current_user.get("roles", [])
    client_ip  = request.client.host if request.client else "unknown"

    # ── Resolve the model through the router (applies policy gate) ──
    agent_session_id = _agent_key(user_id, body.session_id)
    agent = await asyncio.to_thread(_get_agent, agent_session_id)
    agent.requested_model_id = body.model_id
    resolution = _resolve_chat_model_or_503(agent, body.model_id)
    resolved_model_id = resolution.resolved.model.id

    allowed_tools = get_allowed_tools(user_roles) if _AUTH_ENABLED else None

    # Bind the acting user for the whole streamed response so execute_tool() can
    # enforce the confirmation gate on destructive actions (finding F-03).
    # Set directly rather than via `with`, because the generator body outlives
    # this frame; the tokens are reset in the generator's finally block.
    from core.authorization import _actor, _confirm, _enforce
    _authz_tokens = (_actor.set(user_id),
                     _confirm.set(body.confirm_token),
                     _enforce.set(_AUTH_ENABLED))

    async def event_generator():
        import re as _re
        tool_called        = None
        tool_result        = None
        sap_source         = None
        report_payload     = None
        abap_check_payload = None
        abap_code_payload  = None
        full_text          = ""
        err_status         = "ok"
        status_steps       = []
        t_start            = time.monotonic()
        # Accumulate streamed table rows so large datasets persist correctly
        _streamed_rows     = []
        _streamed_columns  = []

        # ── Visualization intent detection ────────────────────────────────────
        _VIZ_KEYWORDS = {
            "visualize", "visualise", "chart", "plot", "graph",
            "bar chart", "pie chart", "trend", "show me a chart",
            "histogram", "scatter",
        }
        _show_viz = any(kw in body.message.lower() for kw in _VIZ_KEYWORDS)

        def _sse(event_type: str, payload: dict) -> str:
            return f"event: {event_type}\ndata: {json.dumps(payload, cls=_JsonEncoder)}\n\n"

        try:
            # ── ABAP code generation ──────────────────────────────────────────
            _gen_match = _re.match(
                r'(?i)generate\s+abap\s+code\s+for\s*:\s*(.+)',
                body.message.strip(), _re.DOTALL
            )
            if _gen_match:
                _gen_description = _gen_match.group(1).strip()
                status_steps.append("Generating ABAP code...")
                yield _sse("status", {"step": "Generating ABAP code...", "phase": "calling_tool", "tool": "generate_abap_code"})
                try:
                    from modules.abap import generate_abap_code
                    abap_code_payload = await asyncio.to_thread(generate_abap_code, _gen_description)
                    tool_called = "generate_abap_code"
                    code_type = abap_code_payload.get("code_type", "ABAP Code")
                    response_text = (
                        f"**Generated ABAP Code — {code_type}**\n\n"
                        f"Here is the generated ABAP code for: *{_gen_description}*\n\n"
                        f"See the code panel below. Copy it and paste into SE38."
                    )
                    full_text = response_text
                    yield _sse("answer", {"delta": response_text})
                except Exception:
                    _logger.exception("ABAP code generation failed")
                    abap_code_payload = None
                yield _sse("done", {
                    "tool_called": tool_called, "tool_result": None,
                    "sap_source": None, "report": None,
                    "abap_check": None, "abap_code": abap_code_payload,
                    "show_visualization": False,
                    "duration_ms": int((time.monotonic() - t_start) * 1000),
                    "model": resolved_model_id,
                })
                return

            # ── ABAP syntax check ─────────────────────────────────────────────
            _abap_fence   = _re.search(r'```abap\s*([\s\S]+?)```', body.message, _re.IGNORECASE)
            _check_intent = any(kw in body.message.lower() for kw in
                                ["check this", "check code", "analyze code", "review code",
                                 "code review", "syntax check", "check abap", "analyse code"])
            if _abap_fence or _check_intent:
                _code_to_check = _abap_fence.group(1).strip() if _abap_fence else None
                if not _code_to_check:
                    _lines = body.message.strip().splitlines()
                    _code_lines = [l for l in _lines if _re.match(
                        r'^\s*(DATA|SELECT|LOOP|IF|FORM|METHOD|REPORT|TABLES|CALL|ENDLOOP|ENDIF|ENDFORM|ENDMETHOD)\b',
                        l, _re.IGNORECASE)]
                    if len(_code_lines) >= 2:
                        _code_to_check = body.message.strip()
                if _code_to_check:
                    status_steps.append("Analyzing ABAP syntax...")
                    yield _sse("status", {"step": "Analyzing ABAP syntax...", "phase": "calling_tool", "tool": "analyze_abap_syntax"})
                    try:
                        from modules.abap import analyze_abap_syntax
                        abap_check_payload = await asyncio.to_thread(analyze_abap_syntax, _code_to_check)
                        abap_check_payload["code"] = _code_to_check
                        tool_called = "analyze_abap_syntax"
                        score  = abap_check_payload.get("quality_score", 0)
                        rating = abap_check_payload.get("rating", "")
                        ec = abap_check_payload.get("error_count", 0)
                        wc = abap_check_payload.get("warning_count", 0)
                        sc = abap_check_payload.get("suggestion_count", 0)
                        response_text = (
                            f"**ABAP Code Review — {rating}** (Quality score: {score}/100)\n\n"
                            f"Found **{ec} error(s)**, **{wc} warning(s)**, **{sc} suggestion(s)** "
                            f"across {abap_check_payload.get('lines_analyzed', 0)} lines. "
                            f"See the review panel below."
                        )
                        full_text = response_text
                        yield _sse("answer", {"delta": response_text})
                    except Exception:
                        _logger.exception("ABAP syntax check failed")
                        abap_check_payload = None
                    yield _sse("done", {
                        "tool_called": tool_called, "tool_result": None,
                        "sap_source": None, "report": None,
                        "abap_check": abap_check_payload, "abap_code": None,
                        "show_visualization": False,
                        "duration_ms": int((time.monotonic() - t_start) * 1000),
                        "model": resolved_model_id,
                    })
                    return

            # ── Report / visualization intent ─────────────────────────────────
            from agent.report_agent import (is_report_query, generate as gen_report,
                                            reply_text as report_reply, is_access_denied)
            if is_report_query(body.message):
                status_steps.append("Generating report and charts...")
                yield _sse("status", {"step": "Generating report and charts...", "phase": "calling_tool", "tool": "report_agent"})
                try:
                    # Same allow-list the tool path uses — a "chart" request must
                    # not reach data the caller's role does not permit.
                    report_payload = await asyncio.to_thread(
                        gen_report, body.message, allowed_tools)
                    if is_access_denied(report_payload):
                        yield _sse("error", {
                            "message": "Access denied: your role does not permit "
                                       "reporting on this data.",
                            "status_code": 403,
                        })
                        return
                    if report_payload:
                        response_text = report_reply(body.message, report_payload)
                        tool_called   = "report_agent"
                        full_text     = response_text
                        yield _sse("answer", {"delta": response_text})
                        yield _sse("done", {
                            "tool_called": tool_called, "tool_result": None,
                            "sap_source": None, "report": report_payload,
                            "abap_check": None, "abap_code": None,
                            "show_visualization": _show_viz,
                            "duration_ms": int((time.monotonic() - t_start) * 1000),
                            "model": resolved_model_id,
                        })
                        return
                except Exception:
                    _logger.exception("Report agent failed; falling through to main agent")
                    report_payload = None

            # ── Main agent streaming path ─────────────────────────────────────
            async for event_str in agent.chat_stream(
                body.message,
                allowed_tools=allowed_tools,
                clarification_answer=body.clarification_answer,
                ticket_status=body.ticket_status,
            ):
                # Intercept events to extract metadata for audit logging and history
                if event_str.startswith("event: done"):
                    try:
                        data_line = next(l for l in event_str.split("\n") if l.startswith("data:"))
                        done_data  = json.loads(data_line[5:])
                        tool_called  = done_data.get("tool_called")
                        tool_result  = done_data.get("tool_result")
                        sap_source   = done_data.get("sap_source")
                        done_data["show_visualization"] = _show_viz
                        done_data["duration_ms"] = int((time.monotonic() - t_start) * 1000)
                        done_data["model"] = resolved_model_id
                        yield f"event: done\ndata: {json.dumps(done_data, cls=_JsonEncoder)}\n\n"
                    except Exception:
                        yield event_str
                    continue
                elif event_str.startswith("event: answer"):
                    try:
                        data_line = next(l for l in event_str.split("\n") if l.startswith("data:"))
                        full_text += json.loads(data_line[5:]).get("delta", "")
                    except Exception:
                        pass
                elif event_str.startswith("event: status"):
                    try:
                        data_line = next(l for l in event_str.split("\n") if l.startswith("data:"))
                        step = json.loads(data_line[5:]).get("step", "")
                        if step:
                            status_steps.append(step)
                    except Exception:
                        pass
                elif event_str.startswith("event: table_start"):
                    try:
                        data_line = next(l for l in event_str.split("\n") if l.startswith("data:"))
                        _streamed_columns = json.loads(data_line[5:]).get("columns", [])
                    except Exception:
                        pass
                elif event_str.startswith("event: table_rows"):
                    try:
                        data_line = next(l for l in event_str.split("\n") if l.startswith("data:"))
                        _streamed_rows.extend(json.loads(data_line[5:]).get("rows", []))
                    except Exception:
                        pass
                elif event_str.startswith("event: table_end"):
                    yield event_str
                    if _streamed_columns or _streamed_rows:
                        yield _sse("rows", {
                            "columns": _streamed_columns,
                            "rows": _streamed_rows,
                            "row_count": len(_streamed_rows),
                            "truncated": False,
                        })
                    continue

                # Check RBAC on tool used
                if (
                    tool_called
                    and tool_called not in ("action_plan", "autonomous_agent", "auto_research",
                                            "report_agent", "analyze_abap_syntax", "generate_abap_code")
                    and _AUTH_ENABLED
                    and not check_tool_access(tool_called, user_roles)
                ):
                    yield _sse("error", {"message": f"Access denied: your role does not permit '{tool_called}'."})
                    err_status = "error"
                    return

                yield event_str

        except Exception:
            err_status = "error"
            _logger.exception("Unhandled error in /chat/stream for user %s", user_id)
            yield _sse("error", {"message": "An internal error occurred. Contact your administrator."})

        finally:
            # Release the authorization context bound before the generator ran.
            try:
                _actor.reset(_authz_tokens[0])
                _confirm.reset(_authz_tokens[1])
                _enforce.reset(_authz_tokens[2])
            except Exception:
                pass
            duration_ms = int((time.monotonic() - t_start) * 1000)
            rid = log_request(
                user_id=user_id,
                user_roles=user_roles,
                client_ip=client_ip,
                endpoint="/chat/stream",
                query=body.message,
                tool_called=tool_called,
                tool_parameters={k: v for k, v in (tool_result or {}).items()
                                 if k not in ("sap_source",)} if tool_called else None,
                sap_source=sap_source,
                response_text=full_text,
                duration_ms=duration_ms,
                status=err_status,
            )

            if _HISTORY_ENABLED and err_status == "ok" and full_text:
                # If the tool result was streamed in chunks, reconstruct full rows for DB persistence
                if isinstance(tool_result, dict) and tool_result.get("_streamed") and _streamed_rows:
                    tool_result = {"rows": _streamed_rows, "sap_source": tool_result.get("sap_source")}
                _conv_id = await _async_get_or_create_conv(user_id, body.session_id, body.message)
                if _conv_id:
                    await _async_save_msg(_conv_id, "user", body.message)
                    await _async_save_msg(
                        _conv_id, "bot", full_text,
                        tool_called=tool_called,
                        tool_result=tool_result,
                        sap_source=sap_source,
                        abap_check=abap_check_payload,
                        abap_code=abap_code_payload,
                        report=report_payload,
                        status_steps=status_steps or [],
                    )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ── Audit log endpoints ────────────────────────────────────────────────────────

@app.get("/audit/logs")
def audit_logs(
    # Filters
    user_id:    str | None = None,
    endpoint:   str | None = None,
    status:     str | None = None,   # 'ok' | 'error'
    method:     str | None = None,
    log_source: str | None = None,   # 'audit' | 'middleware'
    # Typed rather than str: an unparseable value used to sail through to SQL,
    # where "timestamp >= 'not-a-date'" filtered everything out and the caller
    # got 200 with total: 0. An auditor reading that concludes there was no
    # activity in the window. FastAPI now answers 422 on a bad value.
    from_ts:    datetime | None = None,
    to_ts:      datetime | None = None,
    # Pagination
    limit:  int = 100,
    offset: int = 0,
    admin: dict = Depends(require_admin),
):
    """
    Return activity log records with optional filtering and pagination.
    Admin only — SOX/GDPR compliant.

    Filters: user_id, endpoint (partial match), status (ok|error),
             method, log_source (audit|middleware), from_ts, to_ts (ISO datetimes)
    """
    limit  = min(limit, 500)   # cap to prevent accidental huge queries
    if _ACTIVITY_DB:
        logs  = _query_activity(
            user_id=user_id, endpoint=endpoint, status=status,
            method=method, log_source=log_source,
            from_ts=from_ts, to_ts=to_ts,
            limit=limit, offset=offset,
        )
        total = _count_activity(
            user_id=user_id, endpoint=endpoint, status=status,
            method=method, log_source=log_source,
            from_ts=from_ts, to_ts=to_ts,
        )
        return {
            "logs":  logs,
            "total": total,
            "limit": limit,
            "offset": offset,
            "db_backed": True,
            "files": list_log_files(),
        }
    # Fallback: file-based logs
    return {
        "logs":  get_recent_logs(limit=limit, user_id=user_id),
        "total": None,
        "db_backed": False,
        "files": list_log_files(),
    }


@app.get("/audit/stats")
def audit_stats(
    from_ts: datetime | None = None,   # see audit_logs() above
    to_ts:   datetime | None = None,
    admin: dict = Depends(require_admin),
):
    """
    Aggregate analytics — total requests, error rate, requests per endpoint/user/tool,
    hourly breakdown. Admin only.
    """
    if not _ACTIVITY_DB:
        raise HTTPException(status_code=503, detail="Stats require DB to be connected.")
    return _activity_stats(from_ts=from_ts, to_ts=to_ts)


@app.get("/audit/my-logs")
def my_logs(
    limit:  int = 50,
    offset: int = 0,
    from_ts: datetime | None = None,   # see audit_logs() above
    to_ts:   datetime | None = None,
    current_user: dict = Depends(get_current_user),
):
    """Return the current user's own activity logs with optional date range."""
    uid = current_user["user_id"]
    if _ACTIVITY_DB:
        logs  = _query_activity(user_id=uid, from_ts=from_ts, to_ts=to_ts,
                                limit=limit, offset=offset)
        total = _count_activity(user_id=uid, from_ts=from_ts, to_ts=to_ts)
        return {"logs": logs, "total": total, "db_backed": True}
    return {"logs": get_recent_logs(limit=limit, user_id=uid), "db_backed": False}


# ── Session reset ──────────────────────────────────────────────────────────────

@app.post("/kutty/ask", response_model=KuttyAskResponse)
@limiter.limit("30/minute")
async def kutty_ask(
    request: Request,
    body: KuttyAskRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Kutty — direct RAG over the SAP consulting ticket backlog.
    Retrieval (PageIndex-style tree search) runs first, then the local model
    writes a grounded answer over the retrieved ticket cards.
    RBAC: requires the 'search_sap_tickets' tool (granted via the 'tickets' module).
    """
    import asyncio as _aio
    from core import redis_cache
    from core.security import classify_for_cache
    user_id = current_user["user_id"]
    user_roles = current_user.get("roles", [])
    if _AUTH_ENABLED and not check_tool_access("search_sap_tickets", user_roles):
        raise HTTPException(
            status_code=403,
            detail="Access denied: your role does not permit ticket-backlog search.",
        )

    # ── Cache lookup (per-user key; status is part of the key) ──
    cache_key = redis_cache.make_key("kutty", body.query, str(body.k), body.status or "")
    cached = redis_cache.get("kutty_ask", user_id, cache_key)
    if cached:
        return KuttyAskResponse(answer=cached["answer"], tickets=cached.get("tickets", []), status="cached")

    try:
        from training.kutty.kutty import ask as _kutty_ask
        result = await _aio.to_thread(_kutty_ask, body.query, body.k, body.status)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception:
        logger.exception("Kutty ask failed for user %s", user_id)
        raise HTTPException(status_code=500, detail="Kutty request failed. See server logs.")

    # ── Cache store (only if classified safe) ──
    cacheable, _reason = classify_for_cache(tool_called="search_sap_tickets", text=result["answer"])
    if cacheable:
        redis_cache.set("kutty_ask", user_id, cache_key,
                        {"answer": result["answer"], "tickets": result["tickets"]})
    return KuttyAskResponse(answer=result["answer"], tickets=result["tickets"], status="ok")


@app.post("/reset")
def reset(request: ChatRequest | None = None, current_user: dict = Depends(get_current_user)):
    user_id    = current_user["user_id"]
    session_id = request.session_id if request else "default"
    key        = _agent_key(user_id, session_id)
    with _session_lock:
        if key in _session_agents:
            _session_agents[key].reset_conversation()
    if _HISTORY_ENABLED:
        _clear_messages(session_id, user_id)
    return {"status": "ok", "message": "Conversation history cleared"}


# ── Chat History endpoints ─────────────────────────────────────────────────────

@app.get("/conversations")
def list_convs(current_user: dict = Depends(get_current_user)):
    """List all conversations for the current user, newest first."""
    if not _HISTORY_ENABLED:
        return {"conversations": []}
    user_id = current_user["user_id"]
    convs = _list_conversations(user_id)
    return {"conversations": convs}


@app.get("/conversations/{session_id:path}/messages")
def get_conv_messages(session_id: str, current_user: dict = Depends(get_current_user)):
    """Return all messages for a conversation (user must own it)."""
    if not _HISTORY_ENABLED:
        return {"messages": []}
    user_id = current_user["user_id"]
    msgs = _get_messages(session_id, user_id)
    return {"messages": msgs}


@app.delete("/conversations/{session_id:path}")
def delete_conv(session_id: str, current_user: dict = Depends(get_current_user)):
    """Delete a conversation and all its messages."""
    user_id = current_user["user_id"]
    # Also clear the in-memory agent if it exists.
    #
    # /chat caches agents under "{user_id}:{session_id}" (_agent_key), and this
    # looked up the bare session_id — so the keys never matched, the branch was
    # dead, and deleting a conversation removed its database rows while the
    # transcript stayed in memory and kept being replayed into the model on the
    # next turn. Using the same key builder as /chat is what stops the two
    # drifting apart again; it also scopes the eviction to the caller, so one
    # user's delete cannot evict another user's identically-named session.
    key = _agent_key(user_id, session_id)
    with _session_lock:
        if key in _session_agents:
            _session_agents.pop(key, None)
            if key in _session_order:
                _session_order.remove(key)
    if _HISTORY_ENABLED:
        deleted = _delete_conversation(session_id, user_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Conversation not found.")
    return {"status": "ok"}


# ── Auto Research endpoint ─────────────────────────────────────────────────────

@app.post("/research", response_model=ResearchResponse)
@limiter.limit("20/minute")
def research(
    request: Request,
    body: ResearchRequest,
    current_user: dict = Depends(get_current_user),
):
    """Auto Research: chains multiple SAP tool calls and returns a structured report."""
    user_id    = current_user["user_id"]
    user_roles = current_user.get("roles", [])
    client_ip  = request.client.host if request.client else "unknown"

    agent      = _get_agent(f"{user_id}:research")
    t_start    = time.monotonic()
    err_status = "ok"
    result     = {}
    rid        = None

    try:
        _, _, result = agent.auto_research(
            body.query,
            allowed_tools=get_allowed_tools(user_roles) if _AUTH_ENABLED else None,
        )
    except Exception:
        err_status = "error"
        _logger.exception("Unhandled error in /research for user %s", user_id)
        raise HTTPException(status_code=500, detail="An internal error occurred. Contact your administrator.")
    finally:
        duration_ms = int((time.monotonic() - t_start) * 1000)
        rid = log_request(
            user_id=user_id,
            user_roles=user_roles,
            client_ip=client_ip,
            endpoint="/research",
            query=body.query,
            tool_called="auto_research",
            tool_parameters={
                "entity_type": result.get("entity_type"),
                "entity_id":   result.get("entity_id"),
                "tools_run":   result.get("tools_run", []),
            },
            sap_source=None,
            response_text=result.get("formatted_report", "")[:200],
            duration_ms=duration_ms,
            status=err_status,
        )

    return ResearchResponse(
        report=result.get("formatted_report", ""),
        anomalies=result.get("anomalies", []),
        tools_used=result.get("tools_run", []),
        sap_sources=result.get("sources_used", []),
        entity_type=result.get("entity_type"),
        entity_id=result.get("entity_id"),
        duration_ms=duration_ms,
        request_id=rid,
        success=result.get("success", False),
    )


# ── Autonomous Agent endpoint ──────────────────────────────────────────────────

@app.post("/autonomous", response_model=AutonomousResponse)
@limiter.limit("10/minute")
def autonomous(
    request: Request,
    body: AutonomousRequest,
    current_user: dict = Depends(get_current_user),
):
    """Autonomous Agent: LLM-driven iterative planning with business reasoning."""
    user_id    = current_user["user_id"]
    user_roles = current_user.get("roles", [])
    client_ip  = request.client.host if request.client else "unknown"

    agent      = _get_agent(f"{user_id}:autonomous")
    t_start    = time.monotonic()
    err_status = "ok"
    result: dict = {}
    rid        = None

    try:
        _, _, result = agent.autonomous(
            body.query,
            allowed_tools=get_allowed_tools(user_roles) if _AUTH_ENABLED else None,
        )
    except Exception:
        err_status = "error"
        _logger.exception("Unhandled error in /autonomous for user %s", user_id)
        raise HTTPException(status_code=500, detail="An internal error occurred. Contact your administrator.")
    finally:
        duration_ms = int((time.monotonic() - t_start) * 1000)
        rid = log_request(
            user_id=user_id,
            user_roles=user_roles,
            client_ip=client_ip,
            endpoint="/autonomous",
            query=body.query,
            tool_called="autonomous_agent",
            tool_parameters={
                "iterations":  result.get("iterations", 0),
                "tools_used":  result.get("tools_used", []),
            },
            sap_source=None,
            response_text=result.get("report", "")[:200],
            duration_ms=duration_ms,
            status=err_status,
        )

    return AutonomousResponse(
        report=result.get("report", ""),
        reasoning=result.get("reasoning", ""),
        tool_calls=result.get("tool_calls", []),
        tools_used=result.get("tools_used", []),
        iterations=result.get("iterations", 0),
        duration_ms=duration_ms,
        request_id=rid,
        success=result.get("success", False),
    )


# ── Tools & modules ────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {
        "message":        "DeepResearch AI API",
        "version":        "4.0.0",
        "status":         "running",
        "modules":        ["FI/CO", "MM", "SD", "HR", "PP", "ABAP"],
        "tool_count":     len(TOOLS),
        "sap_connection": config.sap["connection_type"],
        "auth_enabled":   _AUTH_ENABLED,
    }


@app.get("/health")
def health():
    # Use a temporary agent to check connectivity without side effects
    _probe = _make_agent()
    backend_status = _probe.backend_status()
    from db.connection import is_connected as _db_connected
    db_ok = False
    try:
        db_ok = _db_connected()
    except Exception:
        pass

    return {
        "status":          "ok",
        "backend":         backend_status.get("provider", "unknown"),
        "llm_connected":   backend_status.get("connected", False),
        "model":           backend_status.get("model", "unconfigured"),
        "model_identifier": backend_status.get("model_identifier", ""),
        "latency_ms":      backend_status.get("latency_ms"),
        "sap_mode":        config.sap["connection_type"],
        "mcp_builtin":     config.mcp["builtin_enabled"],
        "auth_enabled":    _AUTH_ENABLED,
        "dev_secret":      is_dev_secret() if _AUTH_ENABLED and _IS_DEV else None,
        "db_connected":    db_ok,
        "chat_history":    _HISTORY_ENABLED and db_ok,
        "activity_log":    _ACTIVITY_DB and db_ok,
    }


@app.get("/tools")
def list_tools(current_user: dict = Depends(get_current_user)):
    user_roles    = current_user.get("roles", [])
    allowed       = get_allowed_tools(user_roles) if _AUTH_ENABLED else None
    visible_tools = [
        {**t, "sap_source": SAP_SOURCES_REF.get(t["name"])}
        for t in TOOLS
        if allowed is None or t["name"] in allowed
    ]
    return {"tools": visible_tools, "count": len(visible_tools)}


@app.get("/modules")
def list_modules(current_user: dict = Depends(get_current_user)):
    user_roles = current_user.get("roles", [])
    allowed    = get_allowed_tools(user_roles) if _AUTH_ENABLED else None
    modules: dict[str, list] = {}
    for tool in TOOLS:
        if allowed is not None and tool["name"] not in allowed:
            continue
        mod = tool["module"]
        modules.setdefault(mod, []).append(tool["name"])
    return {"modules": modules}


# ── Config endpoints ───────────────────────────────────────────────────────────

@app.get("/config")
def get_config(admin: dict = Depends(require_admin)):
    return config.get_safe()


@app.post("/config")
def save_config(patch: ConfigPatch, admin: dict = Depends(require_admin)):
    update = {}
    if patch.sap    is not None: update["sap"]    = patch.sap
    if patch.mcp    is not None: update["mcp"]    = patch.mcp
    if patch.ollama is not None: update["ollama"] = patch.ollama
    config.update(update)
    _clear_all_sessions()   # Recreate agents with new config on next request
    return {"status": "ok", "message": "Configuration saved", "config": config.get_safe()}


@app.post("/config/test-sap")
def test_sap_connection(admin: dict = Depends(require_admin)):
    return config.test_sap_connection()


@app.get("/config/mcp-servers")
def list_mcp_servers(admin: dict = Depends(require_admin)):
    """Admin only, to match POST/DELETE on the same resource and GET /config.

    The list carries the names, URLs and transports of internal MCP servers —
    infrastructure detail a read_only account has no reason to see."""
    mcp_cfg = config.mcp
    servers = []
    if mcp_cfg.get("builtin_enabled", True):
        servers.append({
            "name":      "Built-in SAP Tools (stdio)",
            "type":      "builtin",
            "transport": "stdio",
            "enabled":   True,
            "tools":     len(TOOLS),
        })
    for s in mcp_cfg.get("custom_servers", []):
        servers.append({**s, "type": "custom"})
    return {"servers": servers, "count": len(servers)}


@app.post("/config/mcp-servers")
def add_mcp_server(server: MCPServer, admin: dict = Depends(require_admin)):
    mcp_cfg  = config.mcp
    customs  = mcp_cfg.get("custom_servers", [])
    existing = next((i for i, s in enumerate(customs) if s["name"] == server.name), None)
    entry    = server.model_dump()
    if existing is not None:
        customs[existing] = entry
    else:
        customs.append(entry)
    config.update({"mcp": {**mcp_cfg, "custom_servers": customs}})
    return {"status": "ok", "message": f"MCP server '{server.name}' saved", "server": entry}


@app.delete("/config/mcp-servers/{server_name}")
def remove_mcp_server(server_name: str, admin: dict = Depends(require_admin)):
    mcp_cfg = config.mcp
    customs = [s for s in mcp_cfg.get("custom_servers", []) if s["name"] != server_name]
    config.update({"mcp": {**mcp_cfg, "custom_servers": customs}})
    return {"status": "ok", "message": f"MCP server '{server_name}' removed"}


def assert_safe_outbound_url(raw_url: str) -> None:
    """Raise HTTPException(400) unless `raw_url` is safe for the server to fetch.

    Any endpoint that makes the server issue a request to a caller-supplied
    URL is a server-side request forgery gadget unless the target is checked.
    /config/test-mcp was one: it reported "HTTP 200" for a reachable internal
    service and "Connection failed" for a closed port, which turns it into a
    working internal port scanner — and it was open to every authenticated
    caller, including read_only.

    Two rules, both necessary:
      * scheme must be http/https — `file://`, `gopher://` and friends reach
        things an HTTP client was never meant to reach;
      * every address the hostname resolves to must be publicly routable, so
        a name that resolves to 127.0.0.1, an RFC1918 range, or the cloud
        metadata address at 169.254.169.254 is refused rather than probed.

    Checking every resolved address, not just the first, is what stops a
    dual-A-record host from slipping an internal address past the guard.
    """
    import ipaddress
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(raw_url or "")
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            400,
            f"Unsupported URL scheme {parsed.scheme or '(none)'!r}. "
            "Use http:// or https://.",
        )
    host = parsed.hostname
    if not host:
        raise HTTPException(400, "The URL has no host.")

    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise HTTPException(400, f"Host {host!r} could not be resolved.")

    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (address.is_private or address.is_loopback or address.is_link_local
                or address.is_reserved or address.is_multicast
                or address.is_unspecified):
            raise HTTPException(
                400,
                f"Refusing to probe {host!r}: it resolves to the internal "
                f"address {address}. Only publicly routable hosts may be tested.",
            )


@app.post("/config/test-mcp")
def test_mcp_server(server: MCPServer, admin: dict = Depends(require_admin)):
    """Probe a custom MCP server's URL. Admin only — see assert_safe_outbound_url.

    Its POST/DELETE siblings on /config/mcp-servers already required admin;
    this one did not, which let any authenticated account drive outbound
    requests from the server.
    """
    if server.transport == "stdio":
        return {"success": True, "message": "stdio transport — always available locally"}
    assert_safe_outbound_url(server.url)
    try:
        import requests as _r
        # Redirects are not followed: a 302 to an internal address would walk
        # straight past the check above.
        r = _r.head(server.url, timeout=5, allow_redirects=False)
        return {"success": r.status_code < 500, "message": f"HTTP {r.status_code}", "url": server.url}
    except Exception:
        return {"success": False, "message": "Connection failed", "url": server.url}


# ── MCP SSE — Production endpoint ─────────────────────────────────────────────
# Clients (Claude Desktop, Cursor, etc.) connect via:
#   URL:    https://your-server.com/mcp/sse
#   Header: X-MCP-Key: mcp_xxxxxxxxxxxx
# No DB credentials ever leave the server.

from mcp.server import Server as _MCPServer
from mcp.server.sse import SseServerTransport as _SseTransport
from mcp import types as _mcp_types
from tools.tool_registry import execute_tool as _execute_tool
from agent.auto_research import run_auto_research as _run_auto_research

_mcp_server   = _MCPServer("sap-ai-agent")
_mcp_sse      = _SseTransport("/mcp/messages/")

_MCP_KEYS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp_keys.json"
)


# The MCP SDK dispatches tool calls without access to the HTTP request, so the
# authenticated identity is carried on a context variable set by
# _authenticate_mcp_request() and read by the list/call handlers. Tool calls run
# in the same task as the SSE connection, so the value propagates correctly.
_mcp_identity: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "mcp_identity", default=None)


def _mcp_allowed_tools() -> set[str] | None:
    """Tools the current MCP identity may call. None means auth is disabled."""
    if not _AUTH_ENABLED:
        return None
    ident = _mcp_identity.get()
    if ident is None:
        # No authenticated identity on this context — deny everything.
        return set()
    return get_allowed_tools(ident.get("roles", []))


def _load_mcp_keys() -> dict:
    """Load {label: {"hash": ..., "roles": [...]}} from mcp_keys.json.

    Records written by older builds are plain {label: hash} strings; those are
    normalised here and treated as read_only, which grants no SAP tools.
    """
    if os.path.exists(_MCP_KEYS_FILE):
        try:
            with open(_MCP_KEYS_FILE) as f:
                raw = json.load(f)
        except Exception:
            return {}
        out = {}
        for label, rec in (raw or {}).items():
            if isinstance(rec, str):          # legacy: bare hash, no roles
                out[label] = {"hash": rec, "roles": ["read_only"]}
            elif isinstance(rec, dict) and rec.get("hash"):
                out[label] = {"hash": rec["hash"],
                              "roles": rec.get("roles") or ["read_only"]}
        return out
    return {}


def _save_mcp_keys(keys: dict) -> None:
    with open(_MCP_KEYS_FILE, "w") as f:
        json.dump(keys, f, indent=2)
    import stat as _stat
    os.chmod(_MCP_KEYS_FILE, _stat.S_IRUSR | _stat.S_IWUSR)


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _resolve_mcp_key(raw: str | None) -> dict | None:
    """Return {label, roles} for a valid MCP key, or None.

    Keys carry their own roles so an MCP client is bound to the same module
    allow-list as an interactive user (finding F-01).
    """
    if not raw:
        return None
    # Env-var override (single master key for dev/testing). Its roles come from
    # MCP_API_KEY_ROLES so it cannot silently grant more than intended.
    env_key = os.environ.get("MCP_API_KEY", "")
    if env_key and secrets.compare_digest(raw, env_key):
        roles = [r.strip() for r in
                 os.environ.get("MCP_API_KEY_ROLES", "read_only").split(",") if r.strip()]
        return {"label": "env", "roles": roles}
    hashed = _hash_key(raw)
    for label, rec in _load_mcp_keys().items():
        if secrets.compare_digest(hashed, rec["hash"]):
            return {"label": label, "roles": rec["roles"]}
    return None


def _validate_mcp_key(raw: str | None) -> bool:
    """Back-compat boolean form of _resolve_mcp_key()."""
    return _resolve_mcp_key(raw) is not None


@_mcp_server.list_tools()
async def _mcp_list_tools() -> list[_mcp_types.Tool]:
    # Advertise only what this identity may actually call, so an unprivileged
    # client cannot even enumerate restricted SAP tools.
    allowed = _mcp_allowed_tools()
    tools = [
        _mcp_types.Tool(
            name=t["name"],
            description=f"[{t['module']}] {t['description']}",
            inputSchema=t["parameters"],
        )
        for t in TOOLS
        if allowed is None or t["name"] in allowed
    ]
    if allowed is not None and not allowed:
        return tools
    tools.append(_mcp_types.Tool(
        name="sap_auto_research",
        description=(
            "[ALL MODULES] Automatically gather comprehensive data on any SAP entity "
            "(vendor, material, customer, employee, cost center, production order)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language query, e.g. 'research vendor V001'"}
            },
            "required": ["query"],
        },
    ))
    return tools


@_mcp_server.call_tool()
async def _mcp_call_tool(name: str, arguments: dict) -> list[_mcp_types.TextContent]:
    # Authorization is enforced here, before any SAP data is read — the MCP
    # client is never trusted to respect the tool list it was given (F-01).
    allowed = _mcp_allowed_tools()

    def _denied(tool: str) -> list[_mcp_types.TextContent]:
        _logger.info("MCP tool denied by RBAC: %s (identity=%s)",
                     tool, (_mcp_identity.get() or {}).get("user_id"))
        return [_mcp_types.TextContent(type="text", text=json.dumps(
            {"status": "ERROR",
             "message": f"Access denied: tool '{tool}' is not permitted for your role."},
            indent=2))]

    if name == "sap_auto_research":
        if allowed is not None and not allowed:
            return _denied(name)
        query  = (arguments or {}).get("query", "")

        def _guarded(tool_name: str, params: dict) -> dict:
            if allowed is not None and tool_name not in allowed:
                return {"status": "ERROR",
                        "message": f"Access denied: tool '{tool_name}' not permitted"}
            return _execute_tool(tool_name, params)

        result = _run_auto_research(query, _guarded)
        output = {
            "report":      result["formatted_report"],
            "anomalies":   result["anomalies"],
            "tools_used":  result["tools_run"],
            "sap_sources": result["sources_used"],
            "entity_type": result["entity_type"],
            "entity_id":   result["entity_id"],
        }
        return [_mcp_types.TextContent(type="text", text=json.dumps(output, indent=2))]

    if allowed is not None and name not in allowed:
        return _denied(name)
    result = _execute_tool(name, arguments or {})
    return [_mcp_types.TextContent(type="text", text=json.dumps(result, indent=2))]


def _authenticate_mcp_request(request: Request) -> dict:
    """
    Authenticate an MCP request. Accepts two formats:

    1. OAuth 2.1 JWT Bearer  (preferred — issued by /token after /authorize flow)
       Header: Authorization: Bearer <jwt>
       JWT must have aud = MCP resource URL and valid signature.

    2. Static API Key  (backward compat — issued by /mcp/keys)
       Header: X-MCP-Key: mcp_xxxx
       Or query param: ?key=mcp_xxxx

    Returns user dict {user_id, roles} or raises HTTPException 401.
    """
    server_url = os.environ.get("SERVER_URL", "http://localhost:8000").rstrip("/")

    # ── Try OAuth 2.1 JWT Bearer first ────────────────────────────────────────
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        raw_token = auth_header[7:].strip()
        try:
            payload = verify_mcp_token(raw_token)
            return {
                "user_id": payload.get("sub", "unknown"),
                "roles":   payload.get("roles", ["read_only"]),
                "auth":    "oauth",
            }
        except _jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=401,
                detail="Access token expired.",
                headers={
                    "WWW-Authenticate": (
                        f'Bearer realm="mcp", '
                        f'resource_metadata="{server_url}/.well-known/oauth-protected-resource", '
                        f'error="invalid_token", '
                        f'error_description="Token expired"'
                    )
                },
            )
        except _jwt.InvalidTokenError:
            raise HTTPException(
                status_code=401,
                detail="Invalid token.",
                headers={
                    "WWW-Authenticate": (
                        f'Bearer realm="mcp", '
                        f'resource_metadata="{server_url}/.well-known/oauth-protected-resource", '
                        f'error="invalid_token"'
                    )
                },
            )

    # ── Try static X-MCP-Key (backward compat) ────────────────────────────────
    raw_key = (
        request.headers.get("X-MCP-Key")
        or request.headers.get("x-mcp-key")
        or request.query_params.get("key")
    )
    if raw_key:
        key_ident = _resolve_mcp_key(raw_key)
        if key_ident:
            return {"user_id": f"mcp_key:{key_ident['label']}",
                    "roles": key_ident["roles"], "auth": "api_key"}

    # ── No valid credentials — return 401 with RFC 9728 WWW-Authenticate ──────
    raise HTTPException(
        status_code=401,
        detail="Authentication required. Use OAuth 2.1 or X-MCP-Key header.",
        headers={
            "WWW-Authenticate": (
                f'Bearer realm="mcp", '
                f'resource_metadata="{server_url}/.well-known/oauth-protected-resource"'
            )
        },
    )


@app.get("/mcp/sse")
async def mcp_sse(request: Request):
    """
    Production MCP SSE endpoint.

    Supports two auth methods:
      1. OAuth 2.1 JWT:  Authorization: Bearer <token>  (issued after /authorize flow)
      2. Static API key: X-MCP-Key: mcp_xxxx            (backward compat)

    On 401, returns WWW-Authenticate with resource_metadata so MCP clients
    (Claude Desktop, Claude.ai) can auto-discover the OAuth flow.
    """
    identity = _authenticate_mcp_request(request)
    token = _mcp_identity.set(identity)
    _logger.info("MCP session opened for %s (roles=%s, auth=%s)",
                 identity.get("user_id"), identity.get("roles"), identity.get("auth"))
    try:
        async with _mcp_sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await _mcp_server.run(
                streams[0], streams[1], _mcp_server.create_initialization_options()
            )
    finally:
        _mcp_identity.reset(token)


@app.post("/mcp/messages/")
async def mcp_messages(request: Request):
    """Message posting endpoint for SSE transport (called by MCP clients internally).

    Authenticated for the same reason /mcp/sse is: an unauthenticated caller must
    not be able to inject messages into someone else's MCP session.
    """
    _authenticate_mcp_request(request)
    await _mcp_sse.handle_post_message(request.scope, request.receive, request._send)


# ── MCP Key management (admin only) ───────────────────────────────────────────

class MCPKeyCreate(BaseModel):
    label: str   # human-readable name, e.g. "alice-laptop", "client-acme"
    roles: list[str] = ["read_only"]   # SAP modules this key may reach


@app.post("/mcp/keys")
def create_mcp_key(body: MCPKeyCreate, admin: dict = Depends(require_admin)):
    """Generate a new MCP API key. Returns the raw key once — store it securely.

    The key carries roles, so an MCP client is bound to the same module
    allow-list as an interactive user.
    """
    for r in body.roles:
        if r not in ALL_ROLES:
            raise HTTPException(400, f"Unknown role: {r}. Valid roles: {ALL_ROLES}")
    raw    = "mcp_" + secrets.token_hex(24)
    keys   = _load_mcp_keys()
    if body.label in keys:
        raise HTTPException(400, f"Key label '{body.label}' already exists. Delete it first.")
    keys[body.label] = {"hash": _hash_key(raw), "roles": body.roles}
    _save_mcp_keys(keys)
    return {
        "label":   body.label,
        "roles":   body.roles,
        "key":     raw,
        "warning": "Save this key now — it will not be shown again.",
    }


@app.get("/mcp/keys")
def list_mcp_keys(admin: dict = Depends(require_admin)):
    """List all active MCP key labels (not the keys themselves)."""
    keys = _load_mcp_keys()
    return {"keys": [{"label": k, "roles": v["roles"]} for k, v in keys.items()],
            "count": len(keys)}


@app.delete("/mcp/keys/{label}")
def delete_mcp_key(label: str, admin: dict = Depends(require_admin)):
    """Revoke an MCP API key by label."""
    keys = _load_mcp_keys()
    if label not in keys:
        raise HTTPException(404, f"Key '{label}' not found.")
    del keys[label]
    _save_mcp_keys(keys)
    return {"status": "ok", "message": f"Key '{label}' revoked."}


# Late import to avoid circular imports
from tools.tool_registry import SAP_SOURCES as SAP_SOURCES_REF  # noqa: E402


if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("api.server:app", host=host, port=port, reload=_IS_DEV)
