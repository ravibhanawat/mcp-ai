"""
Role-Based Access Control (RBAC) for SAP AI Agent.

Finance users cannot access HR salary data, etc.
Each role maps to specific SAP modules.
"""

# Maps role name → list of SAP modules accessible
ROLE_MODULES: dict[str, list[str]] = {
    "admin":          ["fi_co", "mm", "sd", "hr", "pp", "abap", "receipt"],
    "fi_co_analyst":  ["fi_co"],
    "mm_analyst":     ["mm"],
    "sd_analyst":     ["sd"],
    "hr_manager":     ["hr"],
    "pp_planner":     ["pp"],
    "abap_developer": ["abap"],
    "re_analyst":     ["sd", "fi_co", "receipt", "fi_co_re"],   # Alembic RE sales team
    "read_only":      [],   # general questions only, no SAP data
}

ALL_ROLES = list(ROLE_MODULES.keys())

# Maps SAP module → tool names
MODULE_TOOLS: dict[str, list[str]] = {
    "fi_co": [
        "get_vendor_info",
        "get_invoice_status",
        "get_open_invoices",
        "get_cost_center_budget",
        "list_all_cost_centers",
        "get_gl_posting_for_receipt",
        "get_customer_ledger",
        "get_tds_certificate_data",
    ],
    "mm": [
        "get_material_info",
        "get_stock_level",
        "get_purchase_order",
        "list_open_purchase_orders",
        "check_reorder_needed",
    ],
    "sd": [
        "get_customer_info",
        "get_sales_order",
        "get_customer_orders",
        "create_sales_order",
        "list_open_sales_orders",
        "get_sales_deed_data",
        "get_allotment_letter_data",
        "validate_einvoice_b2b",
        "get_broker_payout_status",
        "initiate_broker_po",
    ],
    "hr": [
        "get_employee_info",
        "get_leave_balance",
        "get_payslip",
        "apply_leave",
        "search_employees",
    ],
    "pp": [
        "get_production_order",
        "get_bill_of_materials",
        "create_production_order",
        "list_production_orders",
        "get_capacity_utilization",
    ],
    "abap": [
        "get_abap_program",
        "get_function_module",
        "get_transport_request",
        "list_abap_programs",
        "analyze_abap_syntax",
    ],
    "receipt": [
        "get_customer_unit_outstanding",
        "calculate_receipt_allocation",
        "park_customer_receipt",
        "post_customer_receipt",
        "get_receipt_history",
        "get_milestone_billing_status",
    ],
    "fi_co_re": [
        "get_gl_posting_for_receipt",
        "get_customer_ledger",
        "get_tds_certificate_data",
    ],
}

# Reverse map: tool → module
_TOOL_MODULE: dict[str, str] = {
    tool: mod
    for mod, tools in MODULE_TOOLS.items()
    for tool in tools
}


def get_allowed_tools(roles: list[str]) -> set[str]:
    """Return the set of tool names the given roles may call."""
    allowed: set[str] = set()
    for role in roles:
        for mod in ROLE_MODULES.get(role, []):
            allowed.update(MODULE_TOOLS.get(mod, []))
    return allowed


def check_tool_access(tool_name: str, roles: list[str]) -> bool:
    """Return True if any of the provided roles can call this tool."""
    return tool_name in get_allowed_tools(roles)


def get_tool_module(tool_name: str) -> str | None:
    """Return the SAP module a tool belongs to, or None."""
    return _TOOL_MODULE.get(tool_name)
