# Production deployment

The server refuses to start when a required control is missing, so most of this
checklist is enforced rather than advisory. Anything marked **enforced** aborts
the boot with a `FATAL:` line naming the problem.

---

## 1. Environment

```bash
APP_ENV=production                     # enforced: enables every check below
JWT_SECRET_KEY=<64 hex chars>          # enforced: python -c "import secrets;print(secrets.token_hex(32))"
JWT_REFRESH_SECRET=<64 hex chars>      # enforced: must differ from JWT_SECRET_KEY
CORS_ORIGINS=https://sap.example.com   # enforced: a literal * is rejected
TRUSTED_PROXY_IPS=10.0.0.4             # peers allowed to set X-Forwarded-For
HOST=127.0.0.1                         # bind loopback; let the proxy face the network
DB_SSLMODE=require                     # default outside development
```

`DISABLE_AUTH=true` aborts the boot outside development. So does any account
still using a password that was published in this repository.

### Row scoping

```bash
TENANCY_MODEL=database                 # database (default) | column
RECORD_SCOPING=off                     # off (default) | owner
```

`TENANCY_MODEL=database` means one database per company — the model SAP Business
One itself uses, and the recommended one. Cross-company access is then prevented
by the connection, not by a query filter that can be forgotten.

`TENANCY_MODEL=column` keeps one database and filters every query by
`tenant_id`. It **fails closed**: if no tenant is bound to the request, the
predicate becomes `1=0` and no rows are returned.

`RECORD_SCOPING=owner` restricts rows to the user who owns them (a salesperson
sees their own customers). It requires the columns added by
`scripts/add_row_scoping.sql`, **and a backfill** — a NULL `owner_id` matches
nobody outside `UNSCOPED_ROLES`. Enabling it without the schema is **enforced**:
the server names the tables it cannot scope and refuses to start.

---

## 2. First run

```bash
psql -U sap_agent -d sap_agent -f db/schema.sql
python scripts/setup_admin.py          # required: accounts ship with no password
```

Default accounts are created with `must_set_password: true` and no hash. They
cannot be used until an administrator sets a password. Passwords must be ≥10
characters with upper, lower, digit and symbol.

---

## 3. Run

```bash
TRUSTED_PROXY_IPS=10.0.0.4 ./scripts/start_prod.sh
```

Terminate TLS at the proxy. The application emits HSTS, `X-Frame-Options`,
`X-Content-Type-Options`, `Referrer-Policy` and `Permissions-Policy` on every
response, but HSTS only means something over TLS.

Set `REDIS_URL` if you run more than one worker: account lockout and rate-limit
counters fall back to per-process state without it, which multiplies the
effective limits by the worker count.

---

## 4. Authorization model

Four independent layers. All are enforced in the backend, below the model — the
LLM is never the authority for any of them.

| Layer | Where | What it decides |
|---|---|---|
| Module | `auth/rbac.py` | Which tools a role may call at all |
| Operation | `core/authorization.py` | Whether the role may write, not just read |
| Confirmation | `tools/tool_registry.py` | Whether a write executes yet |
| Field | `core/authorization.py` | Which columns come back |
| Row | `core/scoping.py` | Which rows come back |

**Confirmation.** A write returns `CONFIRMATION_REQUIRED` with a `confirm_token`
instead of executing. The token is an HMAC over (user, tool, parameters) with a
5-minute TTL, so it cannot be replayed by another user or reused for different
parameters. The client re-sends the request with `confirm_token` to execute.
`CONFIRM_TOKEN_TTL` tunes the window.

**MCP keys carry roles.** Create them scoped:

```bash
curl -X POST /mcp/keys -H "Authorization: Bearer <admin>" \
     -d '{"label":"acme-laptop","roles":["fi_co_analyst"]}'
```

A key with no roles specified gets `read_only`, which grants documentation
lookup and no customer data.

---

## 5. Data residency

Local models keep everything on your network. Cloud fallback (`OPENAI_API_KEY` /
`ANTHROPIC_API_KEY`) strips SAP tool payloads before transmission — verified —
but **the user's question text still leaves the building**. Leave both unset
unless the customer has accepted that, and point them at the audit record every
fallback writes.

---

## 6. Verify the deployment

```bash
python -m pytest tests/ -q          # 152 tests: auth, RBAC, isolation, injection, posture
python tests/qa_master.py           # 802 adversarial authorization tests, prints a release decision
```

`qa_master.py` prints `SAFE FOR PRODUCTION` or `NOT SAFE FOR PRODUCTION` with the
failing control categories. Run it against the deployed configuration, not just
in development — several checks read the live environment.

---

## 7. Known limits

Be direct about these with customers; they will find them.

- **No SAP connection.** All 46 tools query a local PostgreSQL schema modelled on
  S/4HANA table names. `connection_type` is `db`. A Business One connector
  (HANA/SQL Server reads, Service Layer writes) is not built.
- **Record scoping ships off.** Turning it on needs an ownership rule for your
  business and a backfill; the mechanism is ready, the data is not.
- **No backup tooling** in this repository. Use your standard PostgreSQL backup
  and state an RPO/RTO before signing anything.
