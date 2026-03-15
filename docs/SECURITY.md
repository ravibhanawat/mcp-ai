# Security & Network Isolation Requirements

## Why This Document Exists

In 2024, researchers found **1,100+ Ollama instances exposed publicly** on the internet — many belonging to enterprise environments. Any exposed Ollama instance allows anyone to query your local LLMs and potentially extract SAP context from conversation history.

This document describes the required network configuration to deploy SAP AI Agent safely.

---

## Architecture: What Must Stay On-Premise

```
┌──────────────────────────────────────────────────────────────┐
│  Your On-Premise Network (Never leaves this boundary)        │
│                                                              │
│   ┌─────────────┐    RFC/BAPI    ┌─────────────────────┐    │
│   │   SAP ERP   │◄──────────────►│   SAP AI Agent      │    │
│   │  (ECC/S4H)  │               │   (FastAPI :8000)    │    │
│   └─────────────┘               └──────────┬──────────┘    │
│                                             │ localhost      │
│                                   ┌─────────▼─────────┐     │
│                                   │   Ollama / MLX     │     │
│                                   │   (:11434 / :8080) │     │
│                                   └───────────────────┘     │
└──────────────────────────────────────────────────────────────┘
         │
         │ HTTPS only (with JWT auth)
         ▼
    Your Internal Users / VPN
```

**The LLM (Ollama/MLX) must NEVER be reachable from outside your network.**

---

## Required Network Configuration

### 1. Bind Ollama to localhost only

By default Ollama listens on all interfaces. Restrict it:

```bash
# /etc/systemd/system/ollama.service (Linux)
[Service]
Environment="OLLAMA_HOST=127.0.0.1:11434"
```

```bash
# macOS launchd (~/Library/LaunchAgents/com.ollama.ollama.plist)
<key>OLLAMA_HOST</key>
<string>127.0.0.1:11434</string>
```

Verify: `curl http://0.0.0.0:11434/api/tags` should FAIL from any external host.

### 2. Firewall rules (Linux/iptables example)

```bash
# Block external access to Ollama port
iptables -A INPUT -p tcp --dport 11434 -s 127.0.0.1 -j ACCEPT
iptables -A INPUT -p tcp --dport 11434 -j DROP

# Block external access to MLX server
iptables -A INPUT -p tcp --dport 8080  -s 127.0.0.1 -j ACCEPT
iptables -A INPUT -p tcp --dport 8080  -j DROP
```

### 3. SAP AI Agent API (Port 8000)

- **Never expose port 8000 directly to the internet.**
- Place behind a reverse proxy (nginx/Caddy) with TLS termination.
- Restrict to VPN or internal network CIDR.

```nginx
# nginx example
server {
    listen 443 ssl;
    server_name sapai.internal.company.com;

    ssl_certificate     /etc/ssl/company.crt;
    ssl_certificate_key /etc/ssl/company.key;

    # Only allow internal subnet
    allow 10.0.0.0/8;
    deny  all;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### 4. SAP RFC/BAPI connections

- Use SAP SNC (Secure Network Communications) for RFC encryption.
- Use dedicated RFC user with minimal authorizations (S_RFC, S_TCODE for specific BAPIs only).
- Never use SAP client 000 or DDIC user for RFC connections.

---

## Environment Variable Checklist

| Variable | Required | Description |
|---|---|---|
| `JWT_SECRET_KEY` | **YES** | Random 256-bit key. Generate: `openssl rand -hex 32` |
| `DISABLE_AUTH` | No | Set to `true` for local dev only. Never in production. |
| `CORS_ORIGINS` | **YES** | Comma-separated list of allowed frontend origins. Not `*`. |
| `JWT_EXPIRE_HOURS` | No | Token lifetime (default: 8 hours) |
| `OLLAMA_HOST` | **YES** | Must be `127.0.0.1:11434` |

---

## Production Deployment Checklist

- [ ] Ollama bound to `127.0.0.1` only
- [ ] MLX server bound to `127.0.0.1` only
- [ ] `JWT_SECRET_KEY` set to a random 32-byte hex string
- [ ] `DISABLE_AUTH` not set (or explicitly `false`)
- [ ] `CORS_ORIGINS` set to specific frontend domain(s), not `*`
- [ ] Port 8000 behind TLS reverse proxy
- [ ] Port 8000 restricted to VPN / internal CIDR
- [ ] SAP RFC user has minimal authorizations
- [ ] SNC enabled for RFC connections
- [ ] Audit log files (`logs/audit_*.jsonl`) stored on write-once storage
- [ ] Audit logs retained for minimum 7 years (SOX requirement)
- [ ] `users.json` has file permissions `600` (owner read/write only)

---

## Data Classification

| Data Type | Classification | Notes |
|---|---|---|
| HR payroll (`get_payslip`) | **Highly Confidential** | Restricted to `hr_manager` role only |
| HR employee data | Confidential | `hr_manager` role |
| FI/CO financial data | Confidential | `fi_co_analyst` or `admin` |
| MM / SD / PP data | Internal | Module-specific roles |
| ABAP programs | Internal | `abap_developer` role |
| Audit logs | Highly Confidential | Admin access only. Retention: 7 years |

---

## Incident Response

If you suspect your Ollama instance was exposed:

1. Immediately bind Ollama to `127.0.0.1` and restart
2. Rotate all SAP RFC passwords and API tokens
3. Review audit logs in `logs/` for unexpected queries
4. Notify your SAP Basis team and Information Security team
5. Review SAP SM19/SM20 security audit log for anomalous RFC calls
