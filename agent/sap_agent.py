"""
SAP AI Agent - Core Engine
Supports two local LLM backends:
  - Ollama (http://localhost:11434)  — original backend
  - MLX server (http://localhost:8080) — fine-tuned SAP model on Apple Silicon
"""
import json
import re
import requests
from typing import Any
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
            from config_manager import config as _cfg
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
                timeout=120,
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except requests.exceptions.ConnectionError:
            raise ConnectionError(f"Cannot connect to MLX server at {MLX_BASE_URL}.")
        except Exception as e:
            raise Exception(f"MLX API error: {str(e)}")

    def _call_ollama(self, messages: list[dict]) -> str:
        """Make a call to Ollama API"""
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
                timeout=120
            )
            response.raise_for_status()
            data = response.json()
            return data["message"]["content"]
        except requests.exceptions.ConnectionError:
            raise ConnectionError(f"Cannot connect to Ollama at {self.ollama_url}. Make sure Ollama is running.")
        except requests.exceptions.Timeout:
            raise TimeoutError("Ollama request timed out. The model may be loading.")
        except Exception as e:
            raise Exception(f"Ollama API error: {str(e)}")

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

    def chat(self, user_message: str, allowed_tools: set[str] | None = None) -> tuple:
        """
        Main chat method - process user message and return (response, tool_name, tool_result).

        allowed_tools: if provided (RBAC), the system prompt and tool execution are
                       restricted to this set of tool names.
        """
        # Autonomous Agent: intercept for complex decision/reasoning queries
        if is_autonomous_query(user_message):
            return self.autonomous(user_message, allowed_tools=allowed_tools)

        # Auto Research: intercept before normal LLM flow
        if is_auto_research_query(user_message):
            return self.auto_research(user_message, allowed_tools=allowed_tools)

        # Build a role-scoped system prompt if RBAC filtering is active
        system_prompt = self.system_prompt
        if allowed_tools is not None and not self._use_mlx:
            from tools.tool_registry import get_tools_for_prompt as _gtp
            tools_json = _gtp(allowed_tools=allowed_tools)
            split_marker = "AVAILABLE SAP TOOLS (for MODE 1)"
            if split_marker in self.system_prompt:
                system_prompt = self.system_prompt.split(split_marker)[0]
                system_prompt += f"{split_marker}\n{'═' * 35}\n{tools_json}\n\n"
                system_prompt += "CRITICAL: Output ONLY one of the three modes per response. Never mix JSON with natural language text."
            else:
                # Fallback for MLX or unexpected format
                system_prompt = self.system_prompt

        # Build message history
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(self.conversation_history)
        messages.append({"role": "user", "content": user_message})

        # Step 1: Get LLM response
        llm_response = self._call_llm(messages)

        # Step 2: Check if tool call is needed
        tool_call = self._extract_tool_call(llm_response)

        # Step 2a: Check if response is an action plan (workflow/create/approve intent)
        if not (tool_call and self._is_valid_tool_call(tool_call)):
            action_plan = self._extract_action_plan(llm_response)
            if action_plan:
                # Return action plan as structured response — no tool execution
                if not self._use_mlx:
                    self.conversation_history.append({"role": "user", "content": user_message})
                    self.conversation_history.append({"role": "assistant", "content": llm_response})
                    if len(self.conversation_history) > 20:
                        self.conversation_history = self.conversation_history[-20:]
                return llm_response, "action_plan", action_plan

        # Step 2b: Fallback — if LLM didn't produce a valid tool call, infer from query
        if not (tool_call and self._is_valid_tool_call(tool_call)):
            tool_call = self._infer_tool_from_query(user_message)

        if tool_call and self._is_valid_tool_call(tool_call):
            tool_name = tool_call.get("name", "")
            tool_params = tool_call.get("parameters", {})

            # Step 3: Execute SAP tool
            tool_result = execute_tool(tool_name, tool_params)

            # Step 4: Get final response with tool results
            # For MLX fine-tuned model: send a fresh 3-message context (no history)
            # so the response prompt stays within the 512-token training window.
            if self._use_mlx:
                response_messages = [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_message},
                    {"role": "assistant", "content": llm_response},
                    {
                        "role": "user",
                        "content": f"SAP tool '{tool_name}' returned:\n{json.dumps(tool_result, indent=2)}\n\nProvide a clear, helpful response."
                    },
                ]
            else:
                response_messages = messages + [
                    {"role": "assistant", "content": llm_response},
                    {
                        "role": "user",
                        "content": f"SAP tool '{tool_name}' returned:\n{json.dumps(tool_result, indent=2)}\n\nProvide a clear, helpful response to the user's original question based on this SAP data."
                    },
                ]

            final_response = self._call_llm(response_messages)

            # Update conversation history (Ollama only; MLX stays stateless)
            if not self._use_mlx:
                self.conversation_history.append({"role": "user", "content": user_message})
                self.conversation_history.append({"role": "assistant", "content": final_response})
                if len(self.conversation_history) > 20:
                    self.conversation_history = self.conversation_history[-20:]

            return final_response, tool_name, tool_result
        else:
            # Direct conversational response
            if not self._use_mlx:
                self.conversation_history.append({"role": "user", "content": user_message})
                self.conversation_history.append({"role": "assistant", "content": llm_response})
                if len(self.conversation_history) > 20:
                    self.conversation_history = self.conversation_history[-20:]

            return llm_response, None, None

    def reset_conversation(self):
        """Clear conversation history"""
        self.conversation_history = []
