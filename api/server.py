"""
SAP AI Agent - REST API Server
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
import hashlib
import logging
import os
import secrets
import sys
import time
from contextlib import asynccontextmanager
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
from pydantic import BaseModel
from typing import Any

from agent.sap_agent import SAPAgent, _DecimalEncoder as _JsonEncoder
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
_disable_auth_requested = os.environ.get("DISABLE_AUTH", "false").lower() in ("true", "1", "yes")
if _disable_auth_requested and not _IS_DEV:
    print(
        "FATAL: DISABLE_AUTH=true is not permitted outside APP_ENV=development.",
        file=sys.stderr,
    )
    sys.exit(1)
_AUTH_ENABLED = not _disable_auth_requested

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


# ── Startup checks ─────────────────────────────────────────────────────────────
def _startup_checks() -> None:
    if not _IS_DEV:
        errors = []
        if not os.environ.get("JWT_SECRET_KEY"):
            errors.append("JWT_SECRET_KEY must be set in non-development environments.")
        if not os.environ.get("JWT_REFRESH_SECRET"):
            errors.append("JWT_REFRESH_SECRET must be set in non-development environments.")
        if errors:
            for e in errors:
                print(f"FATAL: {e}", file=sys.stderr)
            sys.exit(1)
    else:
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
    except _aio.TimeoutError:
        _logger.warning("DB migration timed out at startup — DB may not be available.")
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
    title="SAP AI Agent API",
    description="Natural language interface to SAP ERP modules",
    version="4.0.0",
    lifespan=lifespan,
)

# Mount OAuth 2.1 endpoints (RFC 9728, RFC 8414, RFC 7591, PKCE)
app.include_router(_oauth_router)

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

                    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() \
                                or (request.client.host if request.client else None)

                    _write_activity(
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
        return response


app.add_middleware(_ActivityMiddleware)

# ── Rate limiting ──────────────────────────────────────────────────────────────
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

def _get_rate_limit_key(request: Request) -> str:
    """Use X-Forwarded-For when behind a reverse proxy; fall back to socket IP."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

limiter = Limiter(key_func=_get_rate_limit_key)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── Per-session agent pool ─────────────────────────────────────────────────────
_MAX_SESSIONS  = 500          # evict oldest when pool exceeds this
_session_agents: dict[str, SAPAgent] = {}
_session_order: list[str] = []   # insertion order for eviction
_session_lock  = Lock()

# Cache MLX availability at startup so _make_agent() never blocks the lock
# with a slow HTTP probe on every new session creation.
_MLX_AVAILABLE: bool | None = None

def _check_mlx_once() -> bool:
    global _MLX_AVAILABLE
    if _MLX_AVAILABLE is None:
        try:
            import requests as _req
            r = _req.get("http://localhost:8080/v1/models", timeout=2)
            _MLX_AVAILABLE = r.status_code == 200
        except Exception:
            _MLX_AVAILABLE = False
    return _MLX_AVAILABLE


def _make_agent() -> SAPAgent:
    agent = SAPAgent(model=config.default_model, ollama_url=config.ollama_url)
    # Override with the cached check so new agents don't re-probe MLX
    agent._use_mlx = _MLX_AVAILABLE if _MLX_AVAILABLE is not None else agent._use_mlx
    return agent


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
_bearer = HTTPBearer(auto_error=False)

_GUEST_USER = {"user_id": "guest", "roles": ["read_only"], "full_name": "Guest (auth disabled)"}


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """
    Validate JWT Bearer token and return user payload.
    When DISABLE_AUTH=true (dev only) returns a limited read_only guest user.
    """
    if not _AUTH_ENABLED:
        return _GUEST_USER

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header. Use: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(credentials.credentials)
        return {"user_id": payload["sub"], "roles": payload.get("roles", [])}
    except _jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Access token expired. Use /auth/refresh to renew.")
    except _jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token.")


def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if "admin" not in current_user.get("roles", []):
        raise HTTPException(status_code=403, detail="Admin role required.")
    return current_user


# ── Pydantic models ────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    model: str = "llama3.2"
    session_id: str = "default"

class ChatResponse(BaseModel):
    response: str
    tool_called: str | None = None
    tool_result: dict | None = None
    action_plan: dict | None = None
    sap_source: dict | None = None
    request_id: str | None = None
    status: str = "ok"
    report: dict | None = None      # inline chart/table widget payload
    abap_check: dict | None = None  # inline ABAP code review widget payload
    abap_code: dict | None = None   # inline ABAP code generation widget payload

class ResearchRequest(BaseModel):
    query: str

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
    query: str

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
        new_access  = create_token(user["user_id"], user["roles"])
        new_refresh = create_refresh_token(user["user_id"])
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
    allowed_modules = list({
        m for role in user.get("roles", []) for m in ROLE_MODULES.get(role, [])
    })
    return {**user, "allowed_modules": sorted(allowed_modules)}


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
        # Revoke MCP key automatically — no lingering access
        keys  = _load_mcp_keys()
        label = f"user:{user_id}"
        if label in keys:
            del keys[label]
            _save_mcp_keys(keys)
        return {"status": "ok", "message": f"User '{user_id}' deactivated and MCP access revoked"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/auth/users/{user_id}/mcp-setup")
def get_user_mcp_setup(user_id: str, admin: dict = Depends(require_admin)):
    """
    Return a ready-to-paste Claude Desktop config for the user.
    If the user has no MCP key yet, generate one now.
    """
    keys  = _load_mcp_keys()
    label = f"user:{user_id}"
    if label not in keys:
        # Generate on demand (e.g. existing users created before this feature)
        mcp_raw     = "mcp_" + secrets.token_hex(24)
        keys[label] = _hash_key(mcp_raw)
        _save_mcp_keys(keys)
    else:
        # Key exists but we can't return the raw value — must regenerate
        mcp_raw     = "mcp_" + secrets.token_hex(24)
        keys[label] = _hash_key(mcp_raw)
        _save_mcp_keys(keys)

    server_url = os.environ.get("SERVER_URL", "http://localhost:8000").rstrip("/")
    claude_cfg = {
        "mcpServers": {
            "sap-ai-agent": {
                "url": f"{server_url}/mcp/sse",
                "headers": {"X-MCP-Key": mcp_raw},
            }
        }
    }
    return {
        "user_id":    user_id,
        "mcp_key":    mcp_raw,
        "server_url": server_url,
        "claude_desktop_config": claude_cfg,
        "instructions": [
            f"1. Open: ~/Library/Application Support/Claude/claude_desktop_config.json",
            "2. Merge the 'mcpServers' block into that file.",
            "3. Fully quit and reopen Claude Desktop (Cmd+Q).",
            "4. Click the hammer icon in Claude Desktop chat — SAP tools will appear.",
        ],
    }


@app.get("/mcp/my-setup")
def get_my_mcp_setup(current_user: dict = Depends(get_current_user)):
    """
    Self-service: logged-in user gets their own Claude Desktop config.
    Regenerates their MCP key — invalidates the old one.
    """
    user_id = current_user["user_id"]
    keys    = _load_mcp_keys()
    label   = f"user:{user_id}"
    mcp_raw = "mcp_" + secrets.token_hex(24)
    keys[label] = _hash_key(mcp_raw)
    _save_mcp_keys(keys)

    server_url = os.environ.get("SERVER_URL", "http://localhost:8000").rstrip("/")
    claude_cfg = {
        "mcpServers": {
            "sap-ai-agent": {
                "url": f"{server_url}/mcp/sse",
                "headers": {"X-MCP-Key": mcp_raw},
            }
        }
    }
    return {
        "mcp_key":    mcp_raw,
        "server_url": server_url,
        "claude_desktop_config": claude_cfg,
        "instructions": [
            "1. Open: ~/Library/Application Support/Claude/claude_desktop_config.json",
            "2. Merge the 'mcpServers' block into that file.",
            "3. Fully quit and reopen Claude Desktop (Cmd+Q).",
            "4. Click the hammer icon in Claude Desktop chat — SAP tools will appear.",
        ],
    }


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

    import asyncio as _aio
    agent = await _aio.to_thread(_get_agent, f"{user_id}:{body.session_id}")
    if body.model != agent.model:
        agent.model = body.model

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
    from agent.report_agent import is_report_query, generate as gen_report, reply_text as report_reply
    if is_report_query(body.message):
        try:
            report_payload = await _aio.to_thread(gen_report, body.message)
            if report_payload:
                response_text = report_reply(body.message, report_payload)
                tool_called   = "report_agent"
        except Exception:
            logger.exception("Report agent failed; falling back to normal chat")
            report_payload = None

    try:
        if not report_payload and not abap_check_payload and not abap_code_payload:
            response_text, tool_called, tool_result = await _aio.to_thread(
                agent.chat,
                body.message,
                get_allowed_tools(user_roles) if _AUTH_ENABLED else None,
            )

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

    return ChatResponse(
        response=response_text,
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
    Yields server-sent events: status, text_delta, done, error.
    Compatible with fetch() ReadableStream on the frontend.
    """
    import asyncio

    user_id    = current_user["user_id"]
    user_roles = current_user.get("roles", [])
    client_ip  = request.client.host if request.client else "unknown"

    agent = await asyncio.to_thread(_get_agent, f"{user_id}:{body.session_id}")
    if body.model != agent.model:
        agent.model = body.model

    allowed_tools = get_allowed_tools(user_roles) if _AUTH_ENABLED else None

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
                yield _sse("status", {"step": "Generating ABAP code...", "phase": "tool_call", "tool": "generate_abap_code"})
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
                    yield _sse("text_delta", {"delta": response_text})
                except Exception:
                    _logger.exception("ABAP code generation failed")
                    abap_code_payload = None
                yield _sse("done", {
                    "tool_called": tool_called, "tool_result": None,
                    "sap_source": None, "report": None,
                    "abap_check": None, "abap_code": abap_code_payload,
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
                    yield _sse("status", {"step": "Analyzing ABAP syntax...", "phase": "tool_call", "tool": "analyze_abap_syntax"})
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
                        yield _sse("text_delta", {"delta": response_text})
                    except Exception:
                        _logger.exception("ABAP syntax check failed")
                        abap_check_payload = None
                    yield _sse("done", {
                        "tool_called": tool_called, "tool_result": None,
                        "sap_source": None, "report": None,
                        "abap_check": abap_check_payload, "abap_code": None,
                    })
                    return

            # ── Report / visualization intent ─────────────────────────────────
            from agent.report_agent import is_report_query, generate as gen_report, reply_text as report_reply
            if is_report_query(body.message):
                status_steps.append("Generating report and charts...")
                yield _sse("status", {"step": "Generating report and charts...", "phase": "tool_call", "tool": "report_agent"})
                try:
                    report_payload = await asyncio.to_thread(gen_report, body.message)
                    if report_payload:
                        response_text = report_reply(body.message, report_payload)
                        tool_called   = "report_agent"
                        full_text     = response_text
                        yield _sse("text_delta", {"delta": response_text})
                        yield _sse("done", {
                            "tool_called": tool_called, "tool_result": None,
                            "sap_source": None, "report": report_payload,
                            "abap_check": None, "abap_code": None,
                        })
                        return
                except Exception:
                    _logger.exception("Report agent failed; falling through to main agent")
                    report_payload = None

            # ── Main agent streaming path ─────────────────────────────────────
            async for event_str in agent.chat_stream(body.message, allowed_tools=allowed_tools):
                # Intercept events to extract metadata for audit logging and history
                if event_str.startswith("event: done"):
                    try:
                        data_line = next(l for l in event_str.split("\n") if l.startswith("data:"))
                        done_data  = json.loads(data_line[5:])
                        tool_called  = done_data.get("tool_called")
                        tool_result  = done_data.get("tool_result")
                        sap_source   = done_data.get("sap_source")
                    except Exception:
                        pass
                elif event_str.startswith("event: text_delta"):
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
                elif event_str.startswith("event: table_rows"):
                    try:
                        data_line = next(l for l in event_str.split("\n") if l.startswith("data:"))
                        _streamed_rows.extend(json.loads(data_line[5:]).get("rows", []))
                    except Exception:
                        pass

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
    from_ts:    str | None = None,   # ISO datetime string
    to_ts:      str | None = None,
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
    from_ts: str | None = None,
    to_ts:   str | None = None,
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
    from_ts: str | None = None,
    to_ts:   str | None = None,
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

@app.post("/reset")
def reset(request: ChatRequest | None = None, current_user: dict = Depends(get_current_user)):
    user_id    = current_user["user_id"]
    session_id = request.session_id if request else "default"
    key        = f"{user_id}:{session_id}"
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
    # Also clear the in-memory agent if it exists
    with _session_lock:
        if session_id in _session_agents:
            _session_agents.pop(session_id, None)
            if session_id in _session_order:
                _session_order.remove(session_id)
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
        "message":        "SAP AI Agent API",
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
    connected = _probe.check_ollama_connection()
    backend   = "mlx-finetuned" if _probe._use_mlx else "ollama"
    cloud_fallback = bool(
        os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    )
    from db.connection import is_connected as _db_connected
    db_ok = False
    try:
        db_ok = _db_connected()
    except Exception:
        pass

    return {
        "status":          "ok",
        "backend":         backend,
        "llm_connected":   connected,
        "cloud_fallback":  cloud_fallback,
        "model":           "sap-model-fused (fine-tuned)" if _probe._use_mlx else config.default_model,
        "ollama_url":      config.ollama_url,
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
def list_mcp_servers(current_user: dict = Depends(get_current_user)):
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


@app.post("/config/test-mcp")
def test_mcp_server(server: MCPServer, current_user: dict = Depends(get_current_user)):
    if server.transport == "stdio":
        return {"success": True, "message": "stdio transport — always available locally"}
    try:
        import requests as _r
        r = _r.head(server.url, timeout=5, allow_redirects=True)
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


def _load_mcp_keys() -> dict:
    """Load {label: hashed_key} from mcp_keys.json."""
    if os.path.exists(_MCP_KEYS_FILE):
        try:
            with open(_MCP_KEYS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_mcp_keys(keys: dict) -> None:
    with open(_MCP_KEYS_FILE, "w") as f:
        json.dump(keys, f, indent=2)
    import stat as _stat
    os.chmod(_MCP_KEYS_FILE, _stat.S_IRUSR | _stat.S_IWUSR)


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _validate_mcp_key(raw: str | None) -> bool:
    """Return True if the raw key matches any stored key or the env-var key."""
    if not raw:
        return False
    # Env-var override (single master key for dev/testing)
    env_key = os.environ.get("MCP_API_KEY", "")
    if env_key and secrets.compare_digest(raw, env_key):
        return True
    # File-stored keys (hashed)
    hashed = _hash_key(raw)
    return hashed in _load_mcp_keys().values()


@_mcp_server.list_tools()
async def _mcp_list_tools() -> list[_mcp_types.Tool]:
    tools = [
        _mcp_types.Tool(
            name=t["name"],
            description=f"[{t['module']}] {t['description']}",
            inputSchema=t["parameters"],
        )
        for t in TOOLS
    ]
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
    if name == "sap_auto_research":
        query  = (arguments or {}).get("query", "")
        result = _run_auto_research(query, _execute_tool)
        output = {
            "report":      result["formatted_report"],
            "anomalies":   result["anomalies"],
            "tools_used":  result["tools_run"],
            "sap_sources": result["sources_used"],
            "entity_type": result["entity_type"],
            "entity_id":   result["entity_id"],
        }
        return [_mcp_types.TextContent(type="text", text=json.dumps(output, indent=2))]
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
    if raw_key and _validate_mcp_key(raw_key):
        return {"user_id": "api_key_user", "roles": ["read_only"], "auth": "api_key"}

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
    _authenticate_mcp_request(request)

    async with _mcp_sse.connect_sse(
        request.scope, request.receive, request._send
    ) as streams:
        await _mcp_server.run(
            streams[0], streams[1], _mcp_server.create_initialization_options()
        )


@app.post("/mcp/messages/")
async def mcp_messages(request: Request):
    """Message posting endpoint for SSE transport (called by MCP clients internally)."""
    await _mcp_sse.handle_post_message(request.scope, request.receive, request._send)


# ── MCP Key management (admin only) ───────────────────────────────────────────

class MCPKeyCreate(BaseModel):
    label: str   # human-readable name, e.g. "alice-laptop", "client-acme"


@app.post("/mcp/keys")
def create_mcp_key(body: MCPKeyCreate, admin: dict = Depends(require_admin)):
    """Generate a new MCP API key. Returns the raw key once — store it securely."""
    raw    = "mcp_" + secrets.token_hex(24)
    keys   = _load_mcp_keys()
    if body.label in keys:
        raise HTTPException(400, f"Key label '{body.label}' already exists. Delete it first.")
    keys[body.label] = _hash_key(raw)
    _save_mcp_keys(keys)
    return {
        "label":   body.label,
        "key":     raw,
        "warning": "Save this key now — it will not be shown again.",
    }


@app.get("/mcp/keys")
def list_mcp_keys(admin: dict = Depends(require_admin)):
    """List all active MCP key labels (not the keys themselves)."""
    keys = _load_mcp_keys()
    return {"keys": list(keys.keys()), "count": len(keys)}


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
