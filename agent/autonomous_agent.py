"""
SAP Autonomous Agent
Implements a true LLM-driven autonomous loop:
  1. Receives a complex query
  2. Uses the LLM to plan the next best tool call given current findings
  3. Executes the tool and observes the result
  4. Loops until the LLM decides research is complete (max MAX_ITERATIONS)
  5. Runs a final reasoning pass: key insights, risks, recommended actions

This is distinct from AutoResearcher (which uses fixed RESEARCH_PLANS).
AutonomousAgent lets the LLM decide what to investigate next.
"""
from __future__ import annotations
import json
import re
import requests
from datetime import datetime
from typing import Callable


MAX_ITERATIONS = 8
OLLAMA_BASE_URL = "http://localhost:11434"


# ─── System prompt for the autonomous planning step ───────────────────────────

AUTONOMOUS_PLANNER_PROMPT = """You are an SAP autonomous research agent. Your job is to answer a complex SAP business query by calling tools one at a time.

At each step you see:
- The original query
- What you have already discovered (tool results so far)
- The list of available tools

You must output EXACTLY ONE of:
A) A tool call JSON to gather more data:
   {"action": "call_tool", "tool": "TOOL_NAME", "parameters": {"PARAM": "VALUE"}, "reasoning": "why this tool next"}

B) A completion signal when you have enough data:
   {"action": "complete", "reasoning": "why research is complete"}

RULES:
- Never call the same tool twice with the same parameters
- Always justify your choice with a reasoning field
- If you cannot find any relevant tool, output the complete signal
- Prefer specific tools (by entity ID) over generic list tools
- After 4+ tool calls, consider whether you have enough to answer the query

Available tools:
{tools_json}
"""

AUTONOMOUS_REASONER_PROMPT = """You are an SAP Enterprise AI Agent performing business decision reasoning.

Given the following SAP data collected for the query: "{query}"

Collected data:
{collected_data}

Provide a structured analysis with:

1. KEY FINDINGS — what the data reveals (3-5 bullet points)
2. BUSINESS RISKS — risks identified from this data (severity: HIGH/MEDIUM/LOW)
3. RECOMMENDED ACTIONS — concrete next steps with SAP T-codes where applicable
4. DECISION SUMMARY — a 2-sentence executive summary for management

Format your response in clear markdown. Be specific and enterprise-ready.
Never invent data not present in the collected results."""


class AutonomousAgent:
    """
    LLM-driven autonomous SAP research agent.
    Uses iterative plan-execute-observe loop with business reasoning at the end.
    """

    def __init__(self, model: str = "llama3.2", ollama_url: str = None):
        try:
            from core.config_manager import config as _cfg
            self.model = model or _cfg.default_model
            self.ollama_url = ollama_url or _cfg.ollama_url
        except Exception:
            self.model = model or "llama3.2"
            self.ollama_url = ollama_url or OLLAMA_BASE_URL

    # ── Public API ─────────────────────────────────────────────────────────────

    def run(self, query: str, execute_tool_fn: Callable, allowed_tools: set[str] | None = None) -> dict:
        """
        Run the autonomous agent loop.
        Returns a dict with: report, reasoning, tool_calls, collected_data, anomalies, success
        """
        from tools.tool_registry import get_tools_for_prompt

        tools_json = get_tools_for_prompt(allowed_tools=allowed_tools)
        planner_prompt = AUTONOMOUS_PLANNER_PROMPT.format(tools_json=tools_json)

        collected_data: dict[str, dict] = {}   # tool_name+params_key → result
        tool_call_log: list[dict] = []          # ordered log of tool calls
        called_keys: set[str] = set()           # deduplication

        # ── Autonomous loop ───────────────────────────────────────────────────
        for iteration in range(MAX_ITERATIONS):
            # Build context for planner
            context = self._build_context(query, collected_data, tool_call_log)
            plan_response = self._call_llm([
                {"role": "system", "content": planner_prompt},
                {"role": "user",   "content": context},
            ])

            decision = self._parse_decision(plan_response)
            if not decision:
                # Malformed response — stop
                tool_call_log.append({"iteration": iteration + 1, "action": "parse_error", "raw": plan_response[:200]})
                break

            if decision.get("action") == "complete":
                tool_call_log.append({"iteration": iteration + 1, "action": "complete", "reasoning": decision.get("reasoning", "")})
                break

            if decision.get("action") == "call_tool":
                tool_name = decision.get("tool", "")
                params    = decision.get("parameters", {})
                reasoning = decision.get("reasoning", "")

                # Deduplicate calls
                call_key = f"{tool_name}:{json.dumps(params, sort_keys=True)}"
                if call_key in called_keys:
                    tool_call_log.append({"iteration": iteration + 1, "action": "skip_duplicate", "tool": tool_name})
                    # Signal complete if we're looping
                    break
                called_keys.add(call_key)

                # Execute tool
                try:
                    result = execute_tool_fn(tool_name, params)
                except Exception as e:
                    result = {"status": "ERROR", "message": str(e)}

                collected_data[call_key] = {"tool": tool_name, "parameters": params, "result": result}
                tool_call_log.append({
                    "iteration": iteration + 1,
                    "action": "call_tool",
                    "tool": tool_name,
                    "parameters": params,
                    "reasoning": reasoning,
                    "result_status": result.get("status", "OK") if isinstance(result, dict) else "OK",
                })

        # ── Reasoning pass ────────────────────────────────────────────────────
        reasoning_output = self._run_reasoning(query, collected_data)

        # ── Format report ─────────────────────────────────────────────────────
        report = self._format_report(query, tool_call_log, collected_data, reasoning_output)

        return {
            "report": report,
            "reasoning": reasoning_output,
            "tool_calls": tool_call_log,
            "collected_data": {k: v["result"] for k, v in collected_data.items()},
            "tools_used": list({entry["tool"] for entry in tool_call_log if entry.get("action") == "call_tool"}),
            "iterations": len([e for e in tool_call_log if e.get("action") in ("call_tool", "complete")]),
            "success": len(collected_data) > 0,
        }

    # ── LLM helpers ───────────────────────────────────────────────────────────

    def _call_llm(self, messages: list[dict]) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.1, "top_p": 0.9},
        }
        try:
            resp = requests.post(f"{self.ollama_url}/api/chat", json=payload, timeout=120)
            resp.raise_for_status()
            return resp.json()["message"]["content"]
        except Exception as e:
            return json.dumps({"action": "complete", "reasoning": f"LLM error: {str(e)}"})

    def _parse_decision(self, response: str) -> dict | None:
        """Extract the decision JSON from the LLM response."""
        # Direct JSON parse
        try:
            data = json.loads(response.strip())
            if "action" in data:
                return data
        except Exception:
            pass

        # Markdown code block
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                if "action" in data:
                    return data
            except Exception:
                pass

        # Bracket scan for {"action"
        start = response.find('{"action"')
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
                            if "action" in data:
                                return data
                        except Exception:
                            pass
                        break

        return None

    def _build_context(self, query: str, collected_data: dict, tool_call_log: list) -> str:
        """Build the context message for the planner LLM."""
        lines = [f"QUERY: {query}", ""]

        if not collected_data:
            lines.append("NO DATA COLLECTED YET — decide the first tool to call.")
        else:
            lines.append(f"TOOLS CALLED SO FAR ({len(tool_call_log)}):")
            for entry in tool_call_log:
                if entry.get("action") == "call_tool":
                    status = entry.get("result_status", "?")
                    lines.append(f"  - {entry['tool']}({entry['parameters']}) → {status}")
            lines.append("")
            lines.append("COLLECTED DATA SUMMARY:")
            for key, item in collected_data.items():
                result = item["result"]
                if isinstance(result, dict):
                    # Show compact summary
                    summary = {k: v for k, v in result.items() if k not in ("sap_source",) and not isinstance(v, (dict, list))}
                    lines.append(f"  [{item['tool']}]: {json.dumps(summary)}")
                else:
                    lines.append(f"  [{item['tool']}]: {str(result)[:200]}")
            lines.append("")

        lines.append("What is the next best tool to call? Or is the research complete?")
        return "\n".join(lines)

    def _run_reasoning(self, query: str, collected_data: dict) -> str:
        """Run the LLM reasoning pass over all collected data."""
        if not collected_data:
            return "No data was collected — unable to perform reasoning."

        # Build collected data summary for reasoning
        data_summary = []
        for key, item in collected_data.items():
            result = item["result"]
            if isinstance(result, dict):
                clean = {k: v for k, v in result.items() if k != "sap_source"}
                data_summary.append(f"### {item['tool']}\n{json.dumps(clean, indent=2)}")
            else:
                data_summary.append(f"### {item['tool']}\n{str(result)}")

        reasoner_prompt = AUTONOMOUS_REASONER_PROMPT.format(
            query=query,
            collected_data="\n\n".join(data_summary),
        )
        return self._call_llm([
            {"role": "system", "content": "You are a senior SAP business consultant providing enterprise-grade analysis."},
            {"role": "user",   "content": reasoner_prompt},
        ])

    def _format_report(
        self,
        query: str,
        tool_call_log: list,
        collected_data: dict,
        reasoning: str,
    ) -> str:
        """Format the autonomous research output as markdown."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        calls_made = [e for e in tool_call_log if e.get("action") == "call_tool"]

        lines = [
            f"## Autonomous SAP Research Report",
            f"**Query:** {query}",
            f"**Generated:** {now}  |  **Iterations:** {len(calls_made)}  |  **Mode:** Autonomous Agent",
            "",
            "---",
            "",
            "## Business Analysis",
            reasoning,
            "",
            "---",
            "",
            "## Research Execution Log",
            "",
        ]

        if calls_made:
            lines.append("| Step | Tool | Parameters | Result |")
            lines.append("|---|---|---|---|")
            for i, entry in enumerate(calls_made, 1):
                params_str = json.dumps(entry.get("parameters", {}))
                status = entry.get("result_status", "OK")
                reasoning_note = entry.get("reasoning", "")[:60]
                lines.append(f"| {i} | `{entry['tool']}` | `{params_str}` | {status} |")
            lines.append("")
            lines.append("**Agent reasoning per step:**")
            for i, entry in enumerate(calls_made, 1):
                lines.append(f"- Step {i}: {entry.get('reasoning', 'N/A')}")
        else:
            lines.append("*No tools were executed.*")

        return "\n".join(lines)


# ─── Convenience function ──────────────────────────────────────────────────────

def run_autonomous_agent(
    query: str,
    execute_tool_fn: Callable,
    model: str = None,
    ollama_url: str = None,
    allowed_tools: set[str] | None = None,
) -> dict:
    """Top-level function to run the autonomous agent."""
    agent = AutonomousAgent(model=model, ollama_url=ollama_url)
    return agent.run(query, execute_tool_fn, allowed_tools=allowed_tools)


# ─── Trigger detection ─────────────────────────────────────────────────────────

AUTONOMOUS_TRIGGERS = [
    "why", "should i", "recommend", "decision", "what do you think",
    "advise", "help me decide", "is it worth", "compare", "best option",
    "autonomous", "agent mode", "deep analysis", "business decision",
    "root cause", "impact of", "what will happen if", "strategic",
]


def is_autonomous_query(query: str) -> bool:
    """Return True if query should use the autonomous agent (not just auto_research)."""
    q = query.lower()
    return any(trigger in q for trigger in AUTONOMOUS_TRIGGERS)
