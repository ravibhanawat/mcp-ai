"""
SAP AI Agent - Auto Research Engine
Autonomously chains multiple SAP tool calls for a single entity,
detects anomalies, and returns a structured markdown report.
"""
import re
import json
from datetime import datetime
from typing import Callable


# ─── Research Plans ───────────────────────────────────────────────────────────
# Each plan is a list of steps. Each step:
#   tool      - SAP tool name to call
#   params    - dict of params to pass (may reference entity_id via {entity_id})
#   optional  - if True, skip silently on error
#   label     - human-readable step name for progress display

RESEARCH_PLANS = {
    "vendor": [
        {"tool": "get_vendor_info",      "params": {"vendor_id": "{entity_id}"},  "optional": False, "label": "Vendor Master Data"},
        {"tool": "get_open_invoices",    "params": {"vendor_id": "{entity_id}"},  "optional": False, "label": "Open Invoices"},
        {"tool": "list_open_purchase_orders", "params": {},                        "optional": True,  "label": "Open Purchase Orders"},
    ],
    "material": [
        {"tool": "get_material_info",    "params": {"material_id": "{entity_id}"}, "optional": False, "label": "Material Master Data"},
        {"tool": "get_stock_level",      "params": {"material_id": "{entity_id}"}, "optional": False, "label": "Stock Level"},
        {"tool": "check_reorder_needed", "params": {},                              "optional": True,  "label": "Reorder Analysis"},
        {"tool": "get_bill_of_materials","params": {"material_id": "{entity_id}"}, "optional": True,  "label": "Bill of Materials"},
    ],
    "customer": [
        {"tool": "get_customer_info",    "params": {"customer_id": "{entity_id}"}, "optional": False, "label": "Customer Master Data"},
        {"tool": "get_customer_orders",  "params": {"customer_id": "{entity_id}"}, "optional": False, "label": "Customer Orders"},
        {"tool": "list_open_sales_orders","params": {},                             "optional": True,  "label": "Open Sales Orders"},
    ],
    "employee": [
        {"tool": "get_employee_info",    "params": {"emp_id": "{entity_id}"},      "optional": False, "label": "Employee Master Data"},
        {"tool": "get_leave_balance",    "params": {"emp_id": "{entity_id}"},      "optional": False, "label": "Leave Balance"},
        {"tool": "get_payslip",          "params": {"emp_id": "{entity_id}"},      "optional": False, "label": "Payslip"},
    ],
    "cost_center": [
        {"tool": "get_cost_center_budget","params": {"cost_center_id": "{entity_id}"}, "optional": False, "label": "Cost Center Budget"},
        {"tool": "list_all_cost_centers", "params": {},                                 "optional": True,  "label": "All Cost Centers (for comparison)"},
    ],
    "production_order": [
        {"tool": "get_production_order",  "params": {"order_id": "{entity_id}"},   "optional": False, "label": "Production Order Details"},
        {"tool": "get_capacity_utilization","params": {},                            "optional": True,  "label": "Work Center Capacity"},
        {"tool": "list_production_orders", "params": {},                             "optional": True,  "label": "All Production Orders"},
    ],
}

# ─── Entity Detection Patterns ────────────────────────────────────────────────
ENTITY_PATTERNS = [
    ("vendor",           r'\bv\d{3,}\b'),
    ("material",         r'\bmat\d{3,}\b'),
    ("customer",         r'\bc\d{3,}\b'),
    ("employee",         r'\bemp\d{3,}\b'),
    ("cost_center",      r'\bcc\d{3,}\b'),
    ("production_order", r'\bprd\d{4,}\b'),
]

# Keywords that help disambiguate when pattern alone isn't enough
ENTITY_KEYWORDS = {
    "vendor":           ["vendor", "supplier", "purchase", "invoice"],
    "material":         ["material", "stock", "inventory", "product", "bom", "parts"],
    "customer":         ["customer", "client", "buyer", "sales", "order"],
    "employee":         ["employee", "staff", "worker", "hr", "leave", "payslip"],
    "cost_center":      ["cost center", "budget", "controlling", "cost"],
    "production_order": ["production", "manufacturing", "prd", "work order"],
}


class AutoResearcher:
    """Orchestrates multi-step SAP data gathering for a single entity."""

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self, query: str, execute_tool_fn: Callable) -> dict:
        """
        Main entry point. Returns a dict with:
          - formatted_report: markdown string
          - raw_results: dict of tool_name → result
          - anomalies: list of anomaly dicts
          - sources_used: list of SAP source strings
          - entity_type, entity_id
          - tools_run: list of tool names that were called
          - success: bool
        """
        entity_type, entity_id = self._detect_entity(query)

        if not entity_type:
            return {
                "formatted_report": (
                    "Could not identify a SAP entity in your query.\n\n"
                    "Try: *research vendor V001*, *deep dive on MAT002*, "
                    "*analyze customer C001*, *full report on EMP001*"
                ),
                "raw_results": {},
                "anomalies": [],
                "sources_used": [],
                "entity_type": None,
                "entity_id": None,
                "tools_run": [],
                "success": False,
            }

        plan = RESEARCH_PLANS.get(entity_type, [])
        raw_results = {}
        tools_run = []
        sources_used = []

        for step in plan:
            tool_name = step["tool"]
            params = self._resolve_params(step["params"], entity_id)
            try:
                result = execute_tool_fn(tool_name, params)
                raw_results[tool_name] = result
                tools_run.append(tool_name)
                # Collect SAP sources
                src = result.get("sap_source") if isinstance(result, dict) else None
                if src:
                    bapi = src.get("bapi", "")
                    tcode = src.get("tcode", "")
                    entry = f"{tcode}" + (f" ({bapi})" if bapi and bapi != "N/A" else "")
                    if entry not in sources_used:
                        sources_used.append(entry)
            except Exception as e:
                if not step.get("optional", False):
                    raw_results[tool_name] = {"status": "ERROR", "message": str(e)}
                    tools_run.append(tool_name)
                # optional steps silently skipped

        anomalies = self._detect_anomalies(entity_type, entity_id, raw_results)
        report = self._format_report(entity_type, entity_id, raw_results, anomalies, sources_used, tools_run)

        return {
            "formatted_report": report,
            "raw_results": raw_results,
            "anomalies": anomalies,
            "sources_used": sources_used,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "tools_run": tools_run,
            "success": True,
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _detect_entity(self, query: str) -> tuple[str | None, str | None]:
        """Detect entity type and ID from natural language query."""
        q = query.lower()
        for entity_type, pattern in ENTITY_PATTERNS:
            m = re.search(pattern, q, re.IGNORECASE)
            if m:
                entity_id = m.group(0).upper()
                return entity_type, entity_id
        # Fallback: keyword-only match (no ID, for list-type research)
        for entity_type, keywords in ENTITY_KEYWORDS.items():
            if any(kw in q for kw in keywords):
                return entity_type, None
        return None, None

    def _resolve_params(self, params: dict, entity_id: str | None) -> dict:
        """Replace {entity_id} placeholder with actual entity ID."""
        resolved = {}
        for k, v in params.items():
            if isinstance(v, str) and "{entity_id}" in v:
                resolved[k] = entity_id or ""
            else:
                resolved[k] = v
        return resolved

    def _detect_anomalies(self, entity_type: str, entity_id: str | None, results: dict) -> list[dict]:
        """Rule-based anomaly detection on aggregated tool results."""
        anomalies = []

        if entity_type == "vendor":
            # Check for open/blocked invoices
            inv_result = results.get("get_open_invoices", {})
            invoices = inv_result.get("invoices", []) if isinstance(inv_result, dict) else []
            if isinstance(invoices, list):
                open_count = sum(1 for i in invoices if isinstance(i, dict) and i.get("status") in ("OPEN", "BLOCKED"))
                blocked_count = sum(1 for i in invoices if isinstance(i, dict) and i.get("status") == "BLOCKED")
                if blocked_count > 0:
                    anomalies.append({"severity": "HIGH", "message": f"{blocked_count} invoice(s) are BLOCKED — payment process halted, investigation needed"})
                if open_count > 2:
                    anomalies.append({"severity": "MEDIUM", "message": f"{open_count} open invoices outstanding — review payment schedule"})

            # Check vendor status
            vendor_result = results.get("get_vendor_info", {})
            if isinstance(vendor_result, dict):
                status = vendor_result.get("status", "")
                if status == "BLOCKED":
                    anomalies.append({"severity": "HIGH", "message": "Vendor is BLOCKED in SAP — no new POs can be raised"})

        elif entity_type == "material":
            # Check stock vs reorder
            stock_result = results.get("get_stock_level", {})
            if isinstance(stock_result, dict):
                unrestricted = stock_result.get("unrestricted_stock", stock_result.get("unrestricted", 0))
                reserved = stock_result.get("reserved_stock", stock_result.get("reserved", 0))
                available = (unrestricted or 0) - (reserved or 0)
                if available < 10:
                    anomalies.append({"severity": "HIGH", "message": f"Available stock is critically low ({available} units) — immediate replenishment needed"})
                elif available < 30:
                    anomalies.append({"severity": "MEDIUM", "message": f"Available stock is low ({available} units) — consider raising a purchase order"})

            # Check reorder flags
            reorder_result = results.get("check_reorder_needed", {})
            if isinstance(reorder_result, dict):
                items = reorder_result.get("items_needing_reorder", reorder_result.get("reorder_needed", []))
                if isinstance(items, list) and entity_id and any(
                    (isinstance(i, dict) and i.get("material_id") == entity_id) or i == entity_id
                    for i in items
                ):
                    anomalies.append({"severity": "HIGH", "message": f"Material {entity_id} is flagged for reorder in SAP MRP (MD04)"})

        elif entity_type == "customer":
            # Check open orders and credit exposure
            orders_result = results.get("get_customer_orders", {})
            if isinstance(orders_result, dict):
                orders = orders_result.get("orders", [])
                if isinstance(orders, list):
                    open_orders = [o for o in orders if isinstance(o, dict) and o.get("status") == "OPEN"]
                    total_open_value = sum(
                        (o.get("qty", 0) or 0) * (o.get("price", 0) or 0)
                        for o in open_orders
                    )
                    if len(open_orders) > 3:
                        anomalies.append({"severity": "MEDIUM", "message": f"{len(open_orders)} open sales orders — review credit exposure"})
                    if total_open_value > 1_000_000:
                        anomalies.append({"severity": "HIGH", "message": f"High open order value: ₹{total_open_value:,.0f} — credit limit check required"})

            # Check customer credit limit
            cust_result = results.get("get_customer_info", {})
            if isinstance(cust_result, dict):
                credit_limit = cust_result.get("credit_limit", 0) or 0
                if credit_limit == 0:
                    anomalies.append({"severity": "MEDIUM", "message": "No credit limit set for this customer — may allow unlimited exposure"})

        elif entity_type == "employee":
            # Check leave balance
            leave_result = results.get("get_leave_balance", {})
            if isinstance(leave_result, dict):
                annual = leave_result.get("annual_leave", leave_result.get("annual", {}))
                if isinstance(annual, dict):
                    balance = annual.get("balance", annual.get("remaining", None))
                    if balance is not None and balance < 0:
                        anomalies.append({"severity": "HIGH", "message": f"Negative leave balance ({balance} days) — compliance issue, HR review needed"})
                    elif balance is not None and balance > 30:
                        anomalies.append({"severity": "LOW", "message": f"High leave balance ({balance} days) — employee may not be taking adequate leave"})
                # Check numeric balance at top level
                balance_top = leave_result.get("balance", leave_result.get("remaining_days", None))
                if balance_top is not None and isinstance(balance_top, (int, float)) and balance_top < 0:
                    anomalies.append({"severity": "HIGH", "message": f"Negative leave balance ({balance_top} days) — compliance issue"})

        elif entity_type == "cost_center":
            # Check budget utilization
            budget_result = results.get("get_cost_center_budget", {})
            if isinstance(budget_result, dict):
                budget = budget_result.get("budget", 0) or 0
                actual = budget_result.get("actual_spend", budget_result.get("actual", 0)) or 0
                if budget > 0:
                    utilization = (actual / budget) * 100
                    if utilization > 95:
                        anomalies.append({"severity": "HIGH", "message": f"Budget {utilization:.1f}% utilized — approaching limit, new commitments at risk"})
                    elif utilization > 85:
                        anomalies.append({"severity": "MEDIUM", "message": f"Budget {utilization:.1f}% utilized — monitor closely before month-end"})
                    remaining = budget - actual
                    if remaining < 0:
                        anomalies.append({"severity": "HIGH", "message": f"Budget EXCEEDED by ₹{abs(remaining):,.0f} — immediate controller action needed"})

        elif entity_type == "production_order":
            # Check capacity utilization
            cap_result = results.get("get_capacity_utilization", {})
            if isinstance(cap_result, dict):
                centers = cap_result.get("work_centers", cap_result.get("centers", []))
                if isinstance(centers, list):
                    for wc in centers:
                        if isinstance(wc, dict):
                            util = wc.get("utilization_pct", wc.get("utilization", 0)) or 0
                            if util > 95:
                                name = wc.get("work_center", wc.get("name", "Unknown"))
                                anomalies.append({"severity": "HIGH", "message": f"Work center {name} at {util}% capacity — production bottleneck risk"})

        return anomalies

    def _format_report(
        self,
        entity_type: str,
        entity_id: str | None,
        results: dict,
        anomalies: list[dict],
        sources_used: list[str],
        tools_run: list[str],
    ) -> str:
        """Format all research results as a clean markdown report."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        entity_label = entity_type.replace("_", " ").title()
        title_id = entity_id or "All"

        # ── Header ────────────────────────────────────────────────────────────
        lines = [
            f"## {entity_label} Research Report: {title_id}",
            f"**Generated:** {now}  |  **Tools Used:** {len(tools_run)}  |  **Mode:** Auto Research",
            "",
        ]

        # ── Executive Summary ─────────────────────────────────────────────────
        summary = self._build_summary(entity_type, entity_id, results, anomalies)
        lines += ["### Executive Summary", summary, ""]

        # ── Anomalies section (prominent) ─────────────────────────────────────
        if anomalies:
            lines.append("### Anomalies & Alerts")
            severity_icon = {"HIGH": "🔴", "MEDIUM": "🟠", "LOW": "🟡"}
            for a in anomalies:
                icon = severity_icon.get(a["severity"], "⚪")
                lines.append(f"- {icon} **{a['severity']}**: {a['message']}")
            lines.append("")

        # ── Data sections per tool ────────────────────────────────────────────
        section_labels = {
            "get_vendor_info":           "Vendor Profile",
            "get_open_invoices":         "Open Invoices",
            "list_open_purchase_orders": "Open Purchase Orders",
            "get_material_info":         "Material Master",
            "get_stock_level":           "Stock Overview",
            "check_reorder_needed":      "Reorder Status",
            "get_bill_of_materials":     "Bill of Materials",
            "get_customer_info":         "Customer Profile",
            "get_customer_orders":       "Customer Orders",
            "list_open_sales_orders":    "Open Sales Orders",
            "get_employee_info":         "Employee Profile",
            "get_leave_balance":         "Leave Balance",
            "get_payslip":               "Payslip Summary",
            "get_cost_center_budget":    "Budget Overview",
            "list_all_cost_centers":     "All Cost Centers",
            "get_production_order":      "Production Order",
            "get_capacity_utilization":  "Capacity Utilization",
            "list_production_orders":    "Production Orders",
        }

        for tool_name, result in results.items():
            label = section_labels.get(tool_name, tool_name.replace("_", " ").title())
            lines.append(f"### {label}")
            if not isinstance(result, dict):
                lines.append(f"```\n{result}\n```")
            elif result.get("status") == "ERROR":
                lines.append(f"*Could not retrieve data: {result.get('message', 'Unknown error')}*")
            else:
                # Remove metadata from display
                display = {k: v for k, v in result.items() if k not in ("sap_source", "status")}
                lines.append(self._dict_to_markdown(display))
            lines.append("")

        # ── SAP Sources footer ────────────────────────────────────────────────
        if sources_used:
            lines.append("---")
            lines.append(f"**SAP Sources:** {' · '.join(sources_used)}")

        return "\n".join(lines)

    def _build_summary(self, entity_type: str, entity_id: str | None, results: dict, anomalies: list[dict]) -> str:
        """Generate a 2-3 sentence executive summary from results."""
        high_count = sum(1 for a in anomalies if a["severity"] == "HIGH")
        total_anomalies = len(anomalies)

        if entity_type == "vendor":
            vendor = results.get("get_vendor_info", {})
            name = vendor.get("name", entity_id) if isinstance(vendor, dict) else entity_id
            invoices = results.get("get_open_invoices", {})
            inv_list = invoices.get("invoices", []) if isinstance(invoices, dict) else []
            inv_count = len(inv_list) if isinstance(inv_list, list) else 0
            summary = f"Vendor **{entity_id}** ({name}) has been researched across FI/CO and MM data."
            if inv_count:
                summary += f" {inv_count} invoice(s) found."
        elif entity_type == "material":
            mat = results.get("get_material_info", {})
            desc = mat.get("description", mat.get("desc", entity_id)) if isinstance(mat, dict) else entity_id
            stock = results.get("get_stock_level", {})
            unrestricted = stock.get("unrestricted_stock", stock.get("unrestricted", "N/A")) if isinstance(stock, dict) else "N/A"
            summary = f"Material **{entity_id}** ({desc}) has been analyzed across MM stock and planning data."
            summary += f" Current unrestricted stock: {unrestricted} units."
        elif entity_type == "customer":
            cust = results.get("get_customer_info", {})
            name = cust.get("name", entity_id) if isinstance(cust, dict) else entity_id
            summary = f"Customer **{entity_id}** ({name}) has been researched across SD order and credit data."
        elif entity_type == "employee":
            emp = results.get("get_employee_info", {})
            name = emp.get("name", entity_id) if isinstance(emp, dict) else entity_id
            summary = f"Employee **{entity_id}** ({name}) has been researched across HR master, leave, and payroll data."
        elif entity_type == "cost_center":
            budget_data = results.get("get_cost_center_budget", {})
            cc_name = budget_data.get("name", entity_id) if isinstance(budget_data, dict) else entity_id
            budget = budget_data.get("budget", 0) if isinstance(budget_data, dict) else 0
            actual = budget_data.get("actual_spend", budget_data.get("actual", 0)) if isinstance(budget_data, dict) else 0
            utilization = f"{(actual / budget * 100):.1f}%" if budget else "N/A"
            summary = f"Cost Center **{entity_id}** ({cc_name}) budget utilization is **{utilization}**."
        elif entity_type == "production_order":
            prod = results.get("get_production_order", {})
            status = prod.get("status", "Unknown") if isinstance(prod, dict) else "Unknown"
            summary = f"Production Order **{entity_id}** is currently **{status}**."
        else:
            summary = f"Research completed for {entity_type} {entity_id}."

        if high_count:
            summary += f" **⚠ {high_count} HIGH severity alert(s) detected — immediate action required.**"
        elif total_anomalies:
            summary += f" {total_anomalies} advisory alert(s) noted for review."
        else:
            summary += " No critical anomalies detected."

        return summary

    def _dict_to_markdown(self, data: dict | list, indent: int = 0) -> str:
        """Recursively format a dict/list as readable markdown key-value pairs."""
        if isinstance(data, list):
            if not data:
                return "*No data*"
            if all(isinstance(i, dict) for i in data):
                # Render as table
                keys = list(data[0].keys())
                header = "| " + " | ".join(k.replace("_", " ").upper() for k in keys) + " |"
                sep = "| " + " | ".join("---" for _ in keys) + " |"
                rows = [
                    "| " + " | ".join(str(row.get(k, "—")) for k in keys) + " |"
                    for row in data
                ]
                return "\n".join([header, sep] + rows)
            return "\n".join(f"- {item}" for item in data)

        if isinstance(data, dict):
            lines = []
            prefix = "  " * indent
            for k, v in data.items():
                label = k.replace("_", " ").title()
                if isinstance(v, (dict, list)):
                    lines.append(f"{prefix}**{label}:**")
                    lines.append(self._dict_to_markdown(v, indent + 1))
                else:
                    lines.append(f"{prefix}**{label}:** {v}")
            return "\n".join(lines)

        return str(data)


# ─── Module-level convenience function ────────────────────────────────────────

def run_auto_research(query: str, execute_tool_fn: Callable) -> dict:
    """Top-level function — instantiate AutoResearcher and run research."""
    return AutoResearcher().run(query, execute_tool_fn)


# ─── Trigger detection ─────────────────────────────────────────────────────────

AUTO_RESEARCH_TRIGGERS = [
    "research", "deep dive", "deep-dive", "full report", "full details",
    "analyze", "analyse", "investigate", "complete analysis",
    "everything about", "tell me all about", "comprehensive",
    "all details", "full analysis", "audit", "overview of",
]


def is_auto_research_query(query: str) -> bool:
    """Return True if the query should trigger auto research mode."""
    q = query.lower()
    return any(trigger in q for trigger in AUTO_RESEARCH_TRIGGERS)
