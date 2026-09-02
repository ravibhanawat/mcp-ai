"""
SAP AI Agent - Core Engine
Routes all LLM calls through the provider manager, which resolves the model
based on tenant configuration. Models and backends are entirely configurable
via the configuration store, not hardcoded.
"""
import json
import logging
import os
import re
import requests
from decimal import Decimal
from datetime import date, datetime
from typing import Any, AsyncIterator

_logger = logging.getLogger("sap_agent")


class _DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        return super().default(o)
from tools.tool_registry import TOOLS, FUNCTION_MAP, execute_tool, get_tools_for_prompt, get_sap_source
from agent.auto_research import run_auto_research, is_auto_research_query
from agent.autonomous_agent import run_autonomous_agent, is_autonomous_query


class SAPAgent:
    def __init__(
        self,
        manager: "AIProviderManager | None" = None,
        tenant_id: str = "default",
        user_id: str | None = None,
        requested_model_id: str | None = None,
    ):
        """The agent no longer knows what model it uses.

        It asks the manager for one per request, which is what makes the model
        an administrator's decision rather than a deployment's.

        requested_model_id: if set, the agent will request this model from the
        manager. The manager honours the request only if the tenant policy has
        allow_user_selection=True and the model is marked user_selectable.
        """
        from ai.manager import get_manager
        self.manager = manager or get_manager()
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.requested_model_id = requested_model_id
        # Confidential callers (Kutty) set this; the router refuses to resolve an
        # external provider when it is True.
        self.local_only = False
        self.conversation_history = []

    def backend_status(self) -> dict:
        """Report the configured chat model and whether it answers.

        Replaces check_ollama_connection(), which could only ever describe
        Ollama. Never raises: the health endpoint calls it.
        """
        from ai.health import probe, record_health
        from ai.types import Purpose
        try:
            resolution = self.manager.resolve_only(
                tenant_id=self.tenant_id, purpose=Purpose.CHAT
            )
            resolved = resolution.resolved
            api_key = self.manager.credential_for(resolved, self.tenant_id)
            result = probe(resolved, api_key)
            record_health(resolved.model.id, self.tenant_id, result)
            return {
                "configured": True,
                "connected": result.status == "healthy",
                "provider": resolved.provider.name,
                "provider_type": resolved.provider.provider_type.value,
                "model": resolved.model.model_name,
                "model_identifier": resolved.model.model_identifier,
                "latency_ms": result.latency_ms,
                "detail": result.error,
            }
        except Exception as exc:
            return {"configured": False, "connected": False, "detail": str(exc)}

    def system_prompt_for(self, prompt_profile: str) -> str:
        # Fine-tuned MLX model: use the EXACT tool names it was trained on.
        # Do not auto-generate from registry — name mismatch causes hallucinations.
        if prompt_profile == "trained_tool_json":
            tool_list_str = (
                "FI/CO: get_vendor_info, get_invoice_status, get_open_invoices, get_cost_center_budget, list_all_cost_centers, get_gl_posting_for_receipt, get_customer_ledger, get_tds_certificate_data\n"
                "MM: get_material_info, get_stock_level, get_purchase_order, check_reorder_needed, get_bom\n"
                "SD: get_customer_info, get_sales_order, get_delivery_status, get_pricing_info, list_open_orders, get_sales_deed_data, get_allotment_letter_data, validate_einvoice_b2b, get_broker_payout_status, initiate_broker_po\n"
                "HR: get_employee_info, get_leave_balance, get_payslip, list_employees, get_org_chart\n"
                "PP: get_production_order, get_capacity_utilization, get_work_center_info, get_bom_explosion, get_planned_orders\n"
                "ABAP: get_abap_program, get_function_module, get_transport_request, list_abap_programs, analyze_abap_syntax\n"
                "RE: get_customer_unit_outstanding, calculate_receipt_allocation, park_customer_receipt, post_customer_receipt, get_receipt_history, get_milestone_billing_status"
            )
            return (
                "You are SAP Enterprise AI Agent. "
                "For ANY SAP data query, output ONLY a JSON tool call — no other text.\n\n"
                "FORMAT:\n"
                '{"tool_call": {"name": "TOOL_NAME", "parameters": {"PARAM": "VALUE"}}}\n\n'
                "EXAMPLES:\n"
                'User: show vendor V001\n{"tool_call": {"name": "get_vendor_info", "parameters": {"vendor_id": "V001"}}}\n'
                'User: stock for MAT001\n{"tool_call": {"name": "get_stock_level", "parameters": {"material_id": "MAT001"}}}\n'
                'User: ABAP program ZREP_VENDOR_LIST\n{"tool_call": {"name": "get_abap_program", "parameters": {"program_name": "ZREP_VENDOR_LIST"}}}\n'
                'User: invoice INV1001\n{"tool_call": {"name": "get_invoice_status", "parameters": {"invoice_id": "INV1001"}}}\n\n'
                "After receiving tool results, give a clear natural language answer.\n"
                "Never mix JSON and text in the same reply.\n\n"
                "Available tools:\n" + tool_list_str
            )

        # Ollama path: full tool definitions for zero-shot generalisation
        tools_json = get_tools_for_prompt()
        return f"""You are SAP Enterprise AI Agent.

Your role is to assist users in interacting with SAP systems, enterprise workflows, and business data. You help users retrieve insights, automate actions, analyze enterprise data, and guide them through SAP processes.

SUPPORTED SAP SYSTEMS:
• SAP S/4HANA (FI/CO, MM, SD, HR, PP, ABAP)
• SAP SuccessFactors (HR Cloud)
• SAP Ariba (Procurement)
• SAP Business Technology Platform (BTP)
• SAP Analytics Cloud (SAC)

BUSINESS DOMAINS: Finance · Procurement · Supply Chain · Human Resources · Sales · Manufacturing

═══════════════════════════════════════════════════
RESPONSE MODE — select ONE based on the request type:
═══════════════════════════════════════════════════

MODE 1 — DATA RETRIEVAL (read queries about existing SAP records):
Output ONLY this JSON, nothing else:
{{"tool_call": {{"name": "TOOL_NAME", "parameters": {{"PARAM": "VALUE"}}}}}}

MODE 2 — ACTION / WORKFLOW (create, approve, trigger, onboard, process):
Output ONLY this JSON, nothing else:
{{
  "intent": "action_intent_snake_case",
  "module": "SAP Module Name",
  "action": "action_code",
  "required_inputs": ["field1", "field2"],
  "steps": ["Step 1: ...", "Step 2: ...", "Step 3: ..."]
}}

MODE 3 — CONVERSATIONAL (greetings, explanations, general questions):
Respond in clear, professional enterprise language.

═══════════════════════════════════
BEHAVIOR RULES
═══════════════════════════════════

1. ENTERPRISE ACCURACY
   - Prioritize accuracy and clarity above all.
   - If required data (IDs, dates, quantities) is missing, ask clarifying questions before taking action.
   - Never hallucinate SAP data — always use a tool for real data.

2. SECURE DATA HANDLING
   - Never expose: passwords, tokens, oauth secrets, confidential financial data, personal employee data.
   - When returning sensitive records, provide summaries only.

3. STRUCTURED THINKING
   When solving a business problem: Analyze the request → Identify the SAP module → Suggest the best workflow or API → Provide a clear step-by-step solution.

4. CONFIRM BEFORE CRITICAL ACTIONS
   You may recommend workflows, suggest automation, analyze reports, and prepare API requests.
   You MUST confirm with the user before executing: create, delete, approve, post, or trigger actions.

5. ERROR HANDLING
   If a request cannot be completed:
   - Explain why clearly.
   - Suggest an alternative workflow.
   - Provide troubleshooting steps.

6. RESPONSE STYLE
   - Concise, structured, professional, enterprise-ready.
   - Use currency codes (INR, EUR, USD) for all monetary values.

═══════════════════════════════════
AVAILABLE SAP TOOLS (for MODE 1)
═══════════════════════════════════
{tools_json}

═══════════════════════════════════
EXAMPLES
═══════════════════════════════════

User: show me vendor V001
Assistant: {{"tool_call": {{"name": "get_vendor_info", "parameters": {{"vendor_id": "V001"}}}}}}

User: what is the stock level for material MAT002?
Assistant: {{"tool_call": {{"name": "get_stock_level", "parameters": {{"material_id": "MAT002"}}}}}}

User: create a purchase order for vendor V001 for 100 laptops
Assistant: {{
  "intent": "create_purchase_order",
  "module": "SAP S/4HANA Procurement",
  "action": "create_PO",
  "required_inputs": ["vendor_id", "material_id", "quantity", "delivery_date", "plant"],
  "steps": [
    "Step 1: Validate vendor V001 exists and is active",
    "Step 2: Check material availability and reorder levels",
    "Step 3: Create purchase order via ME21N",
    "Step 4: Route to approval workflow",
    "Step 5: Send confirmation to vendor"
  ]
}}

User: onboard new employee John Doe joining next Monday
Assistant: {{
  "intent": "employee_onboarding",
  "module": "SAP SuccessFactors",
  "action": "initiate_onboarding",
  "required_inputs": ["employee_name", "start_date", "department", "position_id", "manager_id", "cost_center"],
  "steps": [
    "Step 1: Create employee master record in SuccessFactors",
    "Step 2: Assign role and position",
    "Step 3: Trigger IT access provisioning workflow",
    "Step 4: Send welcome email and onboarding checklist",
    "Step 5: Schedule orientation sessions"
  ]
}}

User: approve invoice INV1001
Assistant: {{
  "intent": "approve_invoice",
  "module": "SAP S/4HANA Finance",
  "action": "invoice_approval",
  "required_inputs": ["invoice_id", "approver_id", "approval_note"],
  "steps": [
    "Step 1: Retrieve invoice INV1001 for review",
    "Step 2: Verify 3-way match (PO, GR, Invoice)",
    "Step 3: Confirm approval with user before posting",
    "Step 4: Post invoice via MIRO",
    "Step 5: Trigger payment run"
  ]
}}

User: what is the leave balance for employee EMP003?
Assistant: {{"tool_call": {{"name": "get_leave_balance", "parameters": {{"emp_id": "EMP003"}}}}}}

User: show invoice INV1001
Assistant: {{"tool_call": {{"name": "get_invoice_status", "parameters": {{"invoice_id": "INV1001"}}}}}}

User: list all employees
Assistant: {{"tool_call": {{"name": "search_employees", "parameters": {{}}}}}}

User: show all employees in HR department
Assistant: {{"tool_call": {{"name": "search_employees", "parameters": {{"dept": "HR"}}}}}}

User: show outstanding dues for customer ALEC001 unit T1-304
Assistant: {{"tool_call": {{"name": "get_customer_unit_outstanding", "parameters": {{"customer_id": "ALEC001", "unit_number": "T1-304"}}}}}}

User: what are the pending milestones for ALEC002 T2-201?
Assistant: {{"tool_call": {{"name": "get_milestone_billing_status", "parameters": {{"customer_id": "ALEC002", "unit_number": "T2-201"}}}}}}

User: park a cheque receipt of 500000 for ALEC001 unit T1-304, cheque 891234 dated 2026-04-01 HDFC Bank
Assistant: {{"tool_call": {{"name": "park_customer_receipt", "parameters": {{"customer_id": "ALEC001", "unit_number": "T1-304", "payment_mode": "Cheque", "amount": 500000, "instrument_ref": "891234", "instrument_date": "2026-04-01", "bank_name": "HDFC Bank"}}}}}}

User: post the parked receipt PRK00000001
Assistant: {{"tool_call": {{"name": "post_customer_receipt", "parameters": {{"park_reference": "PRK00000001"}}}}}}

User: show receipt history for ALEC001 flat T1-304
Assistant: {{"tool_call": {{"name": "get_receipt_history", "parameters": {{"customer_id": "ALEC001", "unit_number": "T1-304"}}}}}}

User: get sales deed data for customer ALEC001 unit T1-304
Assistant: {{"tool_call": {{"name": "get_sales_deed_data", "parameters": {{"customer_id": "ALEC001", "unit_number": "T1-304"}}}}}}

User: generate allotment letter for ALEC003 unit PC-1102
Assistant: {{"tool_call": {{"name": "get_allotment_letter_data", "parameters": {{"customer_id": "ALEC003", "unit_number": "PC-1102", "project_code": "PARK_CRESCENT"}}}}}}

User: check e-invoice for billing doc 9000010001
Assistant: {{"tool_call": {{"name": "validate_einvoice_b2b", "parameters": {{"billing_doc_no": "9000010001"}}}}}}

User: show broker payout status for BR001
Assistant: {{"tool_call": {{"name": "get_broker_payout_status", "parameters": {{"broker_id": "BR001"}}}}}}

User: initiate broker PO for BR001 unit T1-304
Assistant: {{"tool_call": {{"name": "initiate_broker_po", "parameters": {{"broker_id": "BR001", "unit_number": "T1-304"}}}}}}

User: show customer ledger for ALEC001 T1-304
Assistant: {{"tool_call": {{"name": "get_customer_ledger", "parameters": {{"customer_id": "ALEC001", "unit_number": "T1-304"}}}}}}

User: TDS certificate for ALEC001 FY 2025-26
Assistant: {{"tool_call": {{"name": "get_tds_certificate_data", "parameters": {{"customer_id": "ALEC001", "fiscal_year": "2025-26"}}}}}}

═══════════════════════════════════════
DOCUMENTATION SEARCH RULE
═══════════════════════════════════════
When the user asks HOW to do something in SAP, asks about a T-code, BAPI, business process,
configuration, or error resolution — call the search_sap_docs tool FIRST, then answer.

Examples that require search_sap_docs:
- "How do I create a purchase order?" → {{"tool_call": {{"name": "search_sap_docs", "parameters": {{"query": "create purchase order", "category": "tcode"}}}}}}
- "What is MIRO used for?" → {{"tool_call": {{"name": "search_sap_docs", "parameters": {{"query": "MIRO invoice verification"}}}}}}
- "How does the P2P process work?" → {{"tool_call": {{"name": "search_sap_docs", "parameters": {{"query": "procure to pay process", "category": "process"}}}}}}
- "Invoice is blocked, how to fix?" → {{"tool_call": {{"name": "search_sap_docs", "parameters": {{"query": "invoice blocked", "category": "error"}}}}}}

CRITICAL: Output ONLY one of the three modes per response. Never mix JSON with natural language text."""

    def _call_llm(
        self,
        messages: list[dict],
        *,
        purpose: "Purpose | None" = None,
        carries_sap_data: bool = False,
        required: frozenset | None = None,
        request_id: str | None = None,
    ) -> str:
        """Send messages to whichever model is configured for this purpose.

        The agent expresses what it needs — a purpose, whether the payload holds
        SAP records, which capabilities it requires — and the manager decides
        which model serves it and whether the payload may leave the estate.
        """
        from ai.types import Purpose as _Purpose
        response = self.manager.chat(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            purpose=purpose or _Purpose.CHAT,
            messages=messages,
            carries_sap_data=carries_sap_data,
            required=required or frozenset(),
            local_only=self.local_only,
            requested_model_id=self.requested_model_id,
            request_id=request_id,
        )
        return response.content

    def _call_llm_stream(
        self,
        messages: list[dict],
        *,
        purpose: "Purpose | None" = None,
        carries_sap_data: bool = False,
        request_id: str | None = None,
    ) -> AsyncIterator[str]:
        """Async generator of token strings from the configured chat model.

        No failover: a stream that changed models mid-answer would show the user
        two partial replies stitched together. When the configured model cannot
        stream the manager raises CapabilityUnsupported and the caller falls back
        to a single non-streaming call.
        """
        from ai.types import Purpose as _Purpose
        return self.manager.stream(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            purpose=purpose or _Purpose.CHAT,
            messages=messages,
            carries_sap_data=carries_sap_data,
            local_only=self.local_only,
            requested_model_id=self.requested_model_id,
            request_id=request_id,
        )


    def _extract_tool_call(self, response: str) -> dict | None:
        """Extract JSON tool call from LLM response"""
        # Try direct JSON parse
        try:
            data = json.loads(response.strip())
            if "tool_call" in data:
                return data["tool_call"]
        except Exception:
            pass

        # Try extracting JSON from markdown code block
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                if "tool_call" in data:
                    return data["tool_call"]
            except Exception:
                pass

        # Bracket-counting scan: finds {"tool_call" anywhere in text, handles nesting
        start = response.find('{"tool_call"')
        if start != -1:
            depth = 0
            for i, ch in enumerate(response[start:]):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            data = json.loads(response[start:start + i + 1])
                            if "tool_call" in data:
                                return data["tool_call"]
                        except Exception:
                            pass
                        break

        return None

    def _is_valid_tool_call(self, tool_call: dict) -> bool:
        """Return True only if the extracted tool call refers to a registered tool."""
        name = tool_call.get("name", "")
        return name in FUNCTION_MAP

    def _infer_tool_from_query(self, text: str) -> dict | None:
        """
        Keyword + regex fallback router used when the LLM fails to emit a tool call.
        Matches common SAP entity patterns and maps them to the correct tool + params.
        Returns a tool_call dict like {"name": ..., "parameters": {...}} or None.
        """
        t = text.lower()

        # ABAP program (Z/Y programs — check before generic keyword matches)
        m = re.search(r'\b([zy][a-z0-9_]{2,})\b', text, re.IGNORECASE)
        if m and any(kw in t for kw in ["abap", "program", "report", "se38"]):
            return {"name": "get_abap_program", "parameters": {"program_name": m.group(1).upper()}}

        # Function module
        m = re.search(r'\b([zy][_a-z0-9]{3,})\b', text, re.IGNORECASE)
        if m and any(kw in t for kw in ["function module", "fm ", "se37", "bapi"]):
            return {"name": "get_function_module", "parameters": {"fm_name": m.group(1).upper()}}

        # Transport request (e.g. DEVK900123)
        m = re.search(r'\b([A-Z]{3}K\d{6})\b', text, re.IGNORECASE)
        if m:
            return {"name": "get_transport_request", "parameters": {"tr_id": m.group(1).upper()}}

        # Vendor ID (V001, V002 …)
        m = re.search(r'\bv\d{3,}\b', text, re.IGNORECASE)
        if m and any(kw in t for kw in ["vendor", "supplier"]):
            return {"name": "get_vendor_info", "parameters": {"vendor_id": m.group(0).upper()}}

        # Invoice ID (INV1000 …)
        m = re.search(r'\binv\d+\b', text, re.IGNORECASE)
        if m:
            return {"name": "get_invoice_status", "parameters": {"invoice_id": m.group(0).upper()}}

        # Cost center (CC100 …)
        m = re.search(r'\bcc\d+\b', text, re.IGNORECASE)
        if m:
            return {"name": "get_cost_center_budget", "parameters": {"cost_center_id": m.group(0).upper()}}

        # Purchase order (PO2001 …)
        m = re.search(r'\bpo\d+\b', text, re.IGNORECASE)
        if m:
            return {"name": "get_purchase_order", "parameters": {"po_id": m.group(0).upper()}}

        # Sales order (SO5001 …)
        m = re.search(r'\bso\d+\b', text, re.IGNORECASE)
        if m:
            return {"name": "get_sales_order", "parameters": {"order_id": m.group(0).upper()}}

        # Production order (PRD7001 …)
        m = re.search(r'\bprd\d+\b', text, re.IGNORECASE)
        if m:
            return {"name": "get_production_order", "parameters": {"order_id": m.group(0).upper()}}

        # Customer (C001 …)
        m = re.search(r'\bc\d{3,}\b', text, re.IGNORECASE)
        if m and any(kw in t for kw in ["customer", "client", "buyer"]):
            return {"name": "get_customer_info", "parameters": {"customer_id": m.group(0).upper()}}

        # Employee (EMP001 …)
        m = re.search(r'\bemp\d+\b', text, re.IGNORECASE)
        if m:
            if any(kw in t for kw in ["leave", "vacation", "absence", "balance"]):
                return {"name": "get_leave_balance", "parameters": {"emp_id": m.group(0).upper()}}
            if any(kw in t for kw in ["pay", "salary", "payslip", "wage"]):
                return {"name": "get_payslip", "parameters": {"emp_id": m.group(0).upper()}}
            return {"name": "get_employee_info", "parameters": {"emp_id": m.group(0).upper()}}

        # Material (MAT001 …)
        m = re.search(r'\bmat\d+\b', text, re.IGNORECASE)
        if m:
            if any(kw in t for kw in ["stock", "inventory", "level", "quantity"]):
                return {"name": "get_stock_level", "parameters": {"material_id": m.group(0).upper()}}
            return {"name": "get_material_info", "parameters": {"material_id": m.group(0).upper()}}

        # No-param list queries
        if any(kw in t for kw in ["open invoice", "unpaid invoice", "all invoice"]):
            return {"name": "get_open_invoices", "parameters": {}}
        if any(kw in t for kw in ["all cost center", "list cost center"]):
            return {"name": "list_all_cost_centers", "parameters": {}}
        if any(kw in t for kw in ["open purchase order", "list purchase order", "all po"]):
            return {"name": "list_open_purchase_orders", "parameters": {}}
        if any(kw in t for kw in ["open sales order", "list sales order", "all order"]):
            return {"name": "list_open_sales_orders", "parameters": {}}
        if any(kw in t for kw in ["list all employee", "all employee", "list employee", "show all employee", "show employee", "employees in", "employee list", "staff list"]):
            # Extract optional department filter
            dept_match = re.search(r'\b(in|from|of)\s+([a-zA-Z /&]+?)(?:\s+department|\s+dept|$)', text, re.IGNORECASE)
            dept = dept_match.group(2).strip() if dept_match else None
            params = {"dept": dept} if dept else {}
            return {"name": "search_employees", "parameters": params}
        if any(kw in t for kw in ["reorder", "low stock", "need reorder"]):
            return {"name": "check_reorder_needed", "parameters": {}}
        if any(kw in t for kw in ["capacity", "utilization", "work center"]):
            return {"name": "get_capacity_utilization", "parameters": {}}
        if any(kw in t for kw in ["list abap", "abap program list", "all program"]):
            return {"name": "list_abap_programs", "parameters": {}}

        # Ticket backlog (Kutty RAG) — route clear backlog questions to the ticket
        # index. Checked last so specific SAP entity patterns above win first.
        if any(kw in t for kw in ["ticket", "tickets", "backlog", "ricefw", "wricef"]):
            return {"name": "search_sap_tickets", "parameters": {"query": text}}

        return None

    @staticmethod
    def _apply_ticket_status(tool_name: str, tool_params: dict, ticket_status: str | None) -> None:
        """Inject the UI-selected status filter into a Kutty ticket-search call."""
        if tool_name == "search_sap_tickets" and ticket_status:
            tool_params.setdefault("status", ticket_status)

    def _extract_action_plan(self, response: str) -> dict | None:
        """Extract an action plan JSON (intent/module/action/required_inputs/steps) from LLM response."""
        # Try direct JSON parse
        try:
            data = json.loads(response.strip())
            if "intent" in data and "steps" in data:
                return data
        except Exception:
            pass

        # Try markdown code block
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                if "intent" in data and "steps" in data:
                    return data
            except Exception:
                pass

        # Bracket-counting scan for {"intent" anywhere in text
        start = response.find('{"intent"')
        if start != -1:
            depth = 0
            for i, ch in enumerate(response[start:]):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            data = json.loads(response[start:start + i + 1])
                            if "intent" in data and "steps" in data:
                                return data
                        except Exception:
                            pass
                        break

        return None

    def auto_research(self, query: str, allowed_tools: set[str] | None = None) -> tuple:
        """
        Run autonomous multi-step SAP research on an entity.
        Returns (report_text, "auto_research", research_result_dict).
        """
        def _execute(tool_name: str, params: dict) -> dict:
            # Respect RBAC: skip disallowed tools
            if allowed_tools is not None and tool_name not in allowed_tools:
                return {"status": "ERROR", "message": f"Access denied: tool '{tool_name}' not permitted for your role"}
            return execute_tool(tool_name, params)

        result = run_auto_research(query, _execute)
        return result["formatted_report"], "auto_research", result

    def autonomous(self, query: str, allowed_tools: set[str] | None = None) -> tuple:
        """
        Run the LLM-driven autonomous agent for complex decision/reasoning queries.
        Returns (report_text, "autonomous_agent", result_dict).
        """
        def _execute(tool_name: str, params: dict) -> dict:
            if allowed_tools is not None and tool_name not in allowed_tools:
                return {"status": "ERROR", "message": f"Access denied: tool '{tool_name}' not permitted for your role"}
            from tools.tool_registry import execute_tool
            return execute_tool(tool_name, params)

        result = run_autonomous_agent(
            query=query,
            execute_tool_fn=_execute,
            manager=self.manager,
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            allowed_tools=allowed_tools,
        )
        return result["report"], "autonomous_agent", result

    @staticmethod
    def _friendly_fallback(tool_name: str, tool_result: dict) -> str:
        """
        Build a human-readable markdown response from raw tool result data.
        Used when the LLM fails or returns JSON instead of natural language.
        Handles both single-record and list-of-records results.
        """
        title = tool_name.replace('_', ' ').title()
        lines = [f"## {title}\n"]

        def fmt_val(v):
            if v is None:
                return "—"
            if isinstance(v, bool):
                return "Yes" if v else "No"
            return str(v)

        def render_record(record: dict, indent: str = "") -> list[str]:
            out = []
            for k, v in record.items():
                if k in ("status", "sap_source"):
                    continue
                label = k.replace("_", " ").title()
                if isinstance(v, dict):
                    out.append(f"{indent}**{label}:**")
                    out.extend(render_record(v, indent + "  "))
                elif isinstance(v, list) and v and isinstance(v[0], dict):
                    # Nested list of objects — render as mini table
                    keys = list(v[0].keys())
                    out.append(f"{indent}**{label}:** ({len(v)} items)")
                    out.append("| " + " | ".join(k2.replace("_", " ").upper() for k2 in keys) + " |")
                    out.append("|" + "|".join("---" for _ in keys) + "|")
                    for row in v:
                        out.append("| " + " | ".join(fmt_val(row.get(k2)) for k2 in keys) + " |")
                elif isinstance(v, list):
                    out.append(f"{indent}- **{label}:** {', '.join(fmt_val(x) for x in v) or '—'}")
                else:
                    out.append(f"{indent}- **{label}:** {fmt_val(v)}")
            return out

        # Detect top-level list field (e.g. employees, invoices, orders)
        list_key = None
        list_data = None
        for k, v in tool_result.items():
            if k not in ("status", "sap_source", "count") and isinstance(v, list) and v and isinstance(v[0], dict):
                list_key = k
                list_data = v
                break

        if list_data is not None:
            count = tool_result.get("count", len(list_data))
            lines.append(f"Found **{count}** {list_key.replace('_', ' ')}:\n")
            keys = list(list_data[0].keys())
            lines.append("| " + " | ".join(k.replace("_", " ").upper() for k in keys) + " |")
            lines.append("|" + "|".join(" --- " for _ in keys) + "|")
            for row in list_data:
                lines.append("| " + " | ".join(fmt_val(row.get(k)) for k in keys) + " |")
        else:
            # Single record
            lines.extend(render_record({k: v for k, v in tool_result.items() if k not in ("status", "sap_source")}))

        return "\n".join(lines)

    def _format_tool_response(self, user_message: str, tool_name: str, tool_result: dict) -> str:
        """
        Generate a structured, analytical natural language response from SAP tool data.
        Uses local LLM — tool result data must never be sent to cloud providers.
        The prompt is designed to extract insights, not just reformat JSON.
        Falls back to a clean markdown renderer if the LLM returns JSON or fails.
        """
        data_json = json.dumps(tool_result, indent=2, cls=_DecimalEncoder)
        response_prompt = (
            f"The user asked: \"{user_message}\"\n\n"
            f"SAP tool '{tool_name}' returned this data:\n{data_json}\n\n"
            "Provide a clear, professional enterprise response that:\n"
            "1. Directly answers the user's question using the data above.\n"
            "2. Presents key values in a readable format (use tables or bullet points where helpful).\n"
            "3. Highlights any important findings: overdue items, low stock, budget overruns, anomalies.\n"
            "4. Ends with a one-line business summary or recommended next action.\n"
            "IMPORTANT: Do NOT output JSON or code blocks. Write ONLY in clear business English."
        )
        messages = [
            {"role": "system", "content": "You are a professional SAP enterprise assistant. Format data clearly and provide business insights. Never output raw JSON."},
            {"role": "user", "content": response_prompt},
        ]
        try:
            llm_response = self._call_llm(messages, carries_sap_data=True)
            # If LLM returned JSON (common with small local models), use friendly fallback
            stripped = llm_response.strip()
            if stripped.startswith(("{", "[", "```")):
                return self._friendly_fallback(tool_name, tool_result)
            return llm_response
        except Exception:
            return self._friendly_fallback(tool_name, tool_result)

    def chat(self, user_message: str, allowed_tools: set[str] | None = None,
             ticket_status: str | None = None) -> tuple:
        """
        Main chat method — returns (response_text, tool_name, tool_result).

        Routing priority:
          1. Autonomous / auto-research intercept (complex multi-step)
          2. Deterministic regex router → tool execution (fast, 100% reliable)
          3. LLM-based tool extraction (unrecognised patterns, workflow intents)
          4. Cloud LLM for conversational / research responses (no SAP data sent)
          5. Local LLM fallback for pure conversation
        """
        from ai.types import Purpose

        # ── 1. Intercept autonomous / research queries ─────────────────────────
        if is_autonomous_query(user_message):
            return self.autonomous(user_message, allowed_tools=allowed_tools)
        if is_auto_research_query(user_message):
            return self.auto_research(user_message, allowed_tools=allowed_tools)

        # ── Resolve model to get prompt_profile ────────────────────────────────
        resolution = self.manager.resolve_only(
            tenant_id=self.tenant_id, purpose=Purpose.CHAT,
            requested_model_id=self.requested_model_id,
        )
        prompt_profile = resolution.resolved.model.prompt_profile
        is_trained_model = prompt_profile == "trained_tool_json"

        # ── Build scoped system prompt ─────────────────────────────────────────
        system_prompt = self.system_prompt_for(prompt_profile)
        if allowed_tools is not None and not is_trained_model:
            from tools.tool_registry import get_tools_for_prompt as _gtp
            tools_json = _gtp(allowed_tools=allowed_tools)
            split_marker = "AVAILABLE SAP TOOLS (for MODE 1)"
            if split_marker in system_prompt:
                system_prompt = system_prompt.split(split_marker)[0]
                system_prompt += f"{split_marker}\n{'═' * 35}\n{tools_json}\n\n"
                system_prompt += "CRITICAL: Output ONLY one of the three modes per response. Never mix JSON with natural language text."

        # ── 2. Deterministic tool routing (no LLM required) ───────────────────
        # Run the regex/keyword router FIRST. It is fast and 100% reliable for
        # all standard SAP entity patterns. Only fall through to the LLM when
        # the query doesn't match any known pattern.
        tool_call = self._infer_tool_from_query(user_message)

        if tool_call and self._is_valid_tool_call(tool_call):
            # Honour RBAC
            if allowed_tools is not None and tool_call["name"] not in allowed_tools:
                return (
                    f"Access denied: your role does not permit the '{tool_call['name']}' tool.",
                    None, None
                )
            tool_name   = tool_call["name"]
            tool_params = tool_call.get("parameters", {})
            self._apply_ticket_status(tool_name, tool_params, ticket_status)
            tool_result = execute_tool(tool_name, tool_params)

            # Response formatting uses local LLM (tool data must not leave the network)
            final_response = self._format_tool_response(user_message, tool_name, tool_result)

            if not is_trained_model:
                self.conversation_history.append({"role": "user", "content": user_message})
                self.conversation_history.append({"role": "assistant", "content": final_response})
                if len(self.conversation_history) > 20:
                    self.conversation_history = self.conversation_history[-20:]

            return final_response, tool_name, tool_result

        # ── 3. LLM-based routing (complex / unrecognised patterns) ────────────
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(self.conversation_history)
        messages.append({"role": "user", "content": user_message})

        llm_response = self._call_llm(messages)

        # Check for valid tool call in LLM output
        tool_call = self._extract_tool_call(llm_response)
        if tool_call and self._is_valid_tool_call(tool_call):
            if allowed_tools is not None and tool_call["name"] not in allowed_tools:
                return (
                    f"Access denied: your role does not permit the '{tool_call['name']}' tool.",
                    None, None
                )
            tool_name   = tool_call["name"]
            tool_params = tool_call.get("parameters", {})
            self._apply_ticket_status(tool_name, tool_params, ticket_status)
            tool_result = execute_tool(tool_name, tool_params)

            final_response = self._format_tool_response(user_message, tool_name, tool_result)

            if not is_trained_model:
                self.conversation_history.append({"role": "user", "content": user_message})
                self.conversation_history.append({"role": "assistant", "content": final_response})
                if len(self.conversation_history) > 20:
                    self.conversation_history = self.conversation_history[-20:]

            return final_response, tool_name, tool_result

        # Check for workflow / action plan intent
        action_plan = self._extract_action_plan(llm_response)
        if action_plan:
            if not is_trained_model:
                self.conversation_history.append({"role": "user", "content": user_message})
                self.conversation_history.append({"role": "assistant", "content": llm_response})
                if len(self.conversation_history) > 20:
                    self.conversation_history = self.conversation_history[-20:]
            return llm_response, "action_plan", action_plan

        # ── 4. Conversational / research response ─────────────────────────────
        # The manager routes through configured providers + failover. The response
        # is already available from the earlier _call_llm() — no separate cloud call needed.
        final_response = llm_response

        if not is_trained_model:
            self.conversation_history.append({"role": "user", "content": user_message})
            self.conversation_history.append({"role": "assistant", "content": final_response})
            if len(self.conversation_history) > 20:
                self.conversation_history = self.conversation_history[-20:]

        return final_response, None, None

    def reset_conversation(self):
        """Clear conversation history"""
        self.conversation_history = []

    # ── SSE Streaming helpers ──────────────────────────────────────────────────

    @staticmethod
    def _extract_list_data(tool_result: dict) -> list | None:
        """Return the primary list of records from a tool result, or None."""
        if isinstance(tool_result, list):
            return tool_result
        for v in tool_result.values():
            if isinstance(v, list) and len(v) > 0 and isinstance(v[0], dict):
                return v
        return None

    async def _stream_tool_table(self, tool_name: str, tool_result: dict, rows: list):
        """
        Async generator — yields SSE table_start + batched table_rows events.
        Bypasses the LLM entirely for large datasets.
        Batch size of 50 rows keeps each SSE event small and renders quickly.
        """
        def _sse(event_type: str, payload: dict) -> str:
            return f"event: {event_type}\ndata: {json.dumps(payload, cls=_DecimalEncoder)}\n\n"

        columns = list(rows[0].keys()) if rows else []
        yield _sse("table_start", {
            "tool": tool_name,
            "columns": columns,
            "total": len(rows),
        })
        import asyncio
        batch_size = 50
        for i in range(0, len(rows), batch_size):
            batch = [{k: v for k, v in row.items()} for row in rows[i:i + batch_size]]
            yield _sse("table_rows", {"rows": batch})
            # Yield control so the event loop can flush the response
            await asyncio.sleep(0)
        yield _sse("table_end", {"total": len(rows)})

    async def _format_tool_response_stream(self, user_message: str, tool_name: str, tool_result: dict):
        """
        Async generator — yields the LLM's natural-language formatting of a tool result in chunks.
        Uses non-streaming manager API and yields result in chunks for compatibility with streaming interface.
        Falls back to friendly_fallback if LLM returns JSON.
        """
        import asyncio

        data_json = json.dumps(tool_result, indent=2, cls=_DecimalEncoder)
        # Truncate to ~3000 chars so the full prompt fits in local-LLM context windows
        MAX_DATA_CHARS = 3000
        truncation_note = ""
        if len(data_json) > MAX_DATA_CHARS:
            truncated_json = data_json[:MAX_DATA_CHARS]
            if isinstance(tool_result, list):
                truncation_note = f"\n[Note: Only showing first portion of {len(tool_result)} total records due to context limits.]"
            elif isinstance(tool_result, dict):
                for v in tool_result.values():
                    if isinstance(v, list) and len(v) > 0:
                        truncation_note = f"\n[Note: Data truncated — {len(v)} total records, showing partial data.]"
                        break
            data_json = truncated_json + "\n..." + truncation_note
        response_prompt = (
            f"The user asked: \"{user_message}\"\n\n"
            f"SAP tool '{tool_name}' returned this data:\n{data_json}\n\n"
            "Provide a clear, professional enterprise response that:\n"
            "1. Directly answers the user's question using the data above.\n"
            "2. Presents key values in a readable format (use tables or bullet points where helpful).\n"
            "3. Highlights any important findings: overdue items, low stock, budget overruns, anomalies.\n"
            "4. Ends with a one-line business summary or recommended next action.\n"
            "IMPORTANT: Do NOT output JSON or code blocks. Write ONLY in clear business English."
        )
        messages = [
            {"role": "system", "content": "You are a professional SAP enterprise assistant. Format data clearly and provide business insights. Never output raw JSON."},
            {"role": "user", "content": response_prompt},
        ]

        from ai.errors import CapabilityUnsupported
        try:
            # Buffer the first ~20 chars to detect JSON output
            buffer = []
            first_chunk_peeked = False
            async for token in self._call_llm_stream(messages, carries_sap_data=True):
                if not first_chunk_peeked:
                    buffer.append(token)
                    if len("".join(buffer)) >= 20:
                        first_chunk_peeked = True
                        peeked = "".join(buffer).strip()
                        if peeked.startswith(("{", "[", "```")):
                            # Model returned JSON; fall back to friendly format
                            yield self._friendly_fallback(tool_name, tool_result)
                            return
                        # Yield all buffered tokens
                        for buffered_token in buffer:
                            yield buffered_token
                        buffer = []
                else:
                    yield token
            # Yield any remaining buffered tokens if stream ended before ~20 chars
            if buffer:
                peeked = "".join(buffer).strip()
                if peeked.startswith(("{", "[", "```")):
                    yield self._friendly_fallback(tool_name, tool_result)
                else:
                    for token in buffer:
                        yield token
        except CapabilityUnsupported:
            # Configured model has no streaming capability: answer in one piece.
            yield self._format_tool_response(user_message, tool_name, tool_result)
        except Exception:
            yield self._friendly_fallback(tool_name, tool_result)

    async def chat_stream(
        self,
        user_message: str,
        allowed_tools: set | None = None,
        clarification_answer: str | None = None,
        ticket_status: str | None = None,
    ):
        """
        Async generator that yields SSE-formatted strings for the streaming chat endpoint.
        Mirrors the 5-tier routing of chat() but emits status events at each decision point
        and streams LLM tokens for conversational responses.

        Each yielded string is a complete SSE event ready to write to the HTTP response:
            "event: <type>\\ndata: <json>\\n\\n"
        """
        import asyncio

        def _sse(event_type: str, payload: dict) -> str:
            return f"event: {event_type}\ndata: {json.dumps(payload, cls=_DecimalEncoder)}\n\n"

        if clarification_answer:
            user_message = f"{user_message}\n[Clarification: {clarification_answer}]"

        def _needs_clarification(msg: str) -> dict | None:
            msg_lower = msg.lower()
            if any(kw in msg_lower for kw in ("invoice", "payment", "purchase order", "vendor bill")) \
                    and not any(kw in msg_lower for kw in ("today", "this week", "this month", "last", "since", "from", "between", "year", "quarter")):
                return {
                    "question": "Which time period should I search?",
                    "options": ["This month", "Last 3 months", "This year", "All time"],
                }
            if any(kw in msg_lower for kw in ("customer detail", "vendor detail", "customer profile")) \
                    and not any(c.isupper() for c in msg):
                return {
                    "question": "Which customer or vendor are you looking for?",
                    "options": None,
                }
            return None

        # Skip clarification if caller already provided an answer
        if not clarification_answer:
            _clarify = _needs_clarification(user_message)
            if _clarify:
                yield _sse("clarify", _clarify)
                return

        # ── 1. Autonomous / research intercept ────────────────────────────────
        if is_autonomous_query(user_message):
            yield _sse("status", {"step": "Autonomous agent activated — running multi-step analysis...", "phase": "routing_query"})
            try:
                result = await asyncio.to_thread(self.autonomous, user_message, allowed_tools)
                response_text, tool_called, tool_result = result
            except Exception:
                response_text, tool_called, tool_result = "An error occurred during autonomous analysis.", None, None
            yield _sse("answer", {"delta": response_text})
            yield _sse("done", {
                "tool_called": tool_called, "tool_result": tool_result,
                "sap_source": None, "report": None, "abap_check": None, "abap_code": None,
            })
            return

        if is_auto_research_query(user_message):
            yield _sse("status", {"step": "Auto-research mode — chaining SAP tools...", "phase": "routing_query"})
            try:
                result = await asyncio.to_thread(self.auto_research, user_message, allowed_tools)
                response_text, tool_called, tool_result = result
            except Exception:
                response_text, tool_called, tool_result = "An error occurred during auto-research.", None, None
            yield _sse("answer", {"delta": response_text})
            yield _sse("done", {
                "tool_called": tool_called, "tool_result": tool_result,
                "sap_source": None, "report": None, "abap_check": None, "abap_code": None,
            })
            return

        # ── Resolve model to get prompt_profile ────────────────────────────────
        from ai.types import Purpose
        resolution = self.manager.resolve_only(
            tenant_id=self.tenant_id, purpose=Purpose.CHAT,
            requested_model_id=self.requested_model_id,
        )
        prompt_profile = resolution.resolved.model.prompt_profile
        is_trained_model = prompt_profile == "trained_tool_json"

        # ── Build scoped system prompt ─────────────────────────────────────────
        system_prompt = self.system_prompt_for(prompt_profile)
        if allowed_tools is not None and not is_trained_model:
            from tools.tool_registry import get_tools_for_prompt as _gtp
            tools_json = _gtp(allowed_tools=allowed_tools)
            split_marker = "AVAILABLE SAP TOOLS (for MODE 1)"
            if split_marker in system_prompt:
                system_prompt = system_prompt.split(split_marker)[0]
                system_prompt += f"{split_marker}\n{'═' * 35}\n{tools_json}\n\n"
                system_prompt += "CRITICAL: Output ONLY one of the three modes per response. Never mix JSON with natural language text."

        # ── 2. Deterministic regex router ─────────────────────────────────────
        yield _sse("status", {"step": "Routing query via SAP pattern matcher...", "phase": "routing_query"})
        yield _sse("intent", {"modules": [], "confidence": 0.9, "routing": "pattern_match"})
        tool_call = self._infer_tool_from_query(user_message)

        if tool_call and self._is_valid_tool_call(tool_call):
            if allowed_tools is not None and tool_call["name"] not in allowed_tools:
                yield _sse("answer", {"delta": f"Access denied: your role does not permit the '{tool_call['name']}' tool."})
                yield _sse("done", {"tool_called": None, "tool_result": None, "sap_source": None, "report": None, "abap_check": None, "abap_code": None})
                return

            tool_name   = tool_call["name"]
            tool_params = tool_call.get("parameters", {})
            self._apply_ticket_status(tool_name, tool_params, ticket_status)
            _sap_module = tool_name.split("_")[0].upper() if "_" in tool_name else tool_name.upper()
            yield _sse("intent", {"modules": [_sap_module], "confidence": 1.0, "routing": "confirmed"})
            yield _sse("status", {"step": f"Calling SAP tool: {tool_name}", "phase": "calling_tool", "tool": tool_name})

            tool_result = await asyncio.to_thread(execute_tool, tool_name, tool_params)
            sap_source  = tool_result.get("sap_source") or get_sap_source(tool_name)

            list_rows = self._extract_list_data(tool_result)
            LARGE_THRESHOLD = 15
            if list_rows and len(list_rows) >= LARGE_THRESHOLD:
                # Large dataset: stream summary text + table rows, skip LLM formatting
                total = len(list_rows)
                summary = (
                    f"Found **{total} records** from `{tool_name}`.\n"
                    f"Showing all results in the table below."
                )
                full_text = summary
                yield _sse("answer", {"delta": summary})
                yield _sse("status", {"step": f"Streaming {total} records...", "phase": "processing"})
                async for tbl_event in self._stream_tool_table(tool_name, tool_result, list_rows):
                    yield tbl_event
            else:
                yield _sse("status", {"step": "Formatting response with LLM...", "phase": "processing"})
                full_text = ""
                async for token in self._format_tool_response_stream(user_message, tool_name, tool_result):
                    full_text += token
                    yield _sse("answer", {"delta": token})

            if not is_trained_model:
                self.conversation_history.append({"role": "user", "content": user_message})
                self.conversation_history.append({"role": "assistant", "content": full_text})
                if len(self.conversation_history) > 20:
                    self.conversation_history = self.conversation_history[-20:]

            yield _sse("done", {
                "tool_called": tool_name,
                "tool_result": tool_result if not (list_rows and len(list_rows) >= LARGE_THRESHOLD) else {"sap_source": sap_source, "_streamed": True, "_total": len(list_rows) if list_rows else 0},
                "sap_source": sap_source, "report": None, "abap_check": None, "abap_code": None,
            })
            return

        # ── 3. LLM-based routing ───────────────────────────────────────────────
        yield _sse("status", {"step": "Sending to LLM for intent classification...", "phase": "routing_query"})
        yield _sse("intent", {"modules": [], "confidence": 0.7, "routing": "llm_classification"})
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(self.conversation_history)
        messages.append({"role": "user", "content": user_message})

        llm_response = await asyncio.to_thread(self._call_llm, messages)

        tool_call = self._extract_tool_call(llm_response)
        if tool_call and self._is_valid_tool_call(tool_call):
            if allowed_tools is not None and tool_call["name"] not in allowed_tools:
                yield _sse("answer", {"delta": f"Access denied: your role does not permit the '{tool_call['name']}' tool."})
                yield _sse("done", {"tool_called": None, "tool_result": None, "sap_source": None, "report": None, "abap_check": None, "abap_code": None})
                return

            tool_name   = tool_call["name"]
            tool_params = tool_call.get("parameters", {})
            self._apply_ticket_status(tool_name, tool_params, ticket_status)
            _sap_module = tool_name.split("_")[0].upper() if "_" in tool_name else tool_name.upper()
            yield _sse("intent", {"modules": [_sap_module], "confidence": 1.0, "routing": "confirmed"})
            yield _sse("status", {"step": f"Calling SAP tool: {tool_name}", "phase": "calling_tool", "tool": tool_name})

            tool_result = await asyncio.to_thread(execute_tool, tool_name, tool_params)
            sap_source  = tool_result.get("sap_source") or get_sap_source(tool_name)

            list_rows = self._extract_list_data(tool_result)
            LARGE_THRESHOLD = 15
            if list_rows and len(list_rows) >= LARGE_THRESHOLD:
                total = len(list_rows)
                summary = (
                    f"Found **{total} records** from `{tool_name}`.\n"
                    f"Showing all results in the table below."
                )
                full_text = summary
                yield _sse("answer", {"delta": summary})
                yield _sse("status", {"step": f"Streaming {total} records...", "phase": "processing"})
                async for tbl_event in self._stream_tool_table(tool_name, tool_result, list_rows):
                    yield tbl_event
            else:
                yield _sse("status", {"step": "Formatting response with LLM...", "phase": "processing"})
                full_text = ""
                async for token in self._format_tool_response_stream(user_message, tool_name, tool_result):
                    full_text += token
                    yield _sse("answer", {"delta": token})

            if not is_trained_model:
                self.conversation_history.append({"role": "user", "content": user_message})
                self.conversation_history.append({"role": "assistant", "content": full_text})
                if len(self.conversation_history) > 20:
                    self.conversation_history = self.conversation_history[-20:]

            yield _sse("done", {
                "tool_called": tool_name,
                "tool_result": tool_result if not (list_rows and len(list_rows) >= LARGE_THRESHOLD) else {"sap_source": sap_source, "_streamed": True, "_total": len(list_rows) if list_rows else 0},
                "sap_source": sap_source, "report": None, "abap_check": None, "abap_code": None,
            })
            return

        # Action plan intent
        action_plan = self._extract_action_plan(llm_response)
        if action_plan:
            if not is_trained_model:
                self.conversation_history.append({"role": "user", "content": user_message})
                self.conversation_history.append({"role": "assistant", "content": llm_response})
                if len(self.conversation_history) > 20:
                    self.conversation_history = self.conversation_history[-20:]
            yield _sse("answer", {"delta": llm_response})
            yield _sse("done", {"tool_called": "action_plan", "tool_result": action_plan, "sap_source": None, "report": None, "abap_check": None, "abap_code": None})
            return

        # ── 4. Conversational / cloud response ────────────────────────────────
        yield _sse("status", {"step": "Generating conversational response...", "phase": "streaming_answer"})
        # The manager routes through configured providers + failover. The response
        # is already available from the earlier stream call — no separate cloud call needed.
        final_response = llm_response

        if not is_trained_model:
            self.conversation_history.append({"role": "user", "content": user_message})
            self.conversation_history.append({"role": "assistant", "content": final_response})
            if len(self.conversation_history) > 20:
                self.conversation_history = self.conversation_history[-20:]

        # Stream the cloud/llm response in chunks for better UX
        chunk_size = 20
        for i in range(0, len(final_response), chunk_size):
            yield _sse("answer", {"delta": final_response[i:i + chunk_size]})

        yield _sse("done", {"tool_called": None, "tool_result": None, "sap_source": None, "report": None, "abap_check": None, "abap_code": None})
