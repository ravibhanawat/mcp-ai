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
from tools.tool_registry import TOOLS, execute_tool, get_tools_for_prompt, get_sap_source

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
                "You are an SAP ERP AI Assistant. "
                "When a query requires SAP data, respond ONLY with this exact JSON format:\n"
                '{"tool_call": {"name": "<tool_name>", "parameters": {"<key>": "<value>"}}}\n'
                "After receiving tool results, give a clear natural language answer.\n"
                "Never mix JSON and text in the same reply.\n\n"
                "Available tools:\n" + tool_list_str
            )

        # Ollama path: full tool definitions for zero-shot generalisation
        tools_json = get_tools_for_prompt()
        return f"""You are an intelligent SAP ERP AI Assistant. You help users interact with SAP modules including FI/CO (Finance), MM (Materials Management), SD (Sales & Distribution), HR (Human Resources), PP (Production Planning), and ABAP (Development & Basis).

You have access to the following SAP tools:
{tools_json}

INSTRUCTIONS:
1. Analyze the user's query carefully
2. If a tool call is needed, respond ONLY with a JSON object in this exact format:
   {{"tool_call": {{"name": "tool_name", "parameters": {{"param1": "value1"}}}}}}
3. After receiving tool results, provide a clear, helpful natural language response
4. If no tool is needed (e.g., general question), respond conversationally
5. Always be precise with IDs - use exact IDs from the conversation or ask the user if unclear
6. For currency values, always include the currency code (INR, EUR, USD)

Respond ONLY with either a valid JSON tool_call or a natural language answer. Never mix both."""

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

        # Try finding raw JSON in text
        json_match = re.search(r'\{"tool_call":\s*\{.*?\}\s*\}', response, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                if "tool_call" in data:
                    return data["tool_call"]
            except Exception:
                pass

        return None

    def chat(self, user_message: str, allowed_tools: set[str] | None = None) -> tuple:
        """
        Main chat method - process user message and return (response, tool_name, tool_result).

        allowed_tools: if provided (RBAC), the system prompt and tool execution are
                       restricted to this set of tool names.
        """
        # Build a role-scoped system prompt if RBAC filtering is active
        system_prompt = self.system_prompt
        if allowed_tools is not None and not self._use_mlx:
            from tools.tool_registry import get_tools_for_prompt as _gtp
            tools_json = _gtp(allowed_tools=allowed_tools)
            system_prompt = self.system_prompt.split("You have access to the following SAP tools:")[0]
            system_prompt += f"You have access to the following SAP tools:\n{tools_json}\n\n"
            system_prompt += "Respond ONLY with either a valid JSON tool_call or a natural language answer. Never mix both."

        # Build message history
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(self.conversation_history)
        messages.append({"role": "user", "content": user_message})

        # Step 1: Get LLM response
        llm_response = self._call_llm(messages)

        # Step 2: Check if tool call is needed
        tool_call = self._extract_tool_call(llm_response)

        if tool_call:
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
