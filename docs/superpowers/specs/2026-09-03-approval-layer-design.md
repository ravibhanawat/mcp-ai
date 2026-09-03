# Human-in-the-Loop Approval Layer for SAP Writes — Design

**Date:** 2026-09-03
**Status:** Approved for planning
**Scope:** All six write tools — sales orders, production orders, leave, receipts (park + post), broker POs

---

## 1. Problem

Every SAP write in this product executes the moment the requester confirms it.
`core/authorization.py` gates writes behind a confirmation token, but that token
is minted for, and consumed by, **the same person who asked**. It proves intent.
It does not prove authority. A `sd_analyst` can create a ₹50 lakh sales order
against a customer's credit limit, and a `re_analyst` can post a receipt to FI,
with nobody else in the loop.

This design inserts an approval stage between intent and execution: the LLM
proposes, a deterministic policy engine decides who must sign, and a separate
executor calls SAP only after they have. Reads are untouched.

Three facts about the existing codebase shape the design more than anything in
the original requirement:

* **The choke point already exists.** `tools/tool_registry.execute_tool()` is
  the single path every caller shares — `/chat`, `/chat/stream`, MCP at
  `api/server.py:2065`, the report agent, auto-research. Gating there covers
  all of them; gating in the API layer would leave MCP open.

* **The amount is not in the tool parameters.** `create_sales_order(customer_id,
  material_id, qty, delivery_days)` derives its value from `materials.price ×
  qty` *inside* `modules/sd.py:110`. `initiate_broker_po(broker_id,
  unit_number)` reads `payout_amount` off the booking row. A threshold rule of
  the form "sales_order.amount < 50,000 → auto" therefore cannot be evaluated
  from the payload alone. Resolving the amount by read-only lookup, before the
  write, is a required component — not an implementation detail.

* **Write functions signal failure by return value, not exception.** They return
  `{"status": "ERROR", "message": ...}`. The executor must treat a non-`OK`
  status as a failed execution, or every rejected write would be recorded as a
  success.

## 2. Decisions taken

| Question | Decision |
|---|---|
| Approver notification | In-app inbox in the existing React app, plus HMAC-signed outbound webhooks on every state change. No Slack or SMTP dependency; a relay can be pointed at the webhook. |
| Approver identity | New first-class approver roles in `auth/rbac.py`, assigned in `users.json`. Routing is by role. |
| Existing confirmation gate | Retained. Confirming a draft **submits** it. Policy then auto-executes it or queues it. The existing `confirm_token` round-trip and its tests keep working. |
| Receipts | **Both** `park_customer_receipt` and `post_customer_receipt` go through approval. |

Two corrections to the original requirement, made while reading the code:

* **`assert_safe_outbound_url()` is not reusable for outbound webhooks.** It
  refuses every private, loopback and link-local address, because it guards a
  *caller-supplied* URL at `/config/test-mcp` and exists to stop internal port
  scanning. The approval webhook target is *operator-supplied* via environment
  variable, and an on-premise CPI tenant is routinely on a private network.
  `core/approvals/webhooks.py` gets its own check: scheme must be `http`/`https`,
  private addresses refused **unless** `APPROVAL_WEBHOOK_ALLOW_PRIVATE=true`. It
  raises `ValueError`, not `HTTPException`, because it runs in a background task.
  `/config/test-mcp` keeps the strict guard unchanged.

* **The agent's tool-call protocol does not change.** The requirement proposed
  switching the model to emitting approval-draft JSON. This codebase's agent
  already emits `{"tool_call": {...}}`, and the gate turns that into a draft in
  code. Rewriting the protocol would be a large, risky change to
  `agent/sap_agent.py` that buys nothing the code gate does not already
  guarantee — and the guarantee would then depend on the model complying.

## 3. Architecture

```
User → Agent (LLM) → execute_tool()
                         │
                         ├─ confirmation_required()   ← unchanged; now carries the resolved draft
                         │
                         └─ approvals.gate.intercept()
                                  │
                              resolvers ──→ read-only SAP lookups (amount, counterparties, risk)
                                  │
                              policy.evaluate()  ← policy_rules.json, deterministic
                                  │
                    ┌─────────────┴─────────────┐
                 auto tier                  pending
                    │                           │
            execute inline              approval_requests row
            + record row                       │
                                        Approvals inbox (React) / webhook out
                                               │
                                     approve · reject · edit
                                               │
                                        approvals.executor
                                          (atomic claim,
                                           revalidate,
                                           FUNCTION_MAP call)
                                               │
                                     sap_doc_number ─→ webhook out
```

### 3.1 Modules

New package `core/approvals/`:

| Module | Responsibility | Depends on |
|---|---|---|
| `schema.py` | Idempotent DDL, applied at startup. Follows the flat-statement-list pattern of `ai/schema.py` and `db/activity_log.py`; the project has no migration framework. | `db.connection` |
| `store.py` | All SQL for the three tables. The only module that writes them. | `db.connection` |
| `resolvers.py` | Per-action read-only lookup → measures, context, risk flags, blocking reasons. | `db.connection` |
| `policy.py` | Pure function: `(action, measures, risk_flags, roles) → Decision`. No I/O, no DB. | `policy_rules.json` |
| `gate.py` | The interception called from `execute_tool()`. Also `record_auto()`. | resolvers, policy, store |
| `executor.py` | Claims, revalidates and executes an approved request. Extracts the doc number. | store, resolvers, `tool_registry` |
| `webhooks.py` | Outbound HMAC emitter, delivery rows, backoff. Inbound signature verification. | store |
| `escalation.py` | The 60-second sweeper: SLA escalation, delivery retry, hard expiry. | store, webhooks, executor |

`policy.py` having no I/O is deliberate — it is the component whose behaviour
must be exhaustively testable, and a table-driven suite over pure inputs is the
cheapest way to get that.

## 4. Data model

Three tables, appended to `db/schema.sql` in its existing style and created at
startup by `core/approvals/schema.py`.

### 4.1 `approval_requests`

```sql
CREATE TABLE IF NOT EXISTS approval_requests (
    request_id       VARCHAR(24)   PRIMARY KEY,          -- apr_<16 hex>
    action           VARCHAR(64)   NOT NULL,             -- tool name
    entity_type      VARCHAR(32)   NOT NULL,             -- sales_order | production_order | leave | receipt | broker_po
    payload          JSONB         NOT NULL,             -- canonical tool arguments
    context          JSONB         NOT NULL DEFAULT '{}'::jsonb,   -- resolver output: names, balances, limits
    measures         JSONB         NOT NULL DEFAULT '{}'::jsonb,   -- amount / days / qty — what tiers key on
    amount           DECIMAL(18,2),                      -- denormalised from measures for indexing and display
    currency         CHAR(3)       DEFAULT 'INR',
    summary          TEXT          NOT NULL,
    risk_flags       JSONB         NOT NULL DEFAULT '[]'::jsonb,
    requested_by     VARCHAR(64)   NOT NULL,
    requester_roles  JSONB         NOT NULL DEFAULT '[]'::jsonb,
    approval_chain   JSONB         NOT NULL DEFAULT '[]'::jsonb,   -- ordered [{role, escalate_to, sla_hours}]
    chain_index      SMALLINT      NOT NULL DEFAULT 0,
    approver_role    VARCHAR(48),                        -- chain[chain_index].role, denormalised for the inbox query
    status           VARCHAR(16)   NOT NULL,             -- pending|approved|executing|executed|rejected|failed|expired|superseded
    decided_by       VARCHAR(64),
    decided_at       TIMESTAMPTZ,
    decision_comment TEXT,
    sap_doc_number   VARCHAR(32),
    sap_doc_field    VARCHAR(32),                        -- which key it came from
    sap_doc_status   VARCHAR(20),                        -- set by the inbound SAP status webhook
    error            TEXT,
    idempotency_key  VARCHAR(64)   NOT NULL UNIQUE,   -- uuid4 hex, minted at creation
    sla_due_at       TIMESTAMPTZ,
    expires_at       TIMESTAMPTZ,                        -- hard TTL
    session_id       VARCHAR(128),                       -- so chat can surface the outcome
    supersedes       VARCHAR(24),
    superseded_by    VARCHAR(24),
    created_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);
```

There are two distinct idempotency keys and they must not be confused. The one
on `approval_requests` is minted by this server at creation (uuid4 hex) and
identifies the request to external systems. The one on `approval_events` is
supplied by the *caller* of an inbound decision webhook and deduplicates that
caller's retries. A client cannot influence the former.

Indexes: `(status, approver_role, created_at DESC)` for the inbox,
`(requested_by, created_at DESC)` for "my requests", `(status, sla_due_at)` for
the sweeper, GIN on `payload`.

`approval_chain` carries the whole ordered chain rather than a single
`approver_role`, because two of the six actions genuinely need more than one
signature — `initiate_broker_po` already advertises `release_levels: 2` and
"Pending Level-1 release by Finance Manager" in its own return value at
`modules/sd.py:544`.

**Chain versus escalation.** These are different mechanisms and the schema keeps
them separate. A *chain entry* is a signature that must be collected. An
*escalation* is what happens when one entry's SLA expires: `escalate_to`
replaces the role on that same entry, the SLA resets, and the number of required
signatures does not change.

### 4.2 `approval_events`

Append-only trail: `event_id`, `request_id`, `event` (requested, level_approved,
approved, rejected, edited, escalated, executed, failed, expired), `actor`,
`comment`, `payload_before`/`payload_after` for edits, `idempotency_key`,
`created_at`. Unique index on `(request_id, idempotency_key)` — this is what
makes a retried inbound decision webhook a no-op rather than a second decision.

### 4.3 `approval_deliveries`

Outbound webhook state: `delivery_id`, `request_id`, `event`, `url`,
`body`, `attempts`, `next_attempt_at`, `status` (pending|delivered|failed),
`last_error`, `response_code`. Durable so a webhook is not lost when the
receiver is down, and retried by the same sweeper that handles escalation.

## 5. Resolvers

Each action has a resolver that runs **before** the write and returns
`measures`, `context`, `risk_flags` and `blocking`. All queries are reads.

| Action | Measures | Context | Risk flags | Blocking |
|---|---|---|---|---|
| `create_sales_order` | `amount = materials.price × qty` | customer name, material description, credit limit, unit price | `over_credit_limit`, `new_customer` | customer inactive/absent, material absent |
| `create_production_order` | `qty`, `amount = materials.price × qty` (standard-cost proxy) | material, work centre, plant | `work_center_maintenance` | material absent, work centre absent or under maintenance |
| `apply_leave` | `days` | employee name, entitled, used, balance | `exceeds_half_balance` | invalid leave type, no balance record, `days > balance` |
| `park_customer_receipt` | `amount` | customer, unit, allocation preview, excess | `excess_basic`, `excess_tds` | customer/unit absent, nothing to allocate against |
| `post_customer_receipt` | `amount` from `customer_receipts.amount` | park ref, payment mode, allocation lines | `large_excess` | park ref absent, already `POSTED` |
| `initiate_broker_po` | `amount = payout_amount` | broker, customer, unit, `collected_pct` | `low_collection_margin` | `collected_pct < 20`, PO already created |

**Blocking reasons never become approval requests.** If a resolver reports one,
the gate returns an ordinary `{"status": "ERROR", "message": ...}` and no row is
written. This is the requirement's "validate before submitting" step, enforced
in code instead of in the prompt: an approver is never asked to sign something
that is guaranteed to fail, and the queue does not fill with garbage.

Resolvers are also used on the **confirmation** path, so the
`CONFIRMATION_REQUIRED` payload gains `draft: {amount, currency, summary,
risk_flags, would_route_to}`. The requester sees "₹4,20,000 — will need
sales_manager" before confirming, rather than after.

## 6. Policy engine

Deterministic, pure, and loaded from `core/approvals/policy_rules.json`
(overridable by `APPROVALS_POLICY_PATH`). Never from the system prompt, never
reachable by the model, so thresholds cannot be argued around.

```json
{
  "version": 1,
  "currency": "INR",
  "allow_self_approval": false,
  "hard_ttl_hours": 72,
  "revalidation": { "amount_tolerance_pct": 0.0 },
  "actions": {
    "create_sales_order": {
      "entity_type": "sales_order",
      "measure": "amount",
      "tiers": [
        { "max": 50000,  "chain": [] },
        { "max": 500000, "chain": [{ "role": "sales_manager", "escalate_to": "cfo", "sla_hours": 8 }] },
        { "max": null,   "chain": [{ "role": "sales_manager", "escalate_to": "cfo", "sla_hours": 8 },
                                   { "role": "cfo", "sla_hours": 24 }] }
      ],
      "risk_escalations": { "over_credit_limit": ["cfo"] }
    }
  }
}
```

`measure` names which resolver output the tiers key on, so `apply_leave` keys on
`days` and everything else on `amount` through the same engine with no
special-casing. An empty `chain` is the auto tier. `risk_escalations` append
roles to the chain regardless of amount.

Defaults to ship (all tunable in the JSON, all INR):

| Action | Auto | Then | Then |
|---|---|---|---|
| `create_sales_order` | ≤ 50,000 | ≤ 5,00,000 → `sales_manager` | → `sales_manager`, `cfo` |
| `create_production_order` | ≤ 1,00,000 | ≤ 10,00,000 → `plant_manager` | > 10,00,000 → `plant_manager`, `cfo` |
| `apply_leave` | ≤ 3 days | ≤ 10 days → `hr_approver` | > 10 days → `hr_approver`, `cfo` |
| `park_customer_receipt` | — none | ≤ 5,00,000 → `finance_manager` | → `finance_manager`, `cfo` |
| `post_customer_receipt` | — none | ≤ 5,00,000 → `finance_manager` | → `finance_manager`, `cfo` |
| `initiate_broker_po` | — none | always → `finance_manager`, `cfo` | (matches `release_levels: 2`) |

Receipts have no auto tier because both park and post were explicitly placed
under approval. The auto tier is a one-line addition to the JSON if that proves
too heavy in practice; this is recorded here so the knob is findable.

## 7. Execution

`executor.execute(request_id)` runs as a FastAPI background task:

1. **Claim atomically.** `UPDATE approval_requests SET status='executing',
   updated_at=NOW() WHERE request_id=%s AND status='approved'`. A rowcount of 1
   means this worker owns the execution. Nothing reads the status and then acts
   on it — that race is what double-posts a receipt.
2. **Revalidate.** Re-run the resolver. If a blocking reason has appeared, or
   the measure has drifted beyond `revalidation.amount_tolerance_pct`, mark
   `failed` with `revalidation_failed` and emit. The world moves between
   approval and execution — stock is consumed, a receipt is posted by someone
   else, a price changes — and executing a payload whose value no longer matches
   what was signed is exactly the failure this whole layer exists to prevent.
3. **Execute** through `execute_tool()` with a bypass context variable set, so
   both `confirmation_required()` and `gate.intercept()` stand aside and
   `sap_source` attribution is still injected.
4. **Record.** `status != "OK"` is a failure. On success, extract the document
   number by action:

   | Action | Field |
   |---|---|
   | `create_sales_order` | `order_id` |
   | `create_production_order` | `order_id` |
   | `apply_leave` | `application_id` |
   | `park_customer_receipt` | `park_reference` |
   | `post_customer_receipt` | `fi_doc_no` |
   | `initiate_broker_po` | `po_number` |

5. **Emit** `approval.executed` or `approval.failed`.

The auto tier does not go through the executor. `gate.intercept()` returns
`None`, `execute_tool()` runs inline as it does today, and
`gate.record_auto()` — called immediately after a successful call — writes the
row with `status='executed'` from a draft stashed on a context variable. The
fast path stays fast and the chat still shows the SAP document immediately,
while the audit trail still contains every write.

## 8. API surface

### 8.1 Inbox (JWT, `get_current_user`)

New router `api/routes_approvals.py`, mounted alongside the AI admin routers.

| Route | Purpose |
|---|---|
| `GET /approvals` | Inbox. `scope=inbox` (status pending and `approver_role` ∈ my roles), `scope=mine` (`requested_by` = me), `scope=all` (admin). Filters on status, action, date. Paginated. |
| `GET /approvals/{id}` | Full request with its event trail. |
| `POST /approvals/{id}/approve` | `{comment}`. |
| `POST /approvals/{id}/reject` | `{comment}` — required on reject. |
| `POST /approvals/{id}/edit` | `{payload_patch, comment}`. |
| `GET /approvals/stats` | Counts for the nav badge. |

**Approve** requires the caller to hold `approval_chain[chain_index].role`. If
another chain entry follows, `chain_index` advances, `approver_role` and
`sla_due_at` are updated, status stays `pending`, and `approval.level_approved`
is emitted. Otherwise status becomes `approved` and execution is scheduled.

**Edit supersedes rather than mutates.** The patched payload is re-resolved and
re-evaluated by policy, a new request is created linked by
`supersedes`/`superseded_by`, and the original moves to `superseded`. An edit
that raises the amount past a threshold therefore re-escalates instead of
sliding through on the original approval — mutating in place would let an
approver approve ₹40,000 and execute ₹4,00,000.

**Self-approval is refused** when `requested_by == caller` unless
`allow_self_approval` is set. Admin is not exempt: holding `admin` grants every
role, which would otherwise make the whole layer optional for the one account
most worth constraining.

### 8.2 Inbound webhooks (HMAC, no JWT)

* `POST /webhooks/approval/{request_id}/decision` — `{decision, by, comment,
  idempotency_key}`.
* `POST /webhooks/sap/document-status` — `{sap_doc_number, status, ...}`, sets
  `sap_doc_status`.

Both verify `X-Signature: sha256=<hex>` computed over the **raw request body**
with `APPROVAL_WEBHOOK_SECRET`, compared using `hmac.compare_digest`, plus an
`X-Timestamp` within ±300 s to bound replay. They return 200 quickly and hand
execution to a background task. Retries are absorbed by the unique index on
`(request_id, idempotency_key)` in `approval_events`.

Signature verification reads the body once via a dependency and passes the
parsed object on — verifying a re-serialised body would fail on key order and
whitespace.

## 9. Outbound webhooks

Emitted on `requested`, `level_approved`, `approved`, `rejected`, `edited`,
`escalated`, `executed`, `failed`, `expired`. Body as specified in the
requirement, with `sap_doc_number` present on `executed`. Signed with the same
scheme as inbound. Target from `APPROVAL_WEBHOOK_URL`; the feature is inert when
unset.

Delivery is a row first, HTTP second: `webhooks.emit()` writes an
`approval_deliveries` row and attempts it once, and the sweeper retries failures
with exponential backoff up to a cap. A slow or dead receiver never blocks an
approval decision.

## 10. Scheduler

One `asyncio` task started in the existing `lifespan` at `api/server.py:169`,
ticking every 60 seconds, holding a `pg_try_advisory_lock` for the duration of
each tick so multiple uvicorn workers do not double-fire. Three jobs:

1. Escalate `pending` requests past `sla_due_at` that have an `escalate_to`.
2. Retry `approval_deliveries` due for another attempt.
3. Expire `pending` requests past `expires_at`.

Failure to acquire the lock is a normal outcome, not an error — another worker
has the tick.

## 11. Roles and prompt

`auth/rbac.py` gains five approver roles, each with read access to the module it
signs for:

```
sales_manager    → sd, tickets, docs
finance_manager  → fi_co, sd, receipt, fi_co_re, tickets, docs
plant_manager    → pp, mm, tickets, docs
hr_approver      → hr, tickets, docs
cfo              → fi_co, sd, mm, pp, receipt, fi_co_re, tickets, docs
```

None is added to `WRITE_ROLES`. Approvers approve; the executor performs the
write outside the enforcement context. A user who must both request and approve
holds two roles, and the self-approval rule keeps them from doing both to the
same request.

The `agent/sap_agent.py` system prompt gains only what the code cannot enforce:
never state that a document exists before a document number comes back, report
the request id when a write is queued, and re-issue the tool call with changed
parameters when an approver asks for a change. Thresholds stay out of it.

## 12. Frontend

New `frontend/src/components/approvals/`: `ApprovalsView.jsx` (inbox list with
scope tabs), `ApprovalCard.jsx` (summary, amount, risk-flag chips, age against
SLA), `ApprovalDetail.jsx` (payload, resolved context, event trail, approve /
reject / edit). State in `frontend/src/stores/approvals-store.js` using zustand,
already a dependency and already used by `chat-store.js`. Components built from
scratch — no UI component library, per the project's standing rule.

Nav badge polls `GET /approvals/stats` every 30 seconds. No websockets.

`MessageRow.jsx` renders the `APPROVAL_REQUIRED` state — request id, who it is
waiting on, and a link into the detail view — alongside the existing
`pending_action` rendering.

## 13. Security

* The gate sits in `execute_tool()`, below the model. A prompt injection that
  persuades the agent to skip approval changes nothing.
* Thresholds live in a file the model never sees.
* The executor's bypass is a context variable set only inside
  `executor.execute()`, never reachable from a request handler.
* Approver authority is checked against `approval_chain[chain_index]`, not
  against a client-supplied role.
* Self-approval refused, admin included.
* Payloads are stored as given and re-validated at execution; nothing
  reconstructs a payload from the summary text.
* Existing `mask_fields()` masking applies to resolver context returned through
  the API, so a `sales_manager` does not gain sight of a credit limit their role
  would otherwise be denied.

## 14. Testing

Under the existing plain-pytest convention in `tests/`.

* `test_approvals_policy.py` — table-driven over the pure engine: tier
  selection at and around every boundary, empty chain, risk escalation, unknown
  action, malformed config.
* `test_approvals_resolvers.py` — measures and blocking reasons per action
  against a seeded fixture; the `create_sales_order` amount case specifically.
* `test_approvals_gate.py` — reads pass through; writes without a confirm token
  still get `CONFIRMATION_REQUIRED`; auto tier executes inline and records a
  row; pending tier writes a row and executes nothing; bypass context variable
  stands the gate down; blocking reason returns `ERROR` and writes no row.
* `test_approvals_executor.py` — concurrent claim executes exactly once; a
  non-`OK` return is recorded as `failed`; document number extraction per
  action; revalidation failure on drifted amount.
* `test_approvals_api.py` — chain advance, self-approval refused (admin
  included), wrong-role approve refused, edit supersedes and re-escalates,
  inbox scoping.
* `test_approvals_webhooks.py` — signature accept/tamper/replay/missing,
  idempotent retry, outbound body shape and delivery retry.

## 15. Out of scope

Slack and email adapters (the outbound webhook is the integration point),
approver delegation and out-of-office, bulk approve, approval templates,
per-tenant policy, and a policy-editing admin UI. `policy_rules.json` is edited
on disk for now.
