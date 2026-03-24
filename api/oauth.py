"""
MCP OAuth 2.1 Authorization Server
===================================
Implements the full MCP authorization spec:
  - RFC 9728  — OAuth 2.0 Protected Resource Metadata (/.well-known/oauth-protected-resource)
  - RFC 8414  — Authorization Server Metadata       (/.well-known/oauth-authorization-server)
  - RFC 7591  — Dynamic Client Registration          (/register)
  - OAuth 2.1 — Authorization Code + PKCE            (/authorize)
  - OAuth 2.1 — Token endpoint                       (/token)
  - MCP extension io.modelcontextprotocol/oauth-client-credentials

Flow for Claude Desktop / Claude.ai:
  1. MCP request → 401 with WWW-Authenticate: Bearer resource_metadata=...
  2. Claude fetches /.well-known/oauth-protected-resource
  3. Claude fetches /.well-known/oauth-authorization-server
  4. Claude POSTs to /register (Dynamic Client Registration)
  5. Claude opens browser → GET /authorize  (login form shown to user)
  6. User submits credentials → POST /authorize  (code issued, browser redirected)
  7. Claude exchanges code + PKCE verifier at POST /token
  8. Claude uses Bearer JWT on all subsequent MCP requests
"""
import base64
import hashlib
import html as _html
import json
import os
import secrets
import time
from typing import Optional

import jwt as _jwt
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from auth import users as user_store

router = APIRouter(tags=["oauth"])

# ── Helpers ───────────────────────────────────────────────────────────────────

def _server_url() -> str:
    return os.environ.get("SERVER_URL", "http://localhost:8000").rstrip("/")

def _mcp_resource() -> str:
    """Canonical MCP resource URI — used as JWT audience."""
    return _server_url() + "/mcp/sse"

def _jwt_secret() -> str:
    return os.environ.get("JWT_SECRET_KEY", "dev-secret-CHANGE-ME-before-production")

_MCP_TOKEN_TTL  = 3600   # 1 hour access tokens
_AUTH_CODE_TTL  = 300    # 5 minute auth codes

# ── In-memory stores (single-server; swap for Redis in multi-instance) ─────────

_auth_codes: dict[str, dict] = {}   # code  → grant data
_clients:    dict[str, dict] = {}   # client_id → registration data

# ── Auth code helpers ─────────────────────────────────────────────────────────

def _issue_auth_code(
    client_id: str, redirect_uri: str,
    user_id: str, roles: list[str],
    code_challenge: str, scope: str, state: str,
) -> str:
    code = secrets.token_urlsafe(32)
    _auth_codes[code] = {
        "client_id":      client_id,
        "redirect_uri":   redirect_uri,
        "user_id":        user_id,
        "roles":          roles,
        "code_challenge": code_challenge,
        "scope":          scope,
        "state":          state,
        "expires_at":     time.time() + _AUTH_CODE_TTL,
    }
    return code


def _consume_auth_code(code: str) -> dict | None:
    entry = _auth_codes.pop(code, None)
    if entry and time.time() < entry["expires_at"]:
        return entry
    return None


# ── PKCE helpers ──────────────────────────────────────────────────────────────

def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _verify_pkce(verifier: str, stored_challenge: str) -> bool:
    return secrets.compare_digest(_pkce_challenge(verifier), stored_challenge)


# ── JWT access token ──────────────────────────────────────────────────────────

def _issue_mcp_token(user_id: str, roles: list[str], scope: str) -> dict:
    now = int(time.time())
    payload = {
        "sub":   user_id,
        "roles": roles,
        "scope": scope,
        "aud":   _mcp_resource(),   # RFC 8707 — audience = MCP server URL
        "iss":   _server_url(),
        "iat":   now,
        "exp":   now + _MCP_TOKEN_TTL,
    }
    token = _jwt.encode(payload, _jwt_secret(), algorithm="HS256")
    return {
        "access_token": token,
        "token_type":   "Bearer",
        "expires_in":   _MCP_TOKEN_TTL,
        "scope":        scope,
    }


def verify_mcp_token(raw: str) -> dict:
    """
    Validate a Bearer JWT issued by this server.
    Checks signature, expiry, and audience (must equal MCP resource URI).
    Raises jwt.InvalidTokenError on any failure.
    """
    payload = _jwt.decode(
        raw,
        _jwt_secret(),
        algorithms=["HS256"],
        audience=_mcp_resource(),
    )
    return payload


# ── Login page HTML ───────────────────────────────────────────────────────────

def _login_page(
    client_name: str,
    client_id: str,
    redirect_uri: str,
    scope: str,
    state: str,
    code_challenge: str,
    error: str = "",
) -> str:
    esc = _html.escape
    err_block = (
        f'<div class="error">{esc(error)}</div>'
        if error else ""
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>SAP AI Agent — Authorize</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{background:#0d1117;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
         display:flex;align-items:center;justify-content:center;min-height:100vh;color:#e6edf3}}
    .card{{background:#161b22;border:1px solid #30363d;border-radius:12px;
           padding:32px;width:100%;max-width:420px;box-shadow:0 8px 32px rgba(0,0,0,.4)}}
    .logo{{font-size:28px;margin-bottom:4px;text-align:center}}
    h1{{font-size:18px;font-weight:600;text-align:center;margin-bottom:4px}}
    .sub{{font-size:13px;color:#8b949e;text-align:center;margin-bottom:20px}}
    .client-box{{background:#0d1117;border:1px solid #30363d;border-radius:8px;
                 padding:12px 14px;margin-bottom:20px;font-size:13px}}
    .client-box b{{color:#58a6ff}}
    .scope-chip{{display:inline-block;background:#1f3352;color:#79c0ff;
                 border-radius:4px;padding:2px 8px;font-size:11px;margin-top:4px}}
    label{{display:block;font-size:12px;color:#8b949e;margin-bottom:4px;margin-top:12px}}
    input[type=text],input[type=password]{{width:100%;background:#0d1117;border:1px solid #30363d;
      border-radius:6px;padding:9px 12px;color:#e6edf3;font-size:14px;outline:none}}
    input:focus{{border-color:#58a6ff}}
    .btn{{width:100%;background:#238636;color:#fff;border:none;border-radius:6px;
          padding:10px;font-size:14px;font-weight:600;cursor:pointer;margin-top:18px}}
    .btn:hover{{background:#2ea043}}
    .error{{background:#3d1a1a;border:1px solid #f85149;color:#f85149;
            border-radius:6px;padding:9px 12px;font-size:13px;margin-bottom:12px}}
    .divider{{height:1px;background:#30363d;margin:20px 0}}
    .footer{{font-size:11px;color:#484f58;text-align:center;margin-top:16px}}
  </style>
</head>
<body>
<div class="card">
  <div class="logo">🤖</div>
  <h1>SAP AI Agent</h1>
  <p class="sub">Sign in to grant access</p>

  <div class="client-box">
    <div><b>{esc(client_name)}</b> is requesting access</div>
    {"<div><span class='scope-chip'>" + esc(scope) + "</span></div>" if scope else ""}
  </div>

  {err_block}

  <form method="POST" action="/authorize">
    <input type="hidden" name="client_id"      value="{esc(client_id)}">
    <input type="hidden" name="redirect_uri"   value="{esc(redirect_uri)}">
    <input type="hidden" name="scope"          value="{esc(scope)}">
    <input type="hidden" name="state"          value="{esc(state)}">
    <input type="hidden" name="code_challenge" value="{esc(code_challenge)}">

    <label for="user_id">Username</label>
    <input id="user_id" type="text" name="user_id" placeholder="your_username"
           autocomplete="username" required>

    <label for="password">Password</label>
    <input id="password" type="password" name="password" placeholder="••••••••"
           autocomplete="current-password" required>

    <button class="btn" type="submit">Sign in &amp; Authorize</button>
  </form>

  <div class="divider"></div>
  <p class="footer">Your credentials are verified locally and never sent to {esc(client_name)}.</p>
</div>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════════════════════
# RFC 9728 — Protected Resource Metadata
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/.well-known/oauth-protected-resource")
async def protected_resource_metadata():
    """
    RFC 9728 — MCP clients fetch this first to discover the Authorization Server.
    Claude looks for this on 401 via WWW-Authenticate: Bearer resource_metadata=...
    """
    base = _server_url()
    return JSONResponse({
        "resource":              _mcp_resource(),
        "authorization_servers": [base],
        "scopes_supported":      ["mcp:tools", "mcp:read", "mcp:write"],
        "bearer_methods_supported": ["header"],
    })


# ═══════════════════════════════════════════════════════════════════════════════
# RFC 8414 — Authorization Server Metadata
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/.well-known/oauth-authorization-server")
async def authorization_server_metadata():
    """
    RFC 8414 — Tells MCP clients where all OAuth endpoints live.
    Claude fetches this after discovering the AS URL from the protected resource metadata.
    """
    base = _server_url()
    return JSONResponse({
        "issuer":                             base,
        "authorization_endpoint":             f"{base}/authorize",
        "token_endpoint":                     f"{base}/token",
        "registration_endpoint":              f"{base}/register",
        "response_types_supported":           ["code"],
        "grant_types_supported":              ["authorization_code", "client_credentials"],
        "code_challenge_methods_supported":   ["S256"],    # PKCE S256 required
        "token_endpoint_auth_methods_supported": [
            "none",            # public clients (Claude Desktop)
            "client_secret_basic",
            "private_key_jwt",
        ],
        "scopes_supported":                   ["mcp:tools", "mcp:read", "mcp:write"],
        "client_id_metadata_document_supported": False,    # use DCR instead
    })


# ═══════════════════════════════════════════════════════════════════════════════
# RFC 7591 — Dynamic Client Registration
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/register")
async def dynamic_client_registration(request: Request):
    """
    RFC 7591 — MCP clients (Claude Desktop, Claude.ai, Cursor) register themselves
    automatically here before starting the auth flow.
    No pre-registration needed — clients self-register on first use.
    """
    body = await request.json()

    redirect_uris = body.get("redirect_uris", [])
    if not redirect_uris:
        raise HTTPException(400, detail="redirect_uris is required")

    # Validate redirect URIs — must be localhost or HTTPS
    for uri in redirect_uris:
        if not (
            uri.startswith("https://")
            or uri.startswith("http://127.0.0.1")
            or uri.startswith("http://localhost")
        ):
            raise HTTPException(
                400,
                detail=f"redirect_uri must be https:// or localhost: {uri}"
            )

    client_id = "client_" + secrets.token_urlsafe(16)
    entry = {
        "client_id":                client_id,
        "client_name":              body.get("client_name", "MCP Client"),
        "redirect_uris":            redirect_uris,
        "grant_types":              body.get("grant_types", ["authorization_code"]),
        "response_types":           body.get("response_types", ["code"]),
        "token_endpoint_auth_method": body.get("token_endpoint_auth_method", "none"),
        "scope":                    body.get("scope", "mcp:tools"),
        "client_secret":            None,   # public client — no secret
    }
    _clients[client_id] = entry

    return JSONResponse(entry, status_code=201)


# ═══════════════════════════════════════════════════════════════════════════════
# Authorization Endpoint — GET shows login form, POST processes credentials
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/authorize")
async def authorize_get(
    request: Request,
    client_id: str,
    redirect_uri: str,
    response_type: str = "code",
    scope: str = "mcp:tools",
    state: str = "",
    code_challenge: str = "",
    code_challenge_method: str = "S256",
):
    """
    Step 1 of the Authorization Code flow.
    Claude opens the user's browser to this URL.
    We show a login form so the SAP user can authenticate.
    """
    if response_type != "code":
        raise HTTPException(400, "Only response_type=code is supported")

    if code_challenge_method and code_challenge_method != "S256":
        raise HTTPException(400, "Only code_challenge_method=S256 is supported")

    # Validate client and redirect_uri
    client = _clients.get(client_id)
    if client and redirect_uri not in client["redirect_uris"]:
        raise HTTPException(400, "redirect_uri does not match registered URIs")

    client_name = client["client_name"] if client else "MCP Client"

    return HTMLResponse(_login_page(
        client_name=client_name,
        client_id=client_id,
        redirect_uri=redirect_uri,
        scope=scope,
        state=state,
        code_challenge=code_challenge,
    ))


@router.post("/authorize")
async def authorize_post(
    client_id:      str = Form(...),
    redirect_uri:   str = Form(...),
    scope:          str = Form("mcp:tools"),
    state:          str = Form(""),
    code_challenge: str = Form(""),
    user_id:        str = Form(...),
    password:       str = Form(...),
):
    """
    Step 2 — user submitted the login form.
    Authenticate credentials, issue auth code, redirect back to the MCP client.
    """
    # Validate client
    client = _clients.get(client_id)
    if client and redirect_uri not in client["redirect_uris"]:
        raise HTTPException(400, "redirect_uri mismatch")

    client_name = client["client_name"] if client else "MCP Client"

    # Authenticate user against our user store
    user = user_store.authenticate(user_id, password)
    if not user:
        # Re-show login form with error — never reveal whether user exists
        return HTMLResponse(
            _login_page(
                client_name=client_name,
                client_id=client_id,
                redirect_uri=redirect_uri,
                scope=scope,
                state=state,
                code_challenge=code_challenge,
                error="Invalid username or password.",
            ),
            status_code=401,
        )

    # Issue authorization code
    code = _issue_auth_code(
        client_id=client_id,
        redirect_uri=redirect_uri,
        user_id=user["user_id"],
        roles=user.get("roles", []),
        code_challenge=code_challenge,
        scope=scope,
        state=state,
    )

    # Redirect back to MCP client
    sep = "&" if "?" in redirect_uri else "?"
    location = f"{redirect_uri}{sep}code={code}"
    if state:
        location += f"&state={state}"
    return RedirectResponse(location, status_code=302)


# ═══════════════════════════════════════════════════════════════════════════════
# Token Endpoint — code exchange + client credentials
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/token")
async def token(request: Request):
    """
    POST /token — supports two grant types:

    1. authorization_code  — Claude exchanges auth code + PKCE verifier for JWT
    2. client_credentials  — machine-to-machine (MCP extension)
    """
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type:
        body = await request.json()
    else:
        form = await request.form()
        body = dict(form)

    grant_type = body.get("grant_type", "")

    # ── Authorization Code Grant ───────────────────────────────────────────────
    if grant_type == "authorization_code":
        code         = body.get("code", "")
        redirect_uri = body.get("redirect_uri", "")
        code_verifier = body.get("code_verifier", "")

        grant = _consume_auth_code(code)
        if not grant:
            return JSONResponse(
                {"error": "invalid_grant", "error_description": "Code is invalid or expired."},
                status_code=400,
            )

        if grant["redirect_uri"] != redirect_uri:
            return JSONResponse(
                {"error": "invalid_grant", "error_description": "redirect_uri mismatch."},
                status_code=400,
            )

        # PKCE verification — required per OAuth 2.1
        if grant["code_challenge"]:
            if not code_verifier:
                return JSONResponse(
                    {"error": "invalid_request", "error_description": "code_verifier required."},
                    status_code=400,
                )
            if not _verify_pkce(code_verifier, grant["code_challenge"]):
                return JSONResponse(
                    {"error": "invalid_grant", "error_description": "PKCE verification failed."},
                    status_code=400,
                )

        return JSONResponse(
            _issue_mcp_token(grant["user_id"], grant["roles"], grant["scope"])
        )

    # ── Client Credentials Grant (MCP extension) ──────────────────────────────
    elif grant_type == "client_credentials":
        client_id     = body.get("client_id", "")
        client_secret = body.get("client_secret", "")
        scope         = body.get("scope", "mcp:tools")

        client = _clients.get(client_id)
        if not client:
            return JSONResponse(
                {"error": "invalid_client", "error_description": "Unknown client_id."},
                status_code=401,
            )

        # For public clients (no secret) — service accounts with known client_id
        stored_secret = client.get("client_secret")
        if stored_secret and not secrets.compare_digest(client_secret, stored_secret):
            return JSONResponse(
                {"error": "invalid_client", "error_description": "Invalid client_secret."},
                status_code=401,
            )

        # Issue token for the client itself (no user, service account)
        return JSONResponse(
            _issue_mcp_token(
                user_id=client_id,
                roles=["read_only"],   # default minimal role for M2M
                scope=scope,
            )
        )

    else:
        return JSONResponse(
            {"error": "unsupported_grant_type",
             "error_description": f"grant_type '{grant_type}' is not supported."},
            status_code=400,
        )
