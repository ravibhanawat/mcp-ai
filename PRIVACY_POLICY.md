# Privacy Policy — SAP AI Agent

**Effective Date:** 2026-03-19
**Version:** 1.0
**Product:** SAP AI Agent MCP Server

---

## 1. Overview

This Privacy Policy explains how the SAP AI Agent ("the System") collects, processes, stores, and protects data on behalf of the organisation that deploys it ("Client"). The System is designed as an on-premises enterprise tool. No data is shared with any third party by default.

---

## 2. Data We Process

### 2.1 Enterprise Business Data
The System queries and displays data from the Client's own MySQL database, including:
- Vendor and customer master records
- Financial data: invoices, GL accounts, cost centres
- Purchase orders, sales orders, deliveries
- Employee records, leave balances, payroll
- Production orders, materials, stock levels
- ABAP programs, function modules, transport requests

**This data never leaves the Client's infrastructure** under the default configuration.

### 2.2 User Account Data
Stored in `users.json` on the server:
- User ID, full name, email address
- bcrypt-hashed password (cost factor 12) — plain-text password is never stored
- Role assignments, account status, login failure counters

### 2.3 Audit Logs
Every API request is logged to `audit_logs/`. Logs contain:
- Timestamp, user ID, user roles, client IP address
- Endpoint and tool called
- Query text (with PII redacted — email addresses and phone numbers are masked)
- Response status and duration

**Audit logs are automatically deleted after 90 days.**

### 2.4 Conversation History
Each user session maintains up to 20 messages of conversation context in server memory. This data:
- Is scoped per user + session ID (no cross-user leakage)
- Is lost on server restart (not persisted to disk)
- Can be cleared on demand via `POST /reset`

---

## 3. Data Storage & Security

| Data Type | Storage Location | Encryption at Rest | Retention |
|-----------|-----------------|-------------------|-----------|
| Business data | Client's MySQL | Client-managed | Client-managed |
| User accounts | `users.json` (chmod 600) | Passwords bcrypt-hashed | Until deleted |
| Audit logs | `audit_logs/*.jsonl` | File-system level | 90 days (auto-purged) |
| Conversation context | Server RAM only | N/A | Session lifetime |
| JWT secrets | Environment variables | Env-level | Until rotated |

---

## 4. AI Model & Data Transmission

### 4.1 Default (On-Premises — No Data Leaves the Network)
The System is designed to run with a **local AI model** (Ollama or MLX fine-tuned model) running entirely on the Client's own server. Under this configuration:
- No query, no business data, and no user information is ever transmitted externally.
- The AI model processes all data locally.

### 4.2 Cloud LLM Fallback (Optional — Explicit Opt-In Required)
If the Client configures an `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`, the System may fall back to a cloud AI provider **only when the local model is unreachable**.

**Critical protections in place when cloud fallback is active:**
- **SAP tool result payloads are always stripped before transmission.** Raw business data (employee salaries, vendor bank accounts, invoice details, etc.) is replaced with a placeholder and is never sent to any cloud API.
- Only the user's natural language query and the system role prompt are transmitted.
- Every cloud fallback activation is recorded in the audit log (`llm_fallback` event).

**Client Recommendation:** For maximum data privacy, do not configure cloud API keys in production. Run exclusively on local models. The `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` fields in `.env` should be left blank unless the Client has:
1. Assessed the data classification of queries users will submit.
2. Reviewed and accepted the respective provider's enterprise data processing agreements (OpenAI DPA / Anthropic Trust Centre).

### 4.3 What Is NEVER Transmitted to Any Third Party
Regardless of configuration, the following is never sent externally:
- Employee personal data (name, salary, leave balance, contact details)
- Vendor bank account numbers or tax IDs
- Customer credit limits or GST numbers
- Invoice amounts or payment terms
- Any data retrieved from the MySQL database via SAP tools
- User passwords or JWT tokens

---

## 5. Third-Party Services

The System does not integrate with any third-party analytics, advertising, or tracking service. The only optional external connections are:

| Service | Purpose | When Active | Data Sent |
|---------|---------|------------|-----------|
| OpenAI API | Cloud LLM fallback | Only if `OPENAI_API_KEY` is set and local model is down | Sanitised query only — no SAP data |
| Anthropic API | Cloud LLM fallback | Only if `ANTHROPIC_API_KEY` is set and OpenAI also fails | Sanitised query only — no SAP data |

---

## 6. User Rights & Controls

### 6.1 Access Control
- All endpoints (except `/health`) require JWT authentication.
- Role-based access control (RBAC) ensures users can only call tools permitted by their assigned role.
- User accounts can be deactivated immediately via `PATCH /auth/users/{user_id}/deactivate`.

### 6.2 Data Subject Requests
The Client (system administrator) can:
- **View** a user's audit trail: `GET /audit/my-logs`
- **Delete** a user account: remove from `users.json` via admin API
- **Clear** conversation history: `POST /reset`
- **Export** audit logs: `GET /audit/logs` (admin only)

### 6.3 Password & Credential Security
- Passwords must meet the policy: minimum 10 characters, uppercase, lowercase, digit, and special character.
- Accounts are locked for 15 minutes after 5 consecutive failed login attempts.
- Access tokens expire after 1 hour. Refresh tokens expire after 7 days.
- Tokens are rotated on every refresh.

---

## 7. Data Breach Notification

In the event of a suspected data breach:
1. The system administrator should immediately rotate `JWT_SECRET_KEY` and `JWT_REFRESH_SECRET` (this invalidates all active sessions).
2. Audit logs in `audit_logs/` should be preserved and reviewed.
3. The Client is responsible for notifying affected data subjects and relevant authorities in accordance with applicable data protection law (e.g., DPDP Act 2023 for India, GDPR for EU deployments).

---

## 8. Compliance

The System is designed to support the following compliance frameworks. **The Client is responsible for ensuring their deployment meets all applicable legal requirements.**

| Framework | Relevant Controls |
|-----------|-----------------|
| **India DPDP Act 2023** | Audit logging, PII redaction, data minimisation |
| **GDPR (EU)** | Audit logging, 90-day log retention, access controls, right-to-erasure support |
| **SOX (Sarbanes-Oxley)** | Audit trail for all financial data access, RBAC, tamper-evident logs |
| **ISO 27001** | JWT authentication, bcrypt hashing, CORS restrictions, rate limiting |

---

## 9. Data Retention Summary

| Data | Retention Period |
|------|----------------|
| Audit log files | 90 days (auto-purged) |
| User account records | Until explicitly deleted by admin |
| Conversation context | Session lifetime (memory only) |
| MySQL business data | Client-managed |
| JWT tokens | Access: 1 hour / Refresh: 7 days |

---

## 10. Changes to This Policy

This policy will be updated when:
- A new external integration is added
- Data retention periods change
- A new category of data is collected

The version number and effective date at the top of this document will be updated accordingly.

---

## 11. Contact

This system is deployed and operated by the Client organisation. For privacy-related queries regarding this deployment, contact the system administrator or Data Protection Officer of the deploying organisation.

---

*This privacy policy covers the SAP AI Agent software. It does not cover the privacy practices of OpenAI, Anthropic, or any other third-party service the Client independently chooses to integrate.*
