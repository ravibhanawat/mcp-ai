"""
SAP AI Agent - Configuration Manager
Persists all runtime settings to config.json in the project root.
Handles SAP connection, MCP servers, and Ollama settings.
"""
import json
import os
import stat
import copy
from typing import Any

CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")

DEFAULT_CONFIG: dict[str, Any] = {
    "sap": {
        "connection_type": "db",            # db | cloud | on_premise
        "system_url": "",                   # e.g. https://myXXXXXX.s4hana.ondemand.com
        "client": "100",                    # SAP client number
        "auth_type": "basic",               # basic | oauth2 | x509
        "username": "",
        "password": "",                     # stored as-is locally; never sent to browser
        "oauth_client_id": "",
        "oauth_client_secret": "",
        "oauth_token_url": "",
        "x509_cert_path": "",
        "verify_ssl": True,
        "timeout": 30,
    },
    "mcp": {
        "builtin_enabled": True,            # expose the built-in stdio MCP server
        "transport": "stdio",               # stdio | sse
        "sse_host": "127.0.0.1",
        "sse_port": 8001,
        "custom_servers": [],               # list of {name, url, transport, enabled}
    },
    "ollama": {
        "url": "http://localhost:11434",
        "default_model": "llama3.2",
    },
}

# Fields that must be masked when returned to the browser
_SENSITIVE = {"password", "oauth_client_secret", "oauth_token_url", "x509_cert_path"}


class ConfigManager:
    def __init__(self, config_file: str = CONFIG_FILE):
        self._path = config_file
        self._config = self._load()

    # ── I/O ──────────────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if os.path.exists(self._path):
            try:
                with open(self._path, "r") as f:
                    stored = json.load(f)
                # Deep-merge stored values on top of defaults (handles new keys)
                return self._merge(copy.deepcopy(DEFAULT_CONFIG), stored)
            except Exception:
                pass
        return copy.deepcopy(DEFAULT_CONFIG)

    def _save(self):
        with open(self._path, "w") as f:
            json.dump(self._config, f, indent=2)
        # Restrict to owner read/write only — config may contain SAP credentials
        os.chmod(self._path, stat.S_IRUSR | stat.S_IWUSR)

    @staticmethod
    def _merge(base: dict, override: dict) -> dict:
        for k, v in override.items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                ConfigManager._merge(base[k], v)
            else:
                base[k] = v
        return base

    # ── Public API ────────────────────────────────────────────────────────────

    def get(self) -> dict:
        """Return full config (including secrets — for internal use only)."""
        return copy.deepcopy(self._config)

    def get_safe(self) -> dict:
        """Return config with sensitive fields masked (safe to send to browser)."""
        safe = copy.deepcopy(self._config)
        for key in _SENSITIVE:
            if key in safe["sap"]:
                raw = safe["sap"][key]
                safe["sap"][key] = "••••••••" if raw else ""
        return safe

    def update(self, patch: dict):
        """
        Merge a partial config patch and persist.
        Passwords sent as '••••••••' (unchanged placeholder) are ignored.
        """
        # Guard: don't overwrite stored secrets with placeholder
        if "sap" in patch:
            for key in _SENSITIVE:
                if patch["sap"].get(key) == "••••••••":
                    patch["sap"].pop(key)

        self._config = self._merge(self._config, patch)
        self._save()

    # ── Convenience getters used by the backend ───────────────────────────────

    @property
    def ollama_url(self) -> str:
        return self._config["ollama"]["url"]

    @property
    def default_model(self) -> str:
        return self._config["ollama"]["default_model"]

    @property
    def sap(self) -> dict:
        return self._config["sap"]

    @property
    def mcp(self) -> dict:
        return self._config["mcp"]

    def is_mock_mode(self) -> bool:
        return self._config["sap"]["connection_type"] == "mock"

    # ── SAP Connection test (cloud/on-premise) ────────────────────────────────

    def test_sap_connection(self) -> dict:
        """
        Ping the SAP system URL to check reachability.
        For mock mode this always succeeds.
        For cloud/on-premise it attempts an HTTP HEAD request.
        """
        cfg = self._config["sap"]
        conn_type = cfg["connection_type"]

        if conn_type in ("mock", "db"):
            return {
                "success": True,
                "message": "Database mode — data is served from PostgreSQL. No direct SAP BAPI connection.",
                "connection_type": conn_type,
            }

        url = cfg.get("system_url", "").strip()
        if not url:
            return {"success": False, "message": "system_url is not configured."}

        try:
            import requests as _r
            ping_url = url.rstrip("/") + "/"
            resp = _r.head(
                ping_url,
                timeout=cfg.get("timeout", 10),
                verify=cfg.get("verify_ssl", True),
                allow_redirects=True,
            )
            if resp.status_code < 500:
                return {
                    "success": True,
                    "message": f"SAP system reachable — HTTP {resp.status_code}",
                    "connection_type": conn_type,
                    "url": url,
                }
            return {
                "success": False,
                "message": f"SAP system returned HTTP {resp.status_code}",
                "connection_type": conn_type,
            }
        except Exception as e:
            return {"success": False, "message": str(e), "connection_type": conn_type}


# Module-level singleton
config = ConfigManager()
