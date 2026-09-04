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
from decimal import Decimal
import logging
import re
import requests
from typing import Any

_logger = logging.getLogger("report_agent")

MAX_TOOL_CALLS  = 5          # planner may request up to this many tool calls

# Tools a report can aggregate over. The planner used to receive the entire
# 46-tool registry — ~7.7k tokens, which overflowed the model's context and
# produced garbage plans — and it named tools the caller was not allowed to
# run, so the plan was denied at execution time anyway. Scoping to the read
# tools that return chartable collections cuts the prompt to ~1.4k tokens.
_REPORT_TOOLS: frozenset[str] = frozenset({
    # FI/CO
    "get_open_invoices", "get_cost_center_budget", "list_all_cost_centers",
    # MM
    "check_reorder_needed", "list_open_purchase_orders", "get_stock_level",
    # SD
    "list_open_sales_orders", "get_customer_info", "get_customer_orders",
    # HR
    "search_employees", "get_leave_balance", "get_payslip",
    # PP
    "list_production_orders", "get_capacity_utilization",
})
_EMP_ID_RE      = re.compile(r'\bEMP\d+\b', re.IGNORECASE)
# Customer master IDs look like C001. The leading \b keeps this from matching
# the tail of an unrelated ID such as WC001 (work centre) or ALEC001 (RE customer).
_CUST_ID_RE     = re.compile(r'\bC\d{3,}\b', re.IGNORECASE)
# Any SAP-style entity id (EMP001, C001, V001, MAT011, SO5001, CC1000).
_ENTITY_ID_RE   = re.compile(r'\b[A-Z]{1,4}\d{2,}\b', re.IGNORECASE)

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
- Choose the minimum set of tools needed to answer the query (max {max_tools}).
  ONE tool is usually enough. Never add a tool from an unrelated SAP module:
  a customer question must not pull cost centres, a headcount question must
  not pull invoices. Extra tools produce a chart that mixes unrelated numbers
  and is worse than no chart at all.
- Every tool you list must be needed to draw THIS chart. If you cannot justify
  a tool in one short clause, leave it out.
- A chart needs SEVERAL COMPARABLE NUMBERS. Prefer a tool that returns a
  collection (orders, employees, invoices, materials) over one that returns a
  single master-data record. get_customer_info returns one customer's details
  and cannot be charted — for "customer C001 as a chart" use get_customer_orders.
- For "compare", "breakdown", "distribution" queries → prefer bar or pie
- For "over time", "monthly", "trend" queries → prefer bar (x=month)
- For "matrix", "cross" queries → prefer pivot or heatmap
- For "list", "show all", "table" queries → prefer table
- If a specific entity ID appears (EMP001, C001, V001, MAT001) → put it in the
  tool parameters and name that entity in the title
- If the user named NO specific entity, call the collection tool with EMPTY
  parameters {{}}. Filtering to one vendor/customer when none was asked for
  returns a single row, which cannot be charted.
- Always set "metric" and "value_field" when the rows carry an amount,
  quantity or budget — use metric "sum" for money, "count" only for headcounts
- Never call the same tool twice with identical parameters
- aggregation fields must be JSON null when not applicable — never the string "None"
- The title must name the actual subject and measure, e.g.
  "Sales Orders by Value — C001", not "Customer Info"
- Output raw JSON only — no markdown fences, no explanation text

EXAMPLES

Query: "Get customer info for C001 and show me in bar chart"
{{"chart_type": "bar",
  "title": "Sales Orders by Value \u2014 C001",
  "reasoning": "One customer named, so chart that customer's own orders by value.",
  "steps": [{{"tool": "get_customer_orders", "parameters": {{"customer_id": "C001"}}}}],
  "aggregation": {{"group_by": null, "metric": "sum", "value_field": "value", "label_field": "order_id"}}}}

Query: "headcount by department as a pie chart"
{{"chart_type": "pie",
  "title": "Active Headcount by Department",
  "reasoning": "Counting employees grouped by department is a share-of-total view.",
  "steps": [{{"tool": "search_employees", "parameters": {{}}}}],
  "aggregation": {{"group_by": "department", "metric": "count", "value_field": null, "label_field": "department"}}}}

Query: "leave balance for EMP001"
{{"chart_type": "bar",
  "title": "Leave Balance \u2014 EMP001",
  "reasoning": "One employee named, so chart that employee's leave buckets.",
  "steps": [{{"tool": "get_leave_balance", "parameters": {{"employee_id": "EMP001"}}}}],
  "aggregation": {{"group_by": null, "metric": "value", "value_field": "balance", "label_field": "leave_type"}}}}

Available tools:
{tools_json}
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
    "sd_customer":    ["customer info", "customer detail", "customer master",
                       "customer data", "customer profile", "credit limit",
                       "customer"],
    "hr_headcount":   ["employee", "headcount", "staff", "department", "hr", "workforce",
                       "leave balance", "leave", "payslip", "salary", "payroll"],
    "pp_orders":      ["production order", "manufacturing", "work order"],
    "pp_capacity":    ["capacity", "work center", "utilization", "plant capacity"],
}


# Words that mean "draw me a picture of this" and nothing else. _CHART_KEYWORDS
# deliberately also matches loose words like "compare" and "share of" so that
# ordinary questions still reach the report path — but those are normal
# conversation, and treating them as chart requests would answer "compare V001
# and V002" with a "which chart?" prompt. The fallthrough guard uses this
# narrower set. \b keeps "graph" from matching inside "paragraph".
_EXPLICIT_CHART_RE = re.compile(
    r'\b(charts?|graphs?|plots?|plotted|histograms?|'
    r'heat[\s-]?maps?|pivot\s+tables?|donut|'
    r'visuali[sz](?:e|ed|ation|sation))\b',
    re.IGNORECASE,
)

# Human labels for the data a chart can actually be built from, used when we
# have to ask the user what to chart.
_DATA_SOURCE_LABELS: dict[str, str] = {
    "fi_co_invoices": "open vendor invoices",
    "fi_co_budget":   "cost-centre budget vs actual",
    "mm_reorder":     "materials below reorder level",
    "mm_pos":         "open purchase orders",
    "mm_materials":   "material stock levels",
    "sd_orders":      "open sales orders",
    "sd_customer":    "a customer's orders or credit profile",
    "hr_headcount":   "headcount by department",
    "pp_orders":      "production orders",
    "pp_capacity":    "work-centre capacity utilisation",
}


def is_report_query(text: str) -> bool:
    """Return True if the message is asking for a visualization / report."""
    t = text.lower()
    for keywords in _CHART_KEYWORDS.values():
        if any(k in t for k in keywords):
            return True
    return any(k in t for k in _GENERIC_VIZ)


def is_explicit_chart_request(text: str) -> bool:
    """True only when the user unambiguously asked to be shown a chart.

    Narrower than is_report_query() on purpose. This is the test the caller
    uses to decide whether declining to build a report may fall through to
    freeform chat: for an explicit chart request it may not, because the chat
    model answers "give me a bar chart" by writing matplotlib code, which this
    product cannot run and the user did not ask for.
    """
    return bool(_EXPLICIT_CHART_RE.search(text))


def clarify_text(query: str) -> str:
    """Ask which SAP data to chart, instead of falling through to chat.

    Reached when the user clearly wants a chart but named no subject and the
    conversation supplies none. Naming the chartable datasets turns a dead end
    into one round-trip.
    """
    type_label = {
        "pie":     "pie chart",
        "bar":     "bar chart",
        "heatmap": "heat map",
        "pivot":   "pivot table",
        "table":   "data table",
    }.get(_detect_chart_type(query), "chart")
    options = "\n".join(f"• {label}" for label in _DATA_SOURCE_LABELS.values())
    return (
        f"I can draw that as a {type_label}, but I need to know which SAP data "
        f"to chart — your message does not name one.\n\n"
        f"I can chart any of these directly from SAP:\n{options}\n\n"
        f"Tell me which (or name a customer, employee or cost centre) and I "
        f"will render it."
    )


def _detect_chart_type(text: str) -> str:
    t = text.lower()
    for chart_type, keywords in _CHART_KEYWORDS.items():
        if any(k in t for k in keywords):
            return chart_type
    return "bar"


# How far back an anaphoric follow-up may reach for its subject. Two exchanges:
# far enough to cover "show me X" / "now chart it", short enough that a subject
# from six turns ago cannot hijack an unrelated request.
_CONTEXT_WINDOW = 4


def _recent_text(context: list[dict] | None) -> str:
    """Flatten the last few conversation turns into one searchable string."""
    if not context:
        return ""
    return " ".join(
        str(msg.get("content", ""))
        for msg in context[-_CONTEXT_WINDOW:]
        if isinstance(msg, dict)
    )


def _score_data_sources(text: str) -> dict[str, int]:
    t = text.lower()
    scores: dict[str, int] = {}
    for source, keywords in _DATA_KEYWORDS.items():
        score = sum(1 for k in keywords if k in t)
        if score:
            scores[source] = score
    return scores


def _detect_data_source(text: str,
                        context: list[dict] | None = None) -> str | None:
    """Best-matching data source for `text`, or None if no subject is found.

    Returns None rather than defaulting to a data source: a bare "show me in a
    bar chart" carries no subject, and answering it with whichever report
    happened to be the default produced a confidently wrong chart (HR headcount
    for a customer question). None lets the caller decline and fall through to
    the main agent, which can at least answer honestly.

    `context` is the recent conversation, most recent last. A follow-up like
    "i need this bar chart" is anaphoric — its subject lives in the previous
    turn, not in the sentence — so when the message itself names nothing we
    look there. This widens resolution using text the user actually wrote or
    was actually shown; it does not reinstate the guessed default above. If the
    recent turns name no data either, the answer is still None.
    """
    scores = _score_data_sources(text)
    if not scores and context:
        scores = _score_data_sources(_recent_text(context))
        if scores:
            _logger.info("Chart subject resolved from conversation context: %s",
                         max(scores, key=scores.get))
    if not scores:
        return None
    # max() keeps the first of equal scores, so ties fall to _DATA_KEYWORDS
    # declaration order. sd_customer is declared after sd_orders so a query
    # mentioning "customer order" still resolves to the order report.
    return max(scores, key=scores.get)


# ─── LLM-Driven Report Agent ─────────────────────────────────────────────────

def _sanitize_title(title: str, query: str) -> str:
    """Remove entity ids from a planned title that the user never mentioned.

    The planner puts its invented filter in the title as well as the
    parameters. Once the filter is dropped the chart covers everything, so a
    title reading "Outstanding Vendors by Value - V001" describes data that is
    not on screen. Ids the user did ask for are left alone, and a title that is
    nothing but an id is kept rather than blanked.
    """
    haystack = query.lower()
    invented = [m for m in _ENTITY_ID_RE.findall(title) if m.lower() not in haystack]
    if not invented:
        return title.strip()

    cleaned = title
    for token in invented:
        cleaned = re.sub(rf'\s*[(\[]?\b{re.escape(token)}\b[)\]]?', '', cleaned,
                         flags=re.IGNORECASE)
    # Drop the separator the id hung off, plus any doubled spaces it left.
    cleaned = re.sub(r'[\s\u2013\u2014:,\-]+$', '', cleaned)
    cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
    return cleaned or title.strip()


def _sanitize_parameters(tool_name: str,
                         parameters: Any,
                         query: str) -> dict[str, Any]:
    """Drop planner arguments the user never asked for.

    The planner narrows collection tools on its own initiative: asked to chart
    vendors by outstanding it called get_open_invoices(vendor_id="V001"), which
    returns a single invoice and cannot be charted, so the request produced no
    chart at all. A parameter value appearing nowhere in the user's query is
    the model's invention. Required arguments are kept regardless — dropping
    one only breaks the call — and a tool absent from the registry is left
    untouched rather than silently stripped.
    """
    if not isinstance(parameters, dict) or not parameters:
        return {}

    from tools.tool_registry import TOOLS
    spec = next((t for t in TOOLS if t.get("name") == tool_name), None)
    if spec is None:
        return dict(parameters)

    required = set(spec.get("parameters", {}).get("required", []))
    haystack = query.lower()
    clean: dict[str, Any] = {}
    for key, value in parameters.items():
        if key in required:
            clean[key] = value
            continue
        text = str(value).strip()
        if not text or text.lower() in ("null", "none", "n/a"):
            continue
        if text.lower() in haystack:
            clean[key] = value
        else:
            _logger.info("Dropping invented %s parameter %s=%r (absent from query)",
                         tool_name, key, value)
    return clean


class LLMReportAgent:
    """
    Two-pass LLM agent for report generation.

    Pass 1 (Planner):  query → tool plan + chart type + aggregation strategy
    Pass 2 (Formatter): raw tool results → final ReportPayload JSON

    Falls back to hardcoded fetchers if LLM is unavailable or JSON is malformed.
    """

    def __init__(self, manager=None, tenant_id: str = "default", user_id: str | None = None):
        from ai.manager import get_manager
        self.manager = manager or get_manager()
        self.tenant_id = tenant_id
        self.user_id = user_id

    # ── Public entry point ────────────────────────────────────────────────────

    def generate(self, query: str,
                 allowed_tools: set[str] | None = None,
                 context: list[dict] | None = None) -> dict[str, Any] | None:
        """
        Main entry point. Returns a ReportPayload dict or None on failure.

        The deterministic keyword path runs FIRST and the LLM only handles
        queries it cannot serve. That ordering is deliberate: the LLM formatter
        writes the chart numbers itself, and a small local model demonstrably
        invents them — asked for EMP001's leave it produced 50/20/10 days and a
        "Maternity Leave" category that does not exist, where the real balances
        are 15/12/7. A chart of fabricated SAP figures is worse than no chart,
        so anything the deterministic fetchers can answer is answered by them,
        from real rows. The LLM still covers queries outside their vocabulary,
        where an imperfect chart beats none, and _validated_payload screens it.

        `allowed_tools` is the caller's RBAC allow-list; both paths honour it.
        Pass None only when authentication is disabled.

        `context` is the recent conversation, used to resolve a follow-up whose
        subject is only in the previous turn ("i need this bar chart").
        """
        payload = _hardcoded_generate(query, allowed_tools, context)
        if payload is not None:
            # Includes ACCESS_DENIED, which must not be retried via the LLM.
            return payload

        try:
            payload = self._llm_generate(query, allowed_tools, context)
            if payload and "error" not in payload:
                return payload
        except Exception:
            _logger.warning("LLM report path failed", exc_info=True)

        return None

    # ── Pass 1: Planner ───────────────────────────────────────────────────────

    def _plan(self, query: str,
              allowed_tools: set[str] | None = None) -> dict | None:
        """Call LLM to produce a tool execution plan for the report.

        The planner only ever sees report-capable tools the caller may run, so
        it cannot plan a step that execution would reject.
        """
        from tools.tool_registry import get_tools_for_prompt
        scope = set(_REPORT_TOOLS)
        if allowed_tools is not None:
            scope &= set(allowed_tools)
            if not scope:
                _logger.info("No report tools permitted for caller — skipping plan")
                return None
        tools_json = get_tools_for_prompt(scope)

        prompt = REPORT_PLANNER_PROMPT.format(
            tools_json=tools_json,
            max_tools=MAX_TOOL_CALLS,
        )
        # The planner prompt carries the tool registry and the user's query —
        # no SAP tool result has been fetched yet at this point in the
        # pipeline, so there is nothing here for redaction to protect.
        # Defaulting to carries_sap_data=True would trip the manager's
        # redaction-fail-closed WARNING on every single report generated
        # against an external provider, diluting the exact signal that should
        # be reserved for a genuine leak. Since aggregation became
        # deterministic this is the only LLM call the report path makes, so no
        # SAP row ever leaves the process on behalf of a chart.
        response = self._call_llm([
            {"role": "system", "content": prompt},
            {"role": "user",   "content": f"Generate a report for: {query}"},
        ], carries_sap_data=False)
        return self._parse_json(response)

    # ── Tool executor ─────────────────────────────────────────────────────────

    def _execute_plan(self, steps: list[dict], query: str,
                      allowed_tools: set[str] | None = None) -> dict[str, Any]:
        """Execute each planned tool call and collect results.

        Tools outside the caller's allow-list are never executed: the planner is
        LLM-driven, so it must not be able to widen the caller's permissions.
        """
        from tools.tool_registry import execute_tool

        collected: dict[str, Any] = {}
        called: set[str] = set()

        for step in steps[:MAX_TOOL_CALLS]:
            tool_name  = step.get("tool", "")
            parameters = _sanitize_parameters(tool_name, step.get("parameters"), query)
            call_key   = f"{tool_name}:{json.dumps(parameters, sort_keys=True)}"

            if call_key in called:
                _logger.debug("Skipping duplicate tool call: %s", call_key)
                continue
            called.add(call_key)

            if allowed_tools is not None and tool_name not in allowed_tools:
                _logger.info("Report tool denied by RBAC: %s", tool_name)
                collected[call_key] = {
                    "tool":       tool_name,
                    "parameters": parameters,
                    "result":     {"status": "ERROR",
                                   "message": f"Access denied: tool '{tool_name}' "
                                              f"not permitted for your role"},
                }
                continue

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

    def _llm_generate(self, query: str,
                      allowed_tools: set[str] | None = None,
                      context: list[dict] | None = None) -> dict[str, Any] | None:
        # A follow-up's subject lives in the previous turn, so the planner needs
        # it too. Folding the recent turns into the query also widens the
        # haystack _sanitize_parameters checks against, which is the behaviour
        # we want: an id the user gave two turns ago is not the model's
        # invention, and stripping it would narrow the chart to nothing.
        recent = _recent_text(context)
        query  = f"{query}\n\n(Recent conversation: {recent})" if recent else query

        # Step 1: Plan
        plan = self._plan(query, allowed_tools)
        if not plan or not plan.get("steps"):
            _logger.warning("Planner returned empty/invalid plan for: %s", query)
            return None

        chart_type  = plan.get("chart_type", "bar")
        aggregation = plan.get("aggregation", {})
        steps       = plan.get("steps", [])
        _logger.info("Report plan: chart=%s, tools=%s, agg=%s",
                     chart_type, [s.get("tool") for s in steps], aggregation)

        # Step 2: Execute tools
        collected = self._execute_plan(steps, query, allowed_tools)
        if not collected:
            _logger.warning("No tool results collected for: %s", query)
            return None

        results = {k: v["result"] for k, v in collected.items()}

        # Step 3: Aggregate in Python, from the rows SAP returned.
        #
        # This used to be a second LLM pass that wrote the chart numbers itself,
        # and a small local model fabricated them — see _aggregate's note. The
        # plan (tool, chart type, fields) is the model's contribution; every
        # value below is computed from real rows.
        title   = _sanitize_title(str(plan.get("title") or query).strip() or query,
                                  query)
        payload = _aggregate(results, aggregation, chart_type, title)
        if not payload:
            _logger.info("Aggregation produced no chart for: %s", query)
            return None

        return _validated_payload(payload)

    # ── LLM helpers ───────────────────────────────────────────────────────────

    def _call_llm(self, messages: list[dict], *, carries_sap_data: bool = True) -> str:
        from ai.types import Capability, Purpose
        try:
            response = self.manager.chat(
                tenant_id=self.tenant_id, user_id=self.user_id,
                purpose=Purpose.SUMMARIZATION, intent="report_generation",
                messages=messages, carries_sap_data=carries_sap_data,
                required=frozenset({Capability.CHAT}),
            )
            return response.content
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


def _fetch_customer_orders(cust_id: str) -> dict[str, Any]:
    """Bar chart of one customer's sales orders by value."""
    from modules.sd import get_customer_orders
    result = get_customer_orders(cust_id.upper())
    if result.get("status") != "OK":
        return {}
    orders = result.get("orders", [])
    if not orders:
        return {}
    total = sum(float(o.get("value", 0)) for o in orders) or 1
    data = [
        {
            "label": f"{o['order_id']} – {o.get('material', '')}".strip(" –"),
            "value": round(float(o.get("value", 0)), 2),
            "pct":   round(float(o.get("value", 0)) / total * 100, 1),
        }
        for o in sorted(orders, key=lambda o: -float(o.get("value", 0)))
    ]
    return {
        "title": f"Sales Orders by Value — {result['customer_name']} ({cust_id.upper()})",
        "data":  data,
        "config": {"unit": result.get("currency", "INR"), "value_label": "Order Value"},
    }


def _fetch_customer_credit(cust_id: str) -> dict[str, Any]:
    """Credit picture for one customer — used when the customer has no orders."""
    from modules.sd import get_customer_info, get_customer_orders
    info = get_customer_info(cust_id.upper())
    if info.get("status") != "OK":
        return {}
    credit_limit = float(info.get("credit_limit") or 0)
    try:
        orders = get_customer_orders(cust_id.upper())
        open_value = float(orders.get("total_value") or 0) if orders.get("status") == "OK" else 0.0
    except Exception:
        open_value = 0.0
    available = max(credit_limit - open_value, 0.0)
    total = (credit_limit + open_value + available) or 1
    data = [
        {"label": "Credit Limit",     "value": round(credit_limit, 2), "pct": round(credit_limit / total * 100, 1)},
        {"label": "Open Order Value", "value": round(open_value, 2),   "pct": round(open_value   / total * 100, 1)},
        {"label": "Available Credit", "value": round(available, 2),    "pct": round(available    / total * 100, 1)},
    ]
    data = [d for d in data if d["value"] > 0]
    if not data:
        return {}
    return {
        "title": f"Credit Profile — {info.get('name', cust_id.upper())} ({cust_id.upper()})",
        "data":  data,
        "config": {"unit": info.get("currency", "INR"), "value_label": "Amount"},
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


# Sentinel returned when the caller's role does not permit the requested data.
ACCESS_DENIED: dict[str, Any] = {"error": "access_denied"}

# ─── RBAC: which SAP module each report data source reads from ───────────────
# The report agent reaches SAP data directly, so it must apply the same module
# allow-list the chat tool path applies. Without this an unprivileged user can
# retrieve any module's data simply by asking for a "chart" (finding F-12).
_DATA_SOURCE_MODULE: dict[str, str] = {
    "fi_co_invoices": "fi_co",
    "fi_co_budget":   "fi_co",
    "mm_reorder":     "mm",
    "mm_pos":         "mm",
    "mm_materials":   "mm",
    "sd_orders":      "sd",
    "sd_customer":    "sd",
    "hr_headcount":   "hr",
    "pp_orders":      "pp",
    "pp_capacity":    "pp",
}


def _module_allowed(module: str, allowed_tools: set[str] | None) -> bool:
    """True if the caller's tool allow-list grants any tool in `module`.

    allowed_tools is None only when authentication is disabled (dev mode),
    matching the convention used by SAPAgent.auto_research().
    """
    if allowed_tools is None:
        return True
    from auth.rbac import MODULE_TOOLS
    return bool(set(MODULE_TOOLS.get(module, ())) & set(allowed_tools))


_HARDCODED_FETCHERS = {
    "fi_co_invoices": _fetch_fi_co_invoices,
    "fi_co_budget":   _fetch_fi_co_budget,
    "mm_reorder":     _fetch_mm_reorder,
    "mm_pos":         _fetch_mm_pos,
    "mm_materials":   _fetch_mm_materials,
    "sd_orders":      _fetch_sd_orders,
    # A customer query with no ID in it ("customer breakdown as a chart") has no
    # single customer to profile, so it aggregates across customers instead.
    "sd_customer":    _fetch_sd_orders,
    "hr_headcount":   _fetch_hr_headcount,
    "pp_orders":      _fetch_pp_orders,
    "pp_capacity":    _fetch_pp_capacity,
}


# ─── Deterministic aggregation ────────────────────────────────────────────────
# The LLM plans (which tool, which chart, which fields); Python computes every
# number from the rows SAP actually returned. The model is never asked to write
# a value, because it invents them: asked for EMP001's leave it produced
# 50/20/10 days and a "Maternity Leave" category against real balances of
# 15/12/7. Planning is a judgement call and the model is good at it; arithmetic
# over SAP rows is not a judgement call.

_METRICS = ("count", "sum", "avg", "value")


def _extract_rows(collected: dict[str, Any]) -> list[dict[str, Any]]:
    """The richest list-of-records among the tool results.

    Tool envelopes name their collection differently (orders, employees,
    open_pos, reorder_alerts…), so the shape is what identifies it. The longest
    list wins: when a plan calls several tools, the collection with the most
    records is the one worth charting.
    """
    best: list[dict[str, Any]] = []
    for result in collected.values():
        if not isinstance(result, dict) or result.get("status") == "ERROR":
            continue
        for value in result.values():
            if (isinstance(value, list) and value
                    and all(isinstance(r, dict) for r in value)
                    and len(value) > len(best)):
                best = value
    return best


def _pick_label_field(rows: list[dict[str, Any]], preferred: str | None) -> str | None:
    """The planned label field, or the first string-ish column that identifies a row."""
    if preferred and any(preferred in r for r in rows):
        return preferred
    for candidate in ("name", "label", "description", "department", "customer",
                      "vendor", "status", "id"):
        if any(candidate in r for r in rows):
            return candidate
    for key, value in rows[0].items():
        if isinstance(value, str):
            return key
    return None


def _pick_value_field(rows: list[dict[str, Any]], label_field: str | None) -> str | None:
    """The most chart-worthy numeric column in the rows, or None.

    Prefers a measure name over an incidental number so a budget chart does not
    end up plotting a row's id or year.
    """
    numeric = [
        k for k in rows[0]
        if k != label_field and any(_numeric(r.get(k)) is not None for r in rows)
    ]
    if not numeric:
        return None
    for hint in ("amount", "value", "total", "balance", "budget", "actual",
                 "spend", "cost", "price", "qty", "quantity", "count"):
        for key in numeric:
            if hint in key.lower():
                return key
    return numeric[0]


def _aggregate(collected: dict[str, Any],
               aggregation: dict[str, Any],
               chart_type: str,
               title: str) -> dict[str, Any] | None:
    """Compute a ReportPayload from real tool rows using the planned spec.

    Returns None when the spec cannot be honoured against the rows — a missing
    value field, no collection in the results, every tool errored. Declining is
    correct: the caller shows no chart rather than a plausible wrong one.
    """
    rows = _extract_rows(collected)
    if not rows:
        _logger.info("Aggregation declined: no row collection in tool results")
        return None

    spec = aggregation if isinstance(aggregation, dict) else {}

    def field(name: str) -> str | None:
        """A planned field name, or None. Models write the *string* "null"."""
        raw = spec.get(name)
        if raw is None:
            return None
        text = str(raw).strip()
        return None if text.lower() in ("", "null", "none", "n/a") else text

    metric      = (field("metric") or "").lower()
    value_field = field("value_field")
    group_by    = field("group_by")
    label_field = _pick_label_field(rows, field("label_field") or group_by)

    if value_field and not any(_numeric(r.get(value_field)) is not None for r in rows):
        value_field = None          # planned a column the rows do not carry

    # A plan that names no measure would otherwise fall to "count", which on
    # rows with one entry per label draws identical bars. If the rows carry a
    # numeric column, chart that instead — still read straight from SAP.
    if not value_field and metric in ("", "count", "value", "sum", "avg"):
        inferred = _pick_value_field(rows, label_field)
        if inferred and metric in ("", "value", "sum", "avg"):
            value_field = inferred
        elif inferred and metric == "count" and not group_by:
            value_field, metric = inferred, "value"

    if not metric:
        metric = "sum" if (value_field and group_by) else "value" if value_field else "count"
    if metric not in _METRICS:
        metric = "count"

    if label_field is None:
        _logger.info("Aggregation declined: no usable label field")
        return None

    if metric in ("sum", "avg", "value"):
        if not value_field or not any(_numeric(r.get(value_field)) is not None for r in rows):
            _logger.info("Aggregation declined: value_field %r absent from rows", value_field)
            return None

    if metric == "value":
        pairs = [
            (str(r.get(label_field, "")), _numeric(r.get(value_field)))
            for r in rows
        ]
        totals = {lbl: val for lbl, val in pairs if lbl and val is not None}
    else:
        key_field = group_by if any(group_by in r for r in rows) else label_field
        buckets: dict[str, list[float]] = {}
        for r in rows:
            key = str(r.get(key_field, "Unknown") or "Unknown")
            if metric == "count":
                buckets.setdefault(key, []).append(1.0)
            else:
                val = _numeric(r.get(value_field))
                if val is not None:
                    buckets.setdefault(key, []).append(val)
        if metric == "avg":
            totals = {k: sum(v) / len(v) for k, v in buckets.items() if v}
        else:
            totals = {k: sum(v) for k, v in buckets.items() if v}

    if not totals:
        _logger.info("Aggregation declined: metric %r produced no values", metric)
        return None

    if metric == "count" and len(totals) > 2 and len(set(totals.values())) == 1:
        # One row per label — "count" was the wrong metric and the chart would
        # be a row of identical bars. Better no chart than a meaningless one.
        _logger.info("Aggregation declined: counting %d unique labels is uniform",
                     len(totals))
        return None

    ordered = sorted(totals.items(), key=lambda kv: -kv[1])
    grand   = sum(v for _, v in ordered) or 1
    data = [
        {"label": k, "value": round(v, 2), "pct": round(v / grand * 100, 1)}
        for k, v in ordered
    ]
    return {
        "chart_type": chart_type,
        "title":      title,
        "data":       data,
        "config":     {"value_label": (value_field or metric).replace("_", " ").title()},
    }


# ─── LLM output validation ────────────────────────────────────────────────────

def _numeric(value: Any) -> float | None:
    """Coerce a chart value to a number, or None if it is not one.

    Decimal matters as much as int/float here: every money and quantity column
    in this schema is DECIMAL, so psycopg hands back decimal.Decimal. Treating
    those as non-numeric silently emptied every currency chart.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            return float(value)
        except (ValueError, ArithmeticError):      # Decimal('NaN'), Decimal('Infinity')
            return None
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "").replace("%", "")
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _validated_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Reject LLM chart payloads that would render as nonsense.

    A small local model happily returns a customer master record as 13 "data
    points" whose values are strings like "Mumbai". Rendering that produces a
    bar chart of text. Anything that fails here returns None so the caller
    falls back to the deterministic keyword path, which is always chartable.
    """
    chart_type = payload.get("chart_type")

    if chart_type in ("pie", "bar", "heatmap"):
        clean = []
        for item in payload.get("data") or []:
            if not isinstance(item, dict):
                continue
            value = _numeric(item.get("value"))
            label = item.get("label")
            if value is None or label in (None, ""):
                continue
            clean.append({**item, "label": str(label), "value": value})
        if len(clean) < 2:
            _logger.info("Discarding LLM chart: %d chartable points of %d",
                         len(clean), len(payload.get("data") or []))
            return None
        payload["data"] = clean
        return payload

    if chart_type == "pivot":
        values = payload.get("values") or []
        if not values or not payload.get("rows") or not payload.get("columns"):
            return None
        return payload

    if chart_type == "table":
        if not payload.get("columns") or not payload.get("rows"):
            return None
        return payload

    _logger.info("Discarding LLM chart with unknown chart_type: %r", chart_type)
    return None


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

def _hardcoded_generate(query: str,
                        allowed_tools: set[str] | None = None,
                        context: list[dict] | None = None) -> dict[str, Any] | None:
    """Original keyword-driven path. Used as fallback when LLM is unavailable.

    Returns ACCESS_DENIED when the caller's role does not grant the module the
    detected data source reads from.

    `context` lets a follow-up ("i need this bar chart") take its subject from
    the previous turn. RBAC is applied to the resolved source either way, so a
    subject read out of the conversation grants no access the caller lacks.
    """
    chart_type  = _detect_chart_type(query)
    data_source = _detect_data_source(query, context)

    # An entity ID pins the data source even when no keyword matched: "leave
    # balance for EMP001 chart" names no HR keyword, but EMP001 says HR. This
    # runs before the RBAC gate below so the resolved source is still checked.
    #
    # A follow-up inherits the id from the recent turns for the same reason it
    # inherits the subject: after "show EMP001's leave", "now chart it" means
    # that employee. Without this the request resolves to hr_headcount and
    # silently returns a company-wide chart in place of the one asked for.
    emp_match  = _EMP_ID_RE.search(query)
    cust_match = _CUST_ID_RE.search(query)
    if context and not (emp_match or cust_match):
        recent     = _recent_text(context)
        emp_match  = _EMP_ID_RE.search(recent)
        cust_match = _CUST_ID_RE.search(recent)
    if data_source is None:
        if emp_match:
            data_source = "hr_headcount"
        elif cust_match:
            data_source = "sd_customer"

    if data_source is None:
        # The request named no data ("show me in a bar chart"). Decline so the
        # caller falls through to the main agent instead of charting whichever
        # data source used to be the default.
        _logger.info("No data source detected for report query: %s", query)
        return None

    required_module = _DATA_SOURCE_MODULE.get(data_source)
    if required_module and not _module_allowed(required_module, allowed_tools):
        _logger.info("Report denied by RBAC: data_source=%s module=%s",
                     data_source, required_module)
        return ACCESS_DENIED

    # Specific employee ID → individual data chart
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

    # Specific customer ID → that customer's own chart, not a cross-customer
    # aggregate. Orders by value is the informative view; a customer with no
    # orders falls back to their credit profile.
    if cust_match and data_source == "sd_customer":
        cust_id = cust_match.group(0).upper()
        for fetch in (_fetch_customer_orders, _fetch_customer_credit):
            try:
                raw = fetch(cust_id)
            except Exception:
                _logger.warning("Customer chart fetch %s failed for %s",
                                fetch.__name__, cust_id, exc_info=True)
                raw = {}
            if raw:
                return build_payload(chart_type, raw)
        return None

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

def generate(query: str,
             allowed_tools: set[str] | None = None,
             context: list[dict] | None = None) -> dict[str, Any] | None:
    """
    Main entry point called by api/server.py.
    Tries LLM-driven generation first; falls back to hardcoded path.

    `allowed_tools` is the caller's RBAC allow-list and MUST be supplied by any
    authenticated caller — the report agent reaches SAP data directly, so it is
    the only thing standing between an unprivileged user and another module's
    data. Returns ACCESS_DENIED if the role does not permit the requested data,
    a ReportPayload dict on success, or None if no report could be built.

    `context` is the caller's recent conversation history (most recent last).
    It only resolves what a follow-up refers to; every resolved data source is
    still checked against `allowed_tools`, so context grants no extra access.
    """
    return _get_agent().generate(query, allowed_tools, context)


def is_access_denied(payload: dict[str, Any] | None) -> bool:
    """True if `payload` is the RBAC denial sentinel returned by generate()."""
    return isinstance(payload, dict) and payload.get("error") == "access_denied"


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
