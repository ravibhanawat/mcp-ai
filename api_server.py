"""
SAP AI Agent - REST API Server
Run: uvicorn api_server:app --reload --port 8000

Enterprise additions:
  - JWT authentication (disable with env var DISABLE_AUTH=true for local dev)
  - Role-based access control (RBAC) per SAP module
  - SOX/GDPR-compliant audit logging to logs/audit_YYYY-MM-DD.jsonl
  - SAP source attribution on every tool response
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from typing import Any

from agent.sap_agent import SAPAgent
from tools.tool_registry import TOOLS, get_sap_source
from config_manager import config
from audit_logger import get_recent_logs, list_log_files, log_request
from auth.jwt_handler import create_token, decode_token, is_dev_secret
from auth.rbac import ALL_ROLES, check_tool_access, get_allowed_tools
from auth import users as user_store
import jwt as _jwt
import json

# ── Auth toggle ────────────────────────────────────────────────────────────────
# Set DISABLE_AUTH=true to skip authentication (local dev / demo only)
_AUTH_ENABLED = os.environ.get("DISABLE_AUTH", "false").lower() not in ("true", "1", "yes")

_bearer = HTTPBearer(auto_error=False)

app = FastAPI(
    title="SAP AI Agent API",
    description="Natural language interface to SAP ERP modules via Ollama",
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Agent factory ──────────────────────────────────────────────────────────────
def _make_agent() -> SAPAgent:
    return SAPAgent(model=config.default_model, ollama_url=config.ollama_url)

agent = _make_agent()


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

class CreateUserRequest(BaseModel):
    user_id: str
    password: str
    full_name: str
    email: str
    roles: list[str]


# ── Auth dependency ────────────────────────────────────────────────────────────

_GUEST_USER = {"user_id": "guest", "roles": ["admin"], "full_name": "Guest (auth disabled)"}

def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """
    Extract and verify the JWT Bearer token.
    Returns the user payload dict.

    When DISABLE_AUTH=true this always returns a guest admin user.
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
        raise HTTPException(status_code=401, detail="Token expired. Please log in again.")
    except _jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token.")


def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if "admin" not in current_user.get("roles", []):
        raise HTTPException(status_code=403, detail="Admin role required.")
    return current_user


# ── Auth endpoints ─────────────────────────────────────────────────────────────

@app.post("/auth/login")
def login(body: LoginRequest):
    """Authenticate and receive a JWT token."""
    user = user_store.authenticate(body.user_id, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials.")
    token = create_token(user["user_id"], user["roles"])
    return {
        "access_token": token,
        "token_type":   "bearer",
        "user_id":      user["user_id"],
        "roles":        user["roles"],
        "full_name":    user.get("full_name"),
        "warning":      "Insecure dev secret key in use — set JWT_SECRET_KEY env var" if is_dev_secret() else None,
    }

@app.get("/auth/me")
def me(current_user: dict = Depends(get_current_user)):
    """Return the current authenticated user."""
    user = user_store.get_user(current_user["user_id"])
    if not user:
        return current_user   # fallback for guest/disabled-auth mode
    allowed_modules = list({
        m for role in user.get("roles", []) for m in
        __import__("auth.rbac", fromlist=["ROLE_MODULES"]).ROLE_MODULES.get(role, [])
    })
    return {**user, "allowed_modules": sorted(allowed_modules)}

@app.get("/auth/users")
def list_users(admin: dict = Depends(require_admin)):
    """List all users (admin only)."""
    return {"users": user_store.list_users()}

@app.post("/auth/users")
def create_user(body: CreateUserRequest, admin: dict = Depends(require_admin)):
    """Create a new user account (admin only)."""
    try:
        new_user = user_store.create_user(
            body.user_id, body.password, body.full_name, body.email, body.roles
        )
        return {"status": "ok", "user": new_user}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.patch("/auth/users/{user_id}/deactivate")
def deactivate_user(user_id: str, admin: dict = Depends(require_admin)):
    """Deactivate a user account (admin only)."""
    try:
        user_store.set_active(user_id, False)
        return {"status": "ok", "message": f"User '{user_id}' deactivated"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Core chat endpoint ─────────────────────────────────────────────────────────

@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest, http_request: Request, current_user: dict = Depends(get_current_user)):
    """
    Main chat endpoint.
    - Enforces RBAC: tool calls blocked if user lacks module access.
    - Writes a full audit record (SOX/GDPR).
    - Returns SAP source attribution with every tool result.
    """
    user_id    = current_user["user_id"]
    user_roles = current_user.get("roles", [])
    client_ip  = http_request.client.host if http_request.client else "unknown"

    if request.model != agent.model:
        agent.model = request.model

    t_start = time.monotonic()
    tool_called   = None
    tool_result   = None
    action_plan   = None
    sap_source    = None
    response_text = ""
    err_status    = "ok"

    try:
        response_text, tool_called, tool_result = agent.chat(
            request.message,
            allowed_tools=get_allowed_tools(user_roles) if _AUTH_ENABLED else None,
        )

        # Separate action plans and autonomous results from regular tool results
        if tool_called in ("action_plan", "autonomous_agent", "auto_research") and isinstance(tool_result, dict):
            action_plan = tool_result if tool_called == "action_plan" else None
            tool_result = None

        # RBAC: if agent called a tool the user isn't allowed, block it
        if tool_called and tool_called not in ("action_plan", "autonomous_agent", "auto_research") and _AUTH_ENABLED and not check_tool_access(tool_called, user_roles):
            raise HTTPException(
                status_code=403,
                detail=f"Access denied: your role does not permit '{tool_called}'. "
                       f"Contact your SAP administrator to request access.",
            )

        if tool_result:
            sap_source = tool_result.get("sap_source") or get_sap_source(tool_called or "")

    except HTTPException:
        raise
    except Exception as e:
        err_status = "error"
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        duration_ms = int((time.monotonic() - t_start) * 1000)
        rid = log_request(
            user_id=user_id,
            user_roles=user_roles,
            client_ip=client_ip,
            endpoint="/chat",
            query=request.message,
            tool_called=tool_called,
            tool_parameters={k: v for k, v in (tool_result or {}).items()
                             if k not in ("sap_source",)} if tool_called else None,
            sap_source=sap_source,
            response_text=response_text,
            duration_ms=duration_ms,
            status=err_status,
        )

    return ChatResponse(
        response=response_text,
        tool_called=tool_called,
        tool_result=tool_result,
        action_plan=action_plan,
        sap_source=sap_source,
        request_id=rid,
        status="ok",
    )


# ── Audit log endpoints ────────────────────────────────────────────────────────

@app.get("/audit/logs")
def audit_logs(limit: int = 50, admin: dict = Depends(require_admin)):
    """Return recent audit log entries (admin only). SOX/GDPR compliance."""
    return {"logs": get_recent_logs(limit=limit), "files": list_log_files()}

@app.get("/audit/my-logs")
def my_logs(limit: int = 20, current_user: dict = Depends(get_current_user)):
    """Return the current user's own recent audit entries."""
    return {"logs": get_recent_logs(limit=limit, user_id=current_user["user_id"])}


# ── Reset ──────────────────────────────────────────────────────────────────────

@app.post("/reset")
def reset(current_user: dict = Depends(get_current_user)):
    agent.reset_conversation()
    return {"status": "ok", "message": "Conversation history cleared"}


# ── Auto Research endpoint ──────────────────────────────────────────────────────

@app.post("/research", response_model=ResearchResponse)
def research(request: ResearchRequest, http_request: Request, current_user: dict = Depends(get_current_user)):
    """
    Auto Research endpoint: autonomously chains multiple SAP tool calls for
    an entity and returns a structured markdown report with anomaly detection.
    """
    user_id    = current_user["user_id"]
    user_roles = current_user.get("roles", [])
    client_ip  = http_request.client.host if http_request.client else "unknown"

    t_start = time.monotonic()
    err_status = "ok"
    result = {}
    rid = None

    try:
        _, _, result = agent.auto_research(
            request.query,
            allowed_tools=get_allowed_tools(user_roles) if _AUTH_ENABLED else None,
        )
    except Exception as e:
        err_status = "error"
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        duration_ms = int((time.monotonic() - t_start) * 1000)
        rid = log_request(
            user_id=user_id,
            user_roles=user_roles,
            client_ip=client_ip,
            endpoint="/research",
            query=request.query,
            tool_called="auto_research",
            tool_parameters={"entity_type": result.get("entity_type"), "entity_id": result.get("entity_id"), "tools_run": result.get("tools_run", [])},
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
def autonomous(request: AutonomousRequest, http_request: Request, current_user: dict = Depends(get_current_user)):
    """
    Autonomous Agent endpoint: LLM-driven iterative tool planning and execution
    with business decision reasoning. Use for complex queries that require
    multi-step investigation and strategic recommendations.
    """
    user_id    = current_user["user_id"]
    user_roles = current_user.get("roles", [])
    client_ip  = http_request.client.host if http_request.client else "unknown"

    t_start = time.monotonic()
    err_status = "ok"
    result: dict = {}
    rid = None

    try:
        _, _, result = agent.autonomous(
            request.query,
            allowed_tools=get_allowed_tools(user_roles) if _AUTH_ENABLED else None,
        )
    except Exception as e:
        err_status = "error"
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        duration_ms = int((time.monotonic() - t_start) * 1000)
        rid = log_request(
            user_id=user_id,
            user_roles=user_roles,
            client_ip=client_ip,
            endpoint="/autonomous",
            query=request.query,
            tool_called="autonomous_agent",
            tool_parameters={"iterations": result.get("iterations", 0), "tools_used": result.get("tools_used", [])},
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
        "status":         "running",
        "modules":        ["FI/CO", "MM", "SD", "HR", "PP", "ABAP"],
        "tool_count":     len(TOOLS),
        "sap_connection": config.sap["connection_type"],
        "auth_enabled":   _AUTH_ENABLED,
    }

@app.get("/health")
def health():
    connected = agent.check_ollama_connection()
    backend   = "mlx-finetuned" if agent._use_mlx else "ollama"
    return {
        "status":       "ok",
        "backend":      backend,
        "llm_connected": connected,
        "model":        "sap-model-fused (fine-tuned)" if agent._use_mlx else agent.model,
        "ollama_url":   config.ollama_url,
        "sap_mode":     config.sap["connection_type"],
        "mcp_builtin":  config.mcp["builtin_enabled"],
        "auth_enabled": _AUTH_ENABLED,
        "dev_secret":   is_dev_secret() if _AUTH_ENABLED else None,
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
    global agent
    update = {}
    if patch.sap  is not None: update["sap"]   = patch.sap
    if patch.mcp  is not None: update["mcp"]   = patch.mcp
    if patch.ollama is not None: update["ollama"] = patch.ollama
    config.update(update)
    agent = _make_agent()
    return {"status": "ok", "message": "Configuration saved", "config": config.get_safe()}

@app.post("/config/test-sap")
def test_sap_connection(admin: dict = Depends(require_admin)):
    return config.test_sap_connection()

@app.get("/config/mcp-servers")
def list_mcp_servers(current_user: dict = Depends(get_current_user)):
    mcp_cfg = config.mcp
    servers = []
    if mcp_cfg.get("builtin_enabled", True):
        servers.append({"name": "Built-in SAP Tools (stdio)", "type": "builtin",
                        "transport": "stdio", "enabled": True, "tools": len(TOOLS)})
    for s in mcp_cfg.get("custom_servers", []):
        servers.append({**s, "type": "custom"})
    return {"servers": servers, "count": len(servers)}

@app.post("/config/mcp-servers")
def add_mcp_server(server: MCPServer, admin: dict = Depends(require_admin)):
    mcp_cfg = config.mcp
    customs = mcp_cfg.get("custom_servers", [])
    existing = next((i for i, s in enumerate(customs) if s["name"] == server.name), None)
    entry = server.model_dump()
    if existing is not None: customs[existing] = entry
    else: customs.append(entry)
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
    except Exception as e:
        return {"success": False, "message": str(e), "url": server.url}


# Late import for /tools endpoint (avoids circular import)
from tools.tool_registry import SAP_SOURCES as SAP_SOURCES_REF  # noqa: E402


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api_server:app", host="0.0.0.0", port=8000, reload=True)
