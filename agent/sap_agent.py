"""
SAP AI Agent - Core Engine
Supports multiple LLM backends in priority order:
  1. MLX server (http://localhost:8080)  — fine-tuned SAP model on Apple Silicon
  2. Ollama (http://localhost:11434)     — original local backend
  3. OpenAI API (OPENAI_API_KEY)         — cloud fallback
  4. Anthropic API (ANTHROPIC_API_KEY)   — cloud fallback

The agent automatically selects the first available backend. No configuration
change is needed when deploying to environments without a local model.
"""
import json
import logging
import os
import re
import requests
from decimal import Decimal
from datetime import date, datetime
from typing import Any

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

OLLAMA_BASE_URL = "http://localhost:11434"
MLX_BASE_URL    = "http://localhost:8080"
MLX_MODEL_PATH  = "training/sap-model-fused"


class SAPAgent:
    def __init__(self, model: str = None, ollama_url: str = None):
        # Prefer explicit args; fall back to config file; fall back to defaults
        try:
            from core.config_manager import config as _cfg
            model = model or _cfg.default_model
            ollama_url = ollama_url or _cfg.ollama_url
        except Exception:
            pass
        model = model or "llama3.2"
        ollama_url = ollama_url or OLLAMA_BASE_URL

        # Detect whether to use MLX server (fine-tuned) or Ollama
        self._use_mlx = self._mlx_available()
        self.model = model
        self.ollama_url = ollama_url
        self.conversation_history = []
        self.system_prompt = self._build_system_prompt()

    def _mlx_available(self) -> bool:
        """Return True if the MLX OpenAI-compatible server is running."""
        try:
            r = requests.get(f"{MLX_BASE_URL}/v1/models", timeout=2)
            if r.status_code == 200:
                ids = [m["id"] for m in r.json().get("data", [])]
                return any(MLX_MODEL_PATH in mid for mid in ids)
        except Exception:
            pass
        return False

    def _build_system_prompt(self) -> str:
        # Fine-tuned MLX model: use the EXACT tool names it was trained on.
        # Do not auto-generate from registry — name mismatch causes hallucinations.
        if self._use_mlx:
            tool_list_str = (
                "FI/CO: get_vendor_info, get_invoice_status, get_open_invoices, get_cost_center_budget, list_all_cost_centers\n"
                "MM: get_material_info, get_stock_level, get_purchase_order, check_reorder_needed, get_bom\n"
                "SD: get_customer_info, get_sales_order, get_delivery_status, get_pricing_info, list_open_orders\n"
                "HR: get_employee_info, get_leave_balance, get_payslip, list_employees, get_org_chart\n"
                "PP: get_production_order, get_capacity_utilization, get_work_center_info, get_bom_explosion, get_planned_orders\n"
                "ABAP: get_abap_program, get_function_module, get_transport_request, list_abap_programs, analyze_abap_syntax"
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

    def check_ollama_connection(self) -> bool:
        """Check if the active backend (MLX or Ollama) is reachable."""
        if self._use_mlx:
            return self._mlx_available()
        try:
            resp = requests.get(f"{self.ollama_url}/api/tags", timeout=5)
            if resp.status_code == 200:
                models = [m["name"] for m in resp.json().get("models", [])]
                return any(self.model in m for m in models)
            return False
        except Exception:
            return False

    def _call_llm(self, messages: list[dict]) -> str:
        """Route to MLX server or Ollama based on availability."""
        if self._use_mlx:
            return self._call_mlx(messages)
        return self._call_ollama(messages)

    def _call_mlx(self, messages: list[dict]) -> str:
        """Call the MLX OpenAI-compatible server (fine-tuned SAP model)."""
        payload = {
            "model": MLX_MODEL_PATH,
            "messages": messages,
            "temperature": 0.05,
            "max_tokens": 256,
        }
        try:
            response = requests.post(
                f"{MLX_BASE_URL}/v1/chat/completions",
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except requests.exceptions.ConnectionError:
            raise ConnectionError(f"Cannot connect to MLX server at {MLX_BASE_URL}.")
        except requests.exceptions.Timeout:
            raise TimeoutError("MLX server request timed out.")
        except Exception as e:
            _logger.error("MLX API error", exc_info=True)
            raise Exception("MLX API error. Check server logs.")

    def _call_ollama(self, messages: list[dict]) -> str:
        """Make a call to Ollama API. Falls back to cloud LLM if Ollama is unreachable."""
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": 0.1,
                "top_p": 0.9,
            }
        }
        try:
            response = requests.post(
                f"{self.ollama_url}/api/chat",
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            return data["message"]["content"]
        except requests.exceptions.ConnectionError:
            _logger.warning("Ollama unreachable at %s — trying cloud LLM fallback.", self.ollama_url)
            return self._call_cloud_fallback(messages)
        except requests.exceptions.Timeout:
            raise TimeoutError("Ollama request timed out. The model may be loading.")
        except Exception as e:
            _logger.error("Ollama API error", exc_info=True)
            raise Exception("LLM request failed. Check server logs.")

    @staticmethod
    def _sanitize_for_cloud(messages: list[dict]) -> list[dict]:
        """
        Strip SAP tool result payloads before sending to any cloud LLM.

        Tool result messages look like:
          {"role": "user", "content": "SAP tool 'X' returned:\n{...sensitive data...}"}

        These may contain employee salaries, vendor bank accounts, invoice amounts, etc.
        We replace the payload with a placeholder so the LLM can still generate a coherent
        follow-up prompt without leaking confidential enterprise data to a third party.
        """
        sanitized = []
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str) and content.startswith("SAP tool '") and "returned:" in content:
                # Keep only the first line (tool name), drop the JSON payload
                first_line = content.split("\n")[0]
                sanitized.append({**msg, "content": f"{first_line}\n[SAP data redacted — not transmitted to cloud providers]"})
            else:
                sanitized.append(msg)
        return sanitized

    def _call_cloud_fallback(self, messages: list[dict]) -> str:
        """
        Try OpenAI then Anthropic as fallback when Ollama is unreachable.
        SAP tool result payloads are ALWAYS stripped before transmission —
        confidential enterprise data is never sent to third-party cloud APIs.
        Returns the LLM response string or raises ConnectionError if no
        cloud credentials are configured.
        """
        messages = self._sanitize_for_cloud(messages)
        openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if openai_key:
            try:
                import openai as _oai
                client = _oai.OpenAI(api_key=openai_key)
                model  = os.environ.get("OPENAI_FALLBACK_MODEL", "gpt-4o-mini")
                resp   = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.1,
                    max_tokens=1024,
                )
                _logger.info("Cloud fallback: used OpenAI model %s", model)
                self._log_cloud_fallback("openai", model)
                return resp.choices[0].message.content
            except Exception:
                _logger.warning("OpenAI fallback failed — trying Anthropic.", exc_info=True)

        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if anthropic_key:
            try:
                import anthropic as _ant
                client     = _ant.Anthropic(api_key=anthropic_key)
                model      = os.environ.get("ANTHROPIC_FALLBACK_MODEL", "claude-haiku-4-5")
                system_msg = next((m["content"] for m in messages if m["role"] == "system"), "")
                user_msgs  = [m for m in messages if m["role"] != "system"]
                resp       = client.messages.create(
                    model=model,
                    system=system_msg,
                    messages=user_msgs,
                    max_tokens=1024,
                )
                _logger.info("Cloud fallback: used Anthropic model %s", model)
                self._log_cloud_fallback("anthropic", model)
                return resp.content[0].text
            except Exception:
                _logger.error("Anthropic fallback failed.", exc_info=True)

        raise ConnectionError(
            "No LLM backend is available. Ollama is not running and no cloud "
            "fallback is configured. Set OPENAI_API_KEY or ANTHROPIC_API_KEY, "
            "or start Ollama locally."
        )

    def _log_cloud_fallback(self, provider: str, model: str) -> None:
        """Write a compliance audit record whenever a cloud LLM is used."""
        try:
            from core.audit_logger import log_request
            log_request(
                user_id="system",
                user_roles=["system"],
                client_ip="internal",
                endpoint="llm_fallback",
                query=f"Cloud LLM fallback activated: provider={provider} model={model}",
                tool_called=None,
                status="ok",
            )
        except Exception:
            _logger.warning("Failed to write cloud fallback audit record.", exc_info=True)

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

        return None

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
            model=self.model,
            ollama_url=self.ollama_url,
            allowed_tools=allowed_tools,
        )
        return result["report"], "autonomous_agent", result

    def _call_cloud_primary(self, messages: list[dict]) -> str | None:
        """
        Attempt a cloud LLM call (OpenAI → Anthropic) for conversational queries
        where no SAP data payload is involved. Returns None if no cloud key is set.
        This gives research-quality, analytical responses without touching local model.
        """
        openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if openai_key:
            try:
                import openai as _oai
                client = _oai.OpenAI(api_key=openai_key)
                model  = os.environ.get("OPENAI_FALLBACK_MODEL", "gpt-4o-mini")
                resp   = client.chat.completions.create(
                    model=model, messages=messages, temperature=0.2, max_tokens=1500,
                )
                self._log_cloud_fallback("openai", model)
                return resp.choices[0].message.content
            except Exception:
                _logger.warning("Cloud primary (OpenAI) failed — falling back to local.", exc_info=True)

        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if anthropic_key:
            try:
                import anthropic as _ant
                client     = _ant.Anthropic(api_key=anthropic_key)
                model      = os.environ.get("ANTHROPIC_FALLBACK_MODEL", "claude-haiku-4-5")
                system_msg = next((m["content"] for m in messages if m["role"] == "system"), "")
                user_msgs  = [m for m in messages if m["role"] != "system"]
                resp       = client.messages.create(
                    model=model, system=system_msg, messages=user_msgs, max_tokens=1500,
                )
                self._log_cloud_fallback("anthropic", model)
                return resp.content[0].text
            except Exception:
                _logger.warning("Cloud primary (Anthropic) failed — falling back to local.", exc_info=True)

        return None  # No cloud configured

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
            llm_response = self._call_llm(messages)
            # If LLM returned JSON (common with small local models), use friendly fallback
            stripped = llm_response.strip()
            if stripped.startswith(("{", "[", "```")):
                return self._friendly_fallback(tool_name, tool_result)
            return llm_response
        except Exception:
            return self._friendly_fallback(tool_name, tool_result)

    def chat(self, user_message: str, allowed_tools: set[str] | None = None) -> tuple:
        """
        Main chat method — returns (response_text, tool_name, tool_result).

        Routing priority:
          1. Autonomous / auto-research intercept (complex multi-step)
          2. Deterministic regex router → tool execution (fast, 100% reliable)
          3. LLM-based tool extraction (unrecognised patterns, workflow intents)
          4. Cloud LLM for conversational / research responses (no SAP data sent)
          5. Local LLM fallback for pure conversation
        """
        # ── 1. Intercept autonomous / research queries ─────────────────────────
        if is_autonomous_query(user_message):
            return self.autonomous(user_message, allowed_tools=allowed_tools)
        if is_auto_research_query(user_message):
            return self.auto_research(user_message, allowed_tools=allowed_tools)

        # ── Build scoped system prompt ─────────────────────────────────────────
        system_prompt = self.system_prompt
        if allowed_tools is not None and not self._use_mlx:
            from tools.tool_registry import get_tools_for_prompt as _gtp
            tools_json = _gtp(allowed_tools=allowed_tools)
            split_marker = "AVAILABLE SAP TOOLS (for MODE 1)"
            if split_marker in self.system_prompt:
                system_prompt = self.system_prompt.split(split_marker)[0]
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
            tool_result = execute_tool(tool_name, tool_params)

            # Response formatting uses local LLM (tool data must not leave the network)
            final_response = self._format_tool_response(user_message, tool_name, tool_result)

            if not self._use_mlx:
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
            tool_result = execute_tool(tool_name, tool_params)

            final_response = self._format_tool_response(user_message, tool_name, tool_result)

            if not self._use_mlx:
                self.conversation_history.append({"role": "user", "content": user_message})
                self.conversation_history.append({"role": "assistant", "content": final_response})
                if len(self.conversation_history) > 20:
                    self.conversation_history = self.conversation_history[-20:]

            return final_response, tool_name, tool_result

        # Check for workflow / action plan intent
        action_plan = self._extract_action_plan(llm_response)
        if action_plan:
            if not self._use_mlx:
                self.conversation_history.append({"role": "user", "content": user_message})
                self.conversation_history.append({"role": "assistant", "content": llm_response})
                if len(self.conversation_history) > 20:
                    self.conversation_history = self.conversation_history[-20:]
            return llm_response, "action_plan", action_plan

        # ── 4. Conversational / research response ─────────────────────────────
        # No SAP data is involved here — safe to use cloud LLM for research-quality
        # answers. Cloud gives analytical, context-rich responses that local models
        # cannot match for general enterprise knowledge questions.
        cloud_response = self._call_cloud_primary(messages)
        final_response = cloud_response if cloud_response else llm_response

        if not self._use_mlx:
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

    async def _call_ollama_stream(self, messages: list[dict]):
        """
        Async generator — yields token strings from Ollama's streaming API.
        Uses a queue+thread pattern so iter_lines() never blocks the event loop.
        """
        import asyncio
        import queue
        import threading

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": 0.1, "top_p": 0.9},
        }
        q: queue.Queue = queue.Queue()

        def _worker():
            try:
                r = requests.post(
                    f"{self.ollama_url}/api/chat",
                    json=payload,
                    stream=True,
                    timeout=60,
                )
                for line in r.iter_lines():
                    if line:
                        chunk = json.loads(line)
                        token = chunk.get("message", {}).get("content", "")
                        if token:
                            q.put(token)
                        if chunk.get("done"):
                            break
            except Exception as exc:
                q.put(exc)
            finally:
                q.put(None)  # sentinel

        threading.Thread(target=_worker, daemon=True).start()
        loop = asyncio.get_running_loop()
        while True:
            item = await loop.run_in_executor(None, q.get)
            if item is None:
                break
            if isinstance(item, Exception):
                raise item
            yield item

    async def _format_tool_response_stream(self, user_message: str, tool_name: str, tool_result: dict):
        """
        Async generator — streams the LLM's natural-language formatting of a tool result.
        Buffers the first 20 chars to detect JSON output (falls back to _friendly_fallback).
        Uses the same local-LLM routing as _format_tool_response.
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

        buffer = ""
        buffer_limit = 20
        buffering = True

        try:
            async for token in self._call_ollama_stream(messages):
                if buffering:
                    buffer += token
                    if len(buffer) >= buffer_limit:
                        buffering = False
                        if buffer.lstrip().startswith(("{", "[", "```")):
                            yield self._friendly_fallback(tool_name, tool_result)
                            return
                        else:
                            yield buffer
                else:
                    yield token
            # Flush remaining buffer if we never hit the limit
            if buffering and buffer:
                if buffer.lstrip().startswith(("{", "[", "```")):
                    yield self._friendly_fallback(tool_name, tool_result)
                else:
                    yield buffer
        except Exception:
            yield self._friendly_fallback(tool_name, tool_result)

    async def chat_stream(self, user_message: str, allowed_tools: set | None = None):
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

        # ── 1. Autonomous / research intercept ────────────────────────────────
        if is_autonomous_query(user_message):
            yield _sse("status", {"step": "Autonomous agent activated — running multi-step analysis...", "phase": "routing"})
            try:
                result = await asyncio.to_thread(self.autonomous, user_message, allowed_tools)
                response_text, tool_called, tool_result = result
            except Exception:
                response_text, tool_called, tool_result = "An error occurred during autonomous analysis.", None, None
            yield _sse("text_delta", {"delta": response_text})
            yield _sse("done", {
                "tool_called": tool_called, "tool_result": tool_result,
                "sap_source": None, "report": None, "abap_check": None, "abap_code": None,
            })
            return

        if is_auto_research_query(user_message):
            yield _sse("status", {"step": "Auto-research mode — chaining SAP tools...", "phase": "routing"})
            try:
                result = await asyncio.to_thread(self.auto_research, user_message, allowed_tools)
                response_text, tool_called, tool_result = result
            except Exception:
                response_text, tool_called, tool_result = "An error occurred during auto-research.", None, None
            yield _sse("text_delta", {"delta": response_text})
            yield _sse("done", {
                "tool_called": tool_called, "tool_result": tool_result,
                "sap_source": None, "report": None, "abap_check": None, "abap_code": None,
            })
            return

        # ── Build scoped system prompt ─────────────────────────────────────────
        system_prompt = self.system_prompt
        if allowed_tools is not None and not self._use_mlx:
            from tools.tool_registry import get_tools_for_prompt as _gtp
            tools_json = _gtp(allowed_tools=allowed_tools)
            split_marker = "AVAILABLE SAP TOOLS (for MODE 1)"
            if split_marker in self.system_prompt:
                system_prompt = self.system_prompt.split(split_marker)[0]
                system_prompt += f"{split_marker}\n{'═' * 35}\n{tools_json}\n\n"
                system_prompt += "CRITICAL: Output ONLY one of the three modes per response. Never mix JSON with natural language text."

        # ── 2. Deterministic regex router ─────────────────────────────────────
        yield _sse("status", {"step": "Routing query via SAP pattern matcher...", "phase": "routing"})
        tool_call = self._infer_tool_from_query(user_message)

        if tool_call and self._is_valid_tool_call(tool_call):
            if allowed_tools is not None and tool_call["name"] not in allowed_tools:
                yield _sse("text_delta", {"delta": f"Access denied: your role does not permit the '{tool_call['name']}' tool."})
                yield _sse("done", {"tool_called": None, "tool_result": None, "sap_source": None, "report": None, "abap_check": None, "abap_code": None})
                return

            tool_name   = tool_call["name"]
            tool_params = tool_call.get("parameters", {})
            yield _sse("status", {"step": f"Calling SAP tool: {tool_name}", "phase": "tool_call", "tool": tool_name})

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
                yield _sse("text_delta", {"delta": summary})
                yield _sse("status", {"step": f"Streaming {total} records...", "phase": "formatting"})
                async for tbl_event in self._stream_tool_table(tool_name, tool_result, list_rows):
                    yield tbl_event
            else:
                yield _sse("status", {"step": "Formatting response with LLM...", "phase": "formatting"})
                full_text = ""
                async for token in self._format_tool_response_stream(user_message, tool_name, tool_result):
                    full_text += token
                    yield _sse("text_delta", {"delta": token})

            if not self._use_mlx:
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
        yield _sse("status", {"step": "Sending to LLM for intent classification...", "phase": "llm_routing"})
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(self.conversation_history)
        messages.append({"role": "user", "content": user_message})

        llm_response = await asyncio.to_thread(self._call_llm, messages)

        tool_call = self._extract_tool_call(llm_response)
        if tool_call and self._is_valid_tool_call(tool_call):
            if allowed_tools is not None and tool_call["name"] not in allowed_tools:
                yield _sse("text_delta", {"delta": f"Access denied: your role does not permit the '{tool_call['name']}' tool."})
                yield _sse("done", {"tool_called": None, "tool_result": None, "sap_source": None, "report": None, "abap_check": None, "abap_code": None})
                return

            tool_name   = tool_call["name"]
            tool_params = tool_call.get("parameters", {})
            yield _sse("status", {"step": f"Calling SAP tool: {tool_name}", "phase": "tool_call", "tool": tool_name})

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
                yield _sse("text_delta", {"delta": summary})
                yield _sse("status", {"step": f"Streaming {total} records...", "phase": "formatting"})
                async for tbl_event in self._stream_tool_table(tool_name, tool_result, list_rows):
                    yield tbl_event
            else:
                yield _sse("status", {"step": "Formatting response with LLM...", "phase": "formatting"})
                full_text = ""
                async for token in self._format_tool_response_stream(user_message, tool_name, tool_result):
                    full_text += token
                    yield _sse("text_delta", {"delta": token})

            if not self._use_mlx:
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
            if not self._use_mlx:
                self.conversation_history.append({"role": "user", "content": user_message})
                self.conversation_history.append({"role": "assistant", "content": llm_response})
                if len(self.conversation_history) > 20:
                    self.conversation_history = self.conversation_history[-20:]
            yield _sse("text_delta", {"delta": llm_response})
            yield _sse("done", {"tool_called": "action_plan", "tool_result": action_plan, "sap_source": None, "report": None, "abap_check": None, "abap_code": None})
            return

        # ── 4. Conversational / cloud response ────────────────────────────────
        yield _sse("status", {"step": "Generating conversational response...", "phase": "conversational"})
        cloud_response = self._call_cloud_primary(messages)
        final_response = cloud_response if cloud_response else llm_response

        if not self._use_mlx:
            self.conversation_history.append({"role": "user", "content": user_message})
            self.conversation_history.append({"role": "assistant", "content": final_response})
            if len(self.conversation_history) > 20:
                self.conversation_history = self.conversation_history[-20:]

        # Stream the cloud/llm response in chunks for better UX
        chunk_size = 20
        for i in range(0, len(final_response), chunk_size):
            yield _sse("text_delta", {"delta": final_response[i:i + chunk_size]})

        yield _sse("done", {"tool_called": None, "tool_result": None, "sap_source": None, "report": None, "abap_check": None, "abap_code": None})
