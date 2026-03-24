"""
SAP LLM-Driven Report Agent
============================
Two-pass LLM approach for generating chart/table payloads from natural language:

  Pass 1 — PLANNER:
    LLM reads the user query + available tools and outputs a structured plan:
    which tools to call, what chart type, how to aggregate the results.

  Pass 2 — FORMATTER:
    LLM receives all raw tool results + the original query and outputs the
    final ReportPayload JSON that the frontend ReportWidget renders directly.

Fallback: if LLM is unreachable or JSON parsing fails, the agent falls back
to the original hardcoded keyword-based fetchers (zero LLM dependency).

Supported chart types: pie | bar | heatmap | pivot | table
"""
from __future__ import annotations

import json
import logging
import re
import requests
from typing import Any

_logger = logging.getLogger("report_agent")

OLLAMA_BASE_URL = "http://localhost:11434"
MAX_TOOL_CALLS  = 5          # planner may request up to this many tool calls
_EMP_ID_RE      = re.compile(r'\bEMP\d+\b', re.IGNORECASE)

# ─── LLM Prompts ─────────────────────────────────────────────────────────────

REPORT_PLANNER_PROMPT = """\
You are an SAP Report Planner. Your job is to analyse a user's visualization request and produce an execution plan.

Given the user query and available SAP tools, output EXACTLY this JSON — nothing else:

{{
  "chart_type": "<pie|bar|heatmap|pivot|table>",
  "title": "<descriptive chart title>",
  "reasoning": "<why this chart type and these tools>",
  "steps": [
    {{"tool": "<tool_name>", "parameters": {{"<param>": "<value>"}}}},
    ...
  ],
  "aggregation": {{
    "group_by": "<field name to group by, e.g. department, vendor_name, status>",
    "metric": "<count|sum|avg|value>",
    "value_field": "<field in the result to use as numeric value, or null>",
    "label_field": "<field to use as the chart label>"
  }}
}}

RULES:
- Choose the minimum set of tools needed to answer the query (max {max_tools})
- For "compare", "breakdown", "distribution" queries → prefer bar or pie
- For "over time", "monthly", "trend" queries → prefer bar (x=month)
- For "matrix", "cross" queries → prefer pivot or heatmap
- For "list", "show all", "table" queries → prefer table
- If a specific entity ID appears (EMP001, V001, etc.) → include it in parameters
- Never call the same tool twice with identical parameters
- Output raw JSON only — no markdown fences, no explanation text

Available tools:
{tools_json}
"""

REPORT_FORMATTER_PROMPT = """\
You are an SAP Report Formatter. You receive raw data collected from SAP tools and must format it into a chart payload.

Original query: "{query}"
Chart type requested: {chart_type}
Aggregation plan: {aggregation}

Raw data collected:
{collected_data}

Output EXACTLY this JSON — nothing else:

For pie/bar/heatmap:
{{
  "title": "<chart title>",
  "chart_type": "<pie|bar|heatmap>",
  "data": [
    {{"label": "<string>", "value": <number>, "pct": <number 0-100>}},
    ...
  ],
  "config": {{"unit": "<unit string>", "value_label": "<label>"}}
}}

For pivot:
{{
  "title": "<chart title>",
  "chart_type": "pivot",
  "rows": ["<row1>", ...],
  "columns": ["<col1>", ...],
  "values": [[<num>, ...], ...],
  "config": {{"row_label": "<>", "col_label": "<>", "value_label": "<>"}}
}}

For table:
{{
  "title": "<chart title>",
  "chart_type": "table",
  "columns": ["<col1>", ...],
  "rows": [["<val>", ...], ...],
  "config": {{}}
}}

RULES:
- pct values in data[] must sum to exactly 100 across all items
- Sort data[] by value descending
- Use real numbers from the collected data — never invent values
- If collected data is empty or all errors, output: {{"error": "no_data"}}
- Output raw JSON only — no markdown fences, no explanation
"""


# ─── Intent detection (unchanged — fast, no LLM needed) ──────────────────────

_CHART_KEYWORDS: dict[str, list[str]] = {
    "pie":     ["pie chart", "pie graph", "donut chart", "donut", "as pie", "breakdown pie",
                "percentage breakdown", "share of", "proportion"],
    "bar":     ["bar chart", "bar graph", "histogram", "column chart", "column graph",
                "as bar", "bar view", "compare", "comparison"],
    "heatmap": ["heat map", "heatmap", "heat-map", "intensity map", "color map",
                "colour map", "heat grid", "as heat"],
    "pivot":   ["pivot table", "pivot", "cross-tab", "crosstab", "matrix view",
                "row column", "by x and y", "cross tab"],
    "table":   ["as a table", "as table", "in a table", "tabular", "show table",
                "list as", "data table", "sortable"],
}

_GENERIC_VIZ = ["chart", "graph", "visuali", "visual report", "report view",
                "dashboard widget", "show as", "display as"]

_DATA_KEYWORDS: dict[str, list[str]] = {
    "fi_co_invoices": ["invoice", "payable", "open invoice", "vendor invoice"],
    "fi_co_budget":   ["budget", "cost center", "utilization", "actual vs budget",
                       "budget utilization", "spending", "gl account"],
    "mm_reorder":     ["reorder", "low stock", "stock alert", "replenish"],
    "mm_pos":         ["purchase order", "open po", "po", "procurement"],
    "mm_materials":   ["material", "stock level", "inventory", "stock status"],
    "sd_orders":      ["sales order", "open order", "customer order", "sales"],
    "hr_headcount":   ["employee", "headcount", "staff", "department", "hr", "workforce"],
    "pp_orders":      ["production order", "manufacturing", "work order"],
    "pp_capacity":    ["capacity", "work center", "utilization", "plant capacity"],
}


def is_report_query(text: str) -> bool:
    """Return True if the message is asking for a visualization / report."""
    t = text.lower()
    for keywords in _CHART_KEYWORDS.values():
        if any(k in t for k in keywords):
            return True
    return any(k in t for k in _GENERIC_VIZ)


def _detect_chart_type(text: str) -> str:
    t = text.lower()
    for chart_type, keywords in _CHART_KEYWORDS.items():
        if any(k in t for k in keywords):
            return chart_type
    return "bar"


def _detect_data_source(text: str) -> str:
    t = text.lower()
    scores: dict[str, int] = {}
    for source, keywords in _DATA_KEYWORDS.items():
        score = sum(1 for k in keywords if k in t)
        if score:
            scores[source] = score
    if not scores:
        return "hr_headcount"
    return max(scores, key=scores.get)


# ─── LLM-Driven Report Agent ─────────────────────────────────────────────────

class LLMReportAgent:
    """
    Two-pass LLM agent for report generation.

    Pass 1 (Planner):  query → tool plan + chart type + aggregation strategy
    Pass 2 (Formatter): raw tool results → final ReportPayload JSON

    Falls back to hardcoded fetchers if LLM is unavailable or JSON is malformed.
    """

    def __init__(self, model: str = "llama3.2", ollama_url: str = None):
        try:
            from core.config_manager import config as _cfg
            self.model      = model or _cfg.default_model
            self.ollama_url = ollama_url or _cfg.ollama_url
        except Exception:
            self.model      = model or "llama3.2"
            self.ollama_url = ollama_url or OLLAMA_BASE_URL

    # ── Public entry point ────────────────────────────────────────────────────

    def generate(self, query: str) -> dict[str, Any] | None:
        """
        Main entry point. Returns a ReportPayload dict or None on failure.
        Always tries LLM path first; falls back to hardcoded path on error.
        """
        try:
            payload = self._llm_generate(query)
            if payload and "error" not in payload:
                return payload
        except Exception:
            _logger.warning("LLM report path failed — using hardcoded fallback", exc_info=True)

        return _hardcoded_generate(query)

    # ── Pass 1: Planner ───────────────────────────────────────────────────────

    def _plan(self, query: str) -> dict | None:
        """Call LLM to produce a tool execution plan for the report."""
        from tools.tool_registry import get_tools_for_prompt
        tools_json = get_tools_for_prompt()

        prompt = REPORT_PLANNER_PROMPT.format(
            tools_json=tools_json,
            max_tools=MAX_TOOL_CALLS,
        )
        response = self._call_llm([
            {"role": "system", "content": prompt},
            {"role": "user",   "content": f"Generate a report for: {query}"},
        ])
        return self._parse_json(response)

    # ── Pass 2: Formatter ─────────────────────────────────────────────────────

    def _format(self, query: str, chart_type: str, aggregation: dict,
                collected_data: dict) -> dict | None:
        """Call LLM to transform raw data into a ReportPayload."""
        prompt = REPORT_FORMATTER_PROMPT.format(
            query=query,
            chart_type=chart_type,
            aggregation=json.dumps(aggregation, indent=2),
            collected_data=json.dumps(collected_data, indent=2, default=str),
        )
        response = self._call_llm([
            {"role": "system", "content": prompt},
            {"role": "user",   "content": "Format the collected data into the chart payload JSON."},
        ])
        return self._parse_json(response)

    # ── Tool executor ─────────────────────────────────────────────────────────

    def _execute_plan(self, steps: list[dict]) -> dict[str, Any]:
        """Execute each planned tool call and collect results."""
        from tools.tool_registry import execute_tool

        collected: dict[str, Any] = {}
        called: set[str] = set()

        for step in steps[:MAX_TOOL_CALLS]:
            tool_name  = step.get("tool", "")
            parameters = step.get("parameters", {})
            call_key   = f"{tool_name}:{json.dumps(parameters, sort_keys=True)}"

            if call_key in called:
                _logger.debug("Skipping duplicate tool call: %s", call_key)
                continue
            called.add(call_key)

            try:
                result = execute_tool(tool_name, parameters)
                collected[call_key] = {
                    "tool":       tool_name,
                    "parameters": parameters,
                    "result":     result,
                }
                _logger.info("Report tool executed: %s → status=%s",
                             tool_name, result.get("status", "OK") if isinstance(result, dict) else "OK")
            except Exception as exc:
                _logger.warning("Tool %s failed: %s", tool_name, exc)
                collected[call_key] = {
                    "tool":       tool_name,
                    "parameters": parameters,
                    "result":     {"status": "ERROR", "message": str(exc)},
                }

        return collected

    # ── Full LLM pipeline ─────────────────────────────────────────────────────

    def _llm_generate(self, query: str) -> dict[str, Any] | None:
        # Step 1: Plan
        plan = self._plan(query)
        if not plan or not plan.get("steps"):
            _logger.warning("Planner returned empty/invalid plan for: %s", query)
            return None

        chart_type  = plan.get("chart_type", "bar")
        aggregation = plan.get("aggregation", {})
        steps       = plan.get("steps", [])
        _logger.info("Report plan: chart=%s, tools=%s, agg=%s",
                     chart_type, [s.get("tool") for s in steps], aggregation)

        # Step 2: Execute tools
        collected = self._execute_plan(steps)
        if not collected:
            _logger.warning("No tool results collected for: %s", query)
            return None

        # Simplify collected for formatter (just results, not metadata)
        results_for_formatter = {
            k: v["result"] for k, v in collected.items()
        }

        # Step 3: Format
        payload = self._format(query, chart_type, aggregation, results_for_formatter)
        if not payload:
            _logger.warning("Formatter returned empty payload for: %s", query)
            return None

        # Validate minimal structure
        if "error" in payload:
            return None
        if "chart_type" not in payload:
            payload["chart_type"] = chart_type

        return payload

    # ── LLM helpers ───────────────────────────────────────────────────────────

    def _call_llm(self, messages: list[dict]) -> str:
        payload = {
            "model":   self.model,
            "messages": messages,
            "stream":  False,
            "options": {"temperature": 0.05, "top_p": 0.9},
        }
        try:
            resp = requests.post(
                f"{self.ollama_url}/api/chat",
                json=payload,
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"]
        except Exception as exc:
            _logger.warning("LLM call failed in report agent: %s", exc)
            return "{}"

    @staticmethod
    def _parse_json(text: str) -> dict | None:
        """Extract and parse the first valid JSON object from LLM output."""
        text = text.strip()
        # Direct parse
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        # Markdown code fence
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        # Bare JSON object anywhere in text
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        return None


# ─── Hardcoded fallback fetchers ──────────────────────────────────────────────
# Used when LLM is unreachable or produces malformed output.
# Also used directly for simple, predictable queries to avoid LLM latency.

def _fetch_fi_co_invoices() -> dict[str, Any]:
    from modules.fi_co import get_open_invoices
    result = get_open_invoices()
    if result.get("status") != "OK":
        return {}
    rows = result.get("open_invoices", [])
    grouped: dict[str, float] = {}
    for r in rows:
        vendor = r.get("vendor_name", "Unknown")
        grouped[vendor] = grouped.get(vendor, 0) + float(r.get("amount", 0))
    total = sum(grouped.values()) or 1
    data = [
        {"label": k, "value": round(v, 2), "pct": round(v / total * 100, 1)}
        for k, v in sorted(grouped.items(), key=lambda x: -x[1])
    ]
    return {
        "title": "Open Invoices by Vendor (Amount)",
        "data":  data,
        "config": {"unit": "INR", "value_label": "Amount"},
    }


def _fetch_fi_co_budget() -> dict[str, Any]:
    from modules.fi_co import list_all_cost_centers
    result = list_all_cost_centers()
    if result.get("status") != "OK":
        return {}
    ccs = result.get("cost_centers", [])
    data = [
        {
            "id":     cc["id"],
            "label":  cc["name"],
            "value":  cc["utilization_pct"],
            "status": ("critical" if cc["utilization_pct"] >= 100
                       else "warning" if cc["utilization_pct"] >= 80
                       else "normal"),
        }
        for cc in ccs
    ]
    return {
        "title": "Budget Utilization by Cost Center",
        "data":  data,
        "config": {
            "unit": "%",
            "thresholds": {"warning": 80, "critical": 100},
            "low_color":  "#16a34a",
            "mid_color":  "#d97706",
            "high_color": "#dc2626",
        },
    }


def _fetch_mm_reorder() -> dict[str, Any]:
    from modules.mm import check_reorder_needed
    result = check_reorder_needed()
    if result.get("status") != "OK":
        return {}
    alerts = result.get("reorder_alerts", [])
    data = [
        {
            "label": f"{a['material_id']} – {a['description']}",
            "value": round(a["available"], 1),
            "pct":   round(a["available"] / max(a["reorder_point"], 1) * 100, 1),
        }
        for a in alerts
    ]
    return {
        "title": "Materials Needing Reorder (Available Stock)",
        "data":  data,
        "config": {"unit": "units", "value_label": "Available"},
    }


def _fetch_mm_pos() -> dict[str, Any]:
    from modules.mm import list_open_purchase_orders
    result = list_open_purchase_orders()
    if result.get("status") != "OK":
        return {}
    rows = result.get("open_pos", [])
    grouped: dict[str, int] = {}
    for r in rows:
        vendor = r.get("vendor", "Unknown")
        grouped[vendor] = grouped.get(vendor, 0) + 1
    total = sum(grouped.values()) or 1
    data = [
        {"label": k, "value": v, "pct": round(v / total * 100, 1)}
        for k, v in sorted(grouped.items(), key=lambda x: -x[1])
    ]
    return {
        "title": "Open Purchase Orders by Vendor",
        "data":  data,
        "config": {"unit": "POs", "value_label": "Count"},
    }


def _fetch_mm_materials() -> dict[str, Any]:
    from modules.mm import check_reorder_needed, list_all_materials
    all_mats = list_all_materials()
    reorder  = check_reorder_needed()
    if all_mats.get("status") != "OK":
        return {}
    reorder_ids = {a["material_id"] for a in reorder.get("reorder_alerts", [])}
    columns = ["Material ID", "Description", "Type", "Price", "Currency", "Status"]
    rows = []
    for m in all_mats.get("materials", []):
        status = "critical" if m["material_id"] in reorder_ids else "ok"
        rows.append([
            m["material_id"], m["description"], m["material_type"],
            str(m["price"]), m["currency"], status,
        ])
    return {
        "title":   "All Materials — Stock Status",
        "columns": columns,
        "rows":    rows,
        "config":  {"status_column": 5, "status_map": {"ok": "normal", "critical": "critical"}},
    }


def _fetch_sd_orders() -> dict[str, Any]:
    from modules.sd import list_open_sales_orders
    result = list_open_sales_orders()
    if result.get("status") != "OK":
        return {}
    rows = result.get("open_orders", [])
    grouped: dict[str, int] = {}
    for r in rows:
        customer = r.get("customer", "Unknown")
        grouped[customer] = grouped.get(customer, 0) + 1
    total = sum(grouped.values()) or 1
    data = [
        {"label": k, "value": v, "pct": round(v / total * 100, 1)}
        for k, v in sorted(grouped.items(), key=lambda x: -x[1])
    ]
    return {
        "title": "Open Sales Orders by Customer",
        "data":  data,
        "config": {"unit": "orders", "value_label": "Count"},
    }


def _fetch_hr_headcount() -> dict[str, Any]:
    from modules.hr import search_employees
    result = search_employees()
    if result.get("status") != "OK":
        return {}
    employees = result.get("employees", [])
    grouped: dict[str, int] = {}
    for e in employees:
        dept = e.get("department", "Unknown")
        grouped[dept] = grouped.get(dept, 0) + 1
    total = sum(grouped.values()) or 1
    data = [
        {"label": k, "value": v, "pct": round(v / total * 100, 1)}
        for k, v in sorted(grouped.items(), key=lambda x: -x[1])
    ]
    return {
        "title": "Active Headcount by Department",
        "data":  data,
        "config": {"unit": "employees", "value_label": "Headcount"},
    }


def _fetch_employee_leave(emp_id: str) -> dict[str, Any]:
    from modules.hr import get_leave_balance
    result = get_leave_balance(emp_id.upper())
    if result.get("status") != "OK":
        return {}
    al = result["annual_leave"]
    sl = result["sick_leave"]
    cl = result["casual_leave"]
    total = (
        al["entitled"] + sl["entitled"] + cl["entitled"]
    ) or 1
    data = [
        {"label": "Annual Used",    "value": al["used"],    "pct": round(al["used"]    / total * 100, 1)},
        {"label": "Annual Balance", "value": al["balance"], "pct": round(al["balance"] / total * 100, 1)},
        {"label": "Sick Used",      "value": sl["used"],    "pct": round(sl["used"]    / total * 100, 1)},
        {"label": "Sick Balance",   "value": sl["balance"], "pct": round(sl["balance"] / total * 100, 1)},
        {"label": "Casual Used",    "value": cl["used"],    "pct": round(cl["used"]    / total * 100, 1)},
        {"label": "Casual Balance", "value": cl["balance"], "pct": round(cl["balance"] / total * 100, 1)},
    ]
    data = [d for d in data if d["value"] > 0]
    return {
        "title": f"Leave Balance — {result['employee_name']} ({emp_id.upper()})",
        "data":  data,
        "config": {"unit": "days", "value_label": "Days"},
    }


def _fetch_employee_salary(emp_id: str) -> dict[str, Any]:
    from modules.hr import get_payslip
    result = get_payslip(emp_id.upper())
    if result.get("status") != "OK":
        return {}
    currency = result.get("currency", "INR")
    total = (
        result["basic_salary"] + result["hra"] +
        result["other_allowances"] + result["total_deductions"]
    ) or 1
    data = [
        {"label": "Basic Salary",     "value": result["basic_salary"],     "pct": round(result["basic_salary"]     / total * 100, 1)},
        {"label": "HRA",              "value": result["hra"],              "pct": round(result["hra"]              / total * 100, 1)},
        {"label": "Other Allowances", "value": result["other_allowances"], "pct": round(result["other_allowances"] / total * 100, 1)},
        {"label": "Deductions",       "value": result["total_deductions"], "pct": round(result["total_deductions"] / total * 100, 1)},
    ]
    data = [d for d in data if d["value"] > 0]
    return {
        "title": f"Salary Breakdown — {result['employee_name']} ({emp_id.upper()}, {result['pay_period']})",
        "data":  data,
        "config": {"unit": currency, "value_label": "Amount"},
    }


def _fetch_pp_orders() -> dict[str, Any]:
    from modules.pp import list_production_orders
    result = list_production_orders()
    if result.get("status") != "OK":
        return {}
    orders = result.get("orders", [])
    statuses = sorted({o.get("status", "UNKNOWN") for o in orders})
    wcs      = sorted({o.get("work_center") or "Unassigned" for o in orders})
    matrix   = {s: {w: 0 for w in wcs} for s in statuses}
    for o in orders:
        s = o.get("status", "UNKNOWN")
        w = o.get("work_center") or "Unassigned"
        matrix[s][w] += 1
    values = [[matrix[s][w] for w in wcs] for s in statuses]
    return {
        "title":   "Production Orders by Status × Work Center",
        "rows":    statuses,
        "columns": wcs,
        "values":  values,
        "config":  {"value_label": "Orders", "row_label": "Status", "col_label": "Work Center"},
    }


def _fetch_pp_capacity() -> dict[str, Any]:
    from modules.pp import get_capacity_utilization
    result = get_capacity_utilization()
    if result.get("status") != "OK":
        return {}
    wcs = result.get("work_centers", [])
    data = [
        {
            "id":     w["wc_id"],
            "label":  w["name"],
            "value":  int(w.get("active_production_orders", 0)),
            "status": ("critical" if int(w.get("active_production_orders", 0)) >= 4
                       else "warning" if int(w.get("active_production_orders", 0)) >= 2
                       else "normal"),
        }
        for w in wcs
    ]
    return {
        "title": "Work Center Capacity Load",
        "data":  data,
        "config": {
            "unit": "active orders",
            "thresholds": {"warning": 2, "critical": 4},
            "low_color":  "#16a34a",
            "mid_color":  "#d97706",
            "high_color": "#dc2626",
        },
    }


_HARDCODED_FETCHERS = {
    "fi_co_invoices": _fetch_fi_co_invoices,
    "fi_co_budget":   _fetch_fi_co_budget,
    "mm_reorder":     _fetch_mm_reorder,
    "mm_pos":         _fetch_mm_pos,
    "mm_materials":   _fetch_mm_materials,
    "sd_orders":      _fetch_sd_orders,
    "hr_headcount":   _fetch_hr_headcount,
    "pp_orders":      _fetch_pp_orders,
    "pp_capacity":    _fetch_pp_capacity,
}


# ─── Payload builder ──────────────────────────────────────────────────────────

def _coerce_chart_type(chart_type: str, raw: dict) -> str:
    if "rows" in raw and "columns" in raw and "values" in raw:
        return "pivot"
    if "columns" in raw and "rows" in raw and "data" not in raw:
        return "table"
    return chart_type


def build_payload(chart_type: str, raw: dict) -> dict[str, Any]:
    """Merge raw aggregated data into a ReportPayload the frontend understands."""
    chart_type = _coerce_chart_type(chart_type, raw)
    payload: dict[str, Any] = {
        "chart_type": chart_type,
        "title":      raw.get("title", "SAP Report"),
        "config":     raw.get("config", {}),
    }
    if chart_type in ("pie", "bar", "heatmap"):
        payload["data"] = raw.get("data", [])
    elif chart_type == "pivot":
        payload["rows"]    = raw.get("rows", [])
        payload["columns"] = raw.get("columns", [])
        payload["values"]  = raw.get("values", [])
    elif chart_type == "table":
        payload["columns"] = raw.get("columns", [])
        payload["rows"]    = raw.get("rows", [])
    return payload


# ─── Hardcoded fallback path ──────────────────────────────────────────────────

def _hardcoded_generate(query: str) -> dict[str, Any] | None:
    """Original keyword-driven path. Used as fallback when LLM is unavailable."""
    chart_type  = _detect_chart_type(query)
    data_source = _detect_data_source(query)

    # Specific employee ID → individual data chart
    emp_match = _EMP_ID_RE.search(query)
    if emp_match and data_source == "hr_headcount":
        emp_id = emp_match.group(0).upper()
        t = query.lower()
        if any(k in t for k in ("salary", "pay", "payslip", "compensation", "ctc")):
            try:
                raw = _fetch_employee_salary(emp_id)
            except Exception:
                raw = {}
        else:
            try:
                raw = _fetch_employee_leave(emp_id)
            except Exception:
                raw = {}
        if not raw:
            return None
        return build_payload(chart_type, raw)

    fetcher = _HARDCODED_FETCHERS.get(data_source)
    if fetcher is None:
        return None
    try:
        raw = fetcher()
    except Exception:
        return None
    if not raw:
        return None
    return build_payload(chart_type, raw)


# ─── Module-level singleton ───────────────────────────────────────────────────
# api/server.py calls generate() and reply_text() at module level.
# The singleton is created lazily so import never fails even without Ollama.

_agent: LLMReportAgent | None = None


def _get_agent() -> LLMReportAgent:
    global _agent
    if _agent is None:
        _agent = LLMReportAgent()
    return _agent


# ─── Public API (unchanged surface for api/server.py) ────────────────────────

def generate(query: str) -> dict[str, Any] | None:
    """
    Main entry point called by api/server.py.
    Tries LLM-driven generation first; falls back to hardcoded path.
    Returns a ReportPayload dict or None on complete failure.
    """
    return _get_agent().generate(query)


def reply_text(query: str, payload: dict[str, Any]) -> str:
    """Generate a short conversational reply to accompany the widget."""
    chart_type = payload.get("chart_type", "chart")
    title      = payload.get("title", "SAP data")
    type_label = {
        "pie":     "pie chart",
        "bar":     "bar chart",
        "heatmap": "heat map",
        "pivot":   "pivot table",
        "table":   "data table",
    }.get(chart_type, "chart")
    return f"Here is the **{title}** as a {type_label}:"
