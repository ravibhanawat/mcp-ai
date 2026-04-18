"""
SAP Tool Registry
Maps tool names to actual module functions for the AI agent.
Every tool includes SAP source attribution (BAPI / T-code / table)
so answers can be verified directly in SAP — a Trust requirement.
"""
import json
from modules import fi_co, mm, sd, hr, pp, abap, receipt
from modules.sap_knowledge_base import search_sap_docs

# ─────────────────────────────────────────
# SAP SOURCE ATTRIBUTION
# Maps tool name → SAP objects used to fetch the data.
# Shown with every answer so users can verify in SAP.
# ─────────────────────────────────────────
SAP_SOURCES: dict[str, dict] = {
    # FI/CO
    "get_vendor_info":          {"bapi": "BAPI_VENDOR_GETDETAIL",           "tcode": "XK03",          "table": "LFA1",   "verify": "T-code XK03 → Display Vendor"},
    "get_invoice_status":       {"bapi": "BAPI_INCOMINGINVOICE_GET",         "tcode": "FB03",          "table": "RBKP",   "verify": "T-code FB03 → Display Document"},
    "get_open_invoices":        {"bapi": "BAPI_INCOMINGINVOICE_GETLIST",     "tcode": "FBL1N",         "table": "BSIK",   "verify": "T-code FBL1N → Vendor Line Items"},
    "get_cost_center_budget":   {"bapi": "BAPI_COSTCENTER_GETDETAIL",        "tcode": "KS03",          "table": "CSKS",   "verify": "T-code KS03 → Display Cost Center"},
    "list_all_cost_centers":    {"bapi": "BAPI_COSTCENTER_GETLIST",          "tcode": "KS13",          "table": "CSKS",   "verify": "T-code KS13 → Cost Center List"},
    # MM
    "get_material_info":        {"bapi": "BAPI_MATERIAL_GET_DETAIL",         "tcode": "MM03",          "table": "MARA",   "verify": "T-code MM03 → Display Material"},
    "get_stock_level":          {"bapi": "BAPI_MATERIAL_STOCK_REQ_LIST",     "tcode": "MMBE",          "table": "MARD",   "verify": "T-code MMBE → Stock Overview"},
    "get_purchase_order":       {"bapi": "BAPI_PO_GETDETAIL",                "tcode": "ME23N",         "table": "EKKO",   "verify": "T-code ME23N → Display Purchase Order"},
    "list_open_purchase_orders":{"bapi": "BAPI_PO_GETITEMS",                 "tcode": "ME2M",          "table": "EKKO",   "verify": "T-code ME2M → Purchase Orders by Material"},
    "check_reorder_needed":     {"bapi": "BAPI_MATERIAL_STOCK_REQ_LIST",     "tcode": "MD04",          "table": "MARD",   "verify": "T-code MD04 → Stock/Requirements List"},
    # SD
    "get_customer_info":        {"bapi": "BAPI_CUSTOMER_GETDETAIL",          "tcode": "XD03",          "table": "KNA1",   "verify": "T-code XD03 → Display Customer"},
    "get_sales_order":          {"bapi": "BAPI_SALESORDER_GETLIST",          "tcode": "VA03",          "table": "VBAK",   "verify": "T-code VA03 → Display Sales Order"},
    "get_customer_orders":      {"bapi": "BAPI_SALESORDER_GETLIST",          "tcode": "VA05",          "table": "VBAK",   "verify": "T-code VA05 → List of Sales Orders"},
    "create_sales_order":       {"bapi": "BAPI_SALESORDER_CREATEFROMDAT2",   "tcode": "VA01",          "table": "VBAK",   "verify": "T-code VA01 → Create Sales Order"},
    "list_open_sales_orders":   {"bapi": "BAPI_SALESORDER_GETLIST",          "tcode": "VA05",          "table": "VBAK",   "verify": "T-code VA05 → List of Sales Orders"},
    # HR
    "get_employee_info":        {"bapi": "BAPI_EMPLOYEE_GETDATA",            "tcode": "PA20",          "table": "PA0001", "verify": "T-code PA20 → Display HR Master Data"},
    "get_leave_balance":        {"bapi": "BAPI_ABSENCE_GETLIST",             "tcode": "PT50",          "table": "ABSENCE","verify": "T-code PT50 → Absence Data Overview"},
    "get_payslip":              {"bapi": "BAPI_PAYROLL_RESULT_GETDETAIL",    "tcode": "PC_PAYRESULT",  "table": "PC2BF",  "verify": "T-code PC_PAYRESULT → Payroll Results"},
    "apply_leave":              {"bapi": "BAPI_ABSENCE_CREATE",              "tcode": "PA30",          "table": "ABSENCE","verify": "T-code PA30 → Maintain HR Master Data"},
    "search_employees":         {"bapi": "BAPI_EMPLOYEE_GETDATA",            "tcode": "PA20",          "table": "PA0001", "verify": "T-code PA20 → Display HR Master Data"},
    # PP
    "get_production_order":     {"bapi": "BAPI_PRODORD_GET_DETAIL",          "tcode": "CO03",          "table": "AUFK",   "verify": "T-code CO03 → Display Production Order"},
    "get_bill_of_materials":    {"bapi": "BAPI_MATERIAL_BOM_GETLIST",        "tcode": "CS03",          "table": "STKO",   "verify": "T-code CS03 → Display BOM"},
    "create_production_order":  {"bapi": "BAPI_PRODORD_CREATE",              "tcode": "CO01",          "table": "AUFK",   "verify": "T-code CO01 → Create Production Order"},
    "list_production_orders":   {"bapi": "BAPI_PRODORD_GET_LIST",            "tcode": "COOIS",         "table": "AUFK",   "verify": "T-code COOIS → Production Order Information"},
    "get_capacity_utilization": {"bapi": "BAPI_WORKCENTER_GETCAPACITY",      "tcode": "CR03",          "table": "CRHD",   "verify": "T-code CR03 → Display Work Center"},
    # ABAP
    "get_abap_program":         {"bapi": "N/A",  "tcode": "SE38",  "table": "TRDIR",  "verify": "T-code SE38 → ABAP Editor"},
    "get_function_module":      {"bapi": "N/A",  "tcode": "SE37",  "table": "TFDIR",  "verify": "T-code SE37 → Function Builder"},
    "get_transport_request":    {"bapi": "N/A",  "tcode": "SE10",  "table": "E070",   "verify": "T-code SE10 → Transport Organizer"},
    "list_abap_programs":       {"bapi": "N/A",  "tcode": "SE80",  "table": "TRDIR",  "verify": "T-code SE80 → Object Navigator"},
    "analyze_abap_syntax":      {"bapi": "N/A",  "tcode": "SE38",  "table": "N/A",    "verify": "T-code SE38 → ABAP Editor (Syntax Check)"},
    "generate_abap_code":       {"bapi": "N/A",  "tcode": "SE38",  "table": "N/A",    "verify": "T-code SE38 → ABAP Editor"},
    # Knowledge Base
    "search_sap_docs":          {"bapi": "N/A",  "tcode": "N/A",   "table": "N/A",    "verify": "SAP Knowledge Base (built-in)"},
    # RE — Receipt (ZFI_RECEIPT_PARK / ZFI_RECEIPT_POST)
    "get_customer_unit_outstanding": {"bapi": "Z_RE_GET_OUTSTANDING",  "tcode": "ZFI_RECEIPT_PARK", "table": "re_customers/re_milestones", "verify": "T-code ZFI_RECEIPT_PARK → Receipt Creation Screen"},
    "calculate_receipt_allocation":  {"bapi": "Z_RE_CALC_ALLOCATION",  "tcode": "ZFI_RECEIPT_PARK", "table": "re_milestones",              "verify": "T-code ZFI_RECEIPT_PARK → FIFO Allocation Logic"},
    "park_customer_receipt":         {"bapi": "Z_RE_RECEIPT_PARK",     "tcode": "ZFI_RECEIPT_PARK", "table": "customer_receipts",          "verify": "T-code ZFI_RECEIPT_PARK → Park Receipt"},
    "post_customer_receipt":         {"bapi": "Z_RE_RECEIPT_POST",     "tcode": "ZFI_RECEIPT_POST", "table": "customer_receipts",          "verify": "T-code ZFI_RECEIPT_POST → Post Receipt to FI"},
    "get_receipt_history":           {"bapi": "Z_RE_RECEIPT_LIST",     "tcode": "ZFI_RECEIPT_PARK", "table": "customer_receipts",          "verify": "T-code ZFI_RECEIPT_PARK → Receipt History"},
    "get_milestone_billing_status":  {"bapi": "BAPI_BILLING_GETDETAIL","tcode": "VF03",             "table": "re_milestones",              "verify": "T-code VF03 → Display Billing Document"},
    # RE — SD Parivartan
    "get_sales_deed_data":           {"bapi": "Z_SD_PRINT_WFRICE",     "tcode": "ZSD_PRINT",        "table": "re_customers/re_milestones", "verify": "T-code ZSD_PRINT → Sales Deed Smartform"},
    "get_allotment_letter_data":     {"bapi": "Z_SD_PRINT_ALLOTMENT",  "tcode": "ZSD_PRINT",        "table": "re_customers/re_milestones", "verify": "T-code ZSD_PRINT → Allotment Letter Smartform"},
    "validate_einvoice_b2b":         {"bapi": "Z_EINV_VALIDATE",       "tcode": "VF01",             "table": "re_customers/J_1IGINVREFNUM","verify": "T-code VF01 → Billing Output + E-Invoice Check"},
    "get_broker_payout_status":      {"bapi": "Z_SD_BROKER_PAYOUT",    "tcode": "ZSD_BROKER",       "table": "re_brokers/re_broker_bookings","verify": "T-code ZSD_BROKER → Broker Payout Status"},
    "initiate_broker_po":            {"bapi": "BAPI_PO_CREATE1",       "tcode": "ME21N",            "table": "re_broker_bookings/EKKO",    "verify": "T-code ME21N → Create Broker Payout PO"},
    # RE — FI Parivartan
    "get_gl_posting_for_receipt":    {"bapi": "BAPI_ACC_DOCUMENT_POST","tcode": "FB01",             "table": "customer_receipts/BKPF",     "verify": "T-code FB01 → Post FI Document"},
    "get_customer_ledger":           {"bapi": "BAPI_CUSTOMER_GETACCOUNTDETAIL","tcode": "FBL5N",    "table": "re_milestones/customer_receipts/BSID","verify": "T-code FBL5N → Customer Line Items"},
    "get_tds_certificate_data":      {"bapi": "N/A",                   "tcode": "S_PH0_48000514",   "table": "customer_receipts/WITH_ITEM","verify": "T-code S_PH0_48000514 → TDS Certificate"},
}


def get_sap_source(tool_name: str) -> dict | None:
    """Return the SAP source info for a tool (BAPI, T-code, table, verify hint)."""
    src = SAP_SOURCES.get(tool_name)
    if src:
        return {**src, "tool": tool_name}
    return None

# ─────────────────────────────────────────
# TOOL DEFINITIONS (sent to Ollama)
# ─────────────────────────────────────────
TOOLS = [
    # ── FI/CO Tools ──
    {
        "name": "get_vendor_info",
        "description": "Get vendor master data from SAP FI module. Use when user asks about a vendor or supplier.",
        "module": "FI/CO",
        "parameters": {
            "type": "object",
            "properties": {
                "vendor_id": {"type": "string", "description": "Vendor ID, e.g. V001, V002"}
            },
            "required": ["vendor_id"]
        }
    },
    {
        "name": "get_invoice_status",
        "description": "Get invoice status from SAP FI. Use when user asks about invoice payment, status, or details.",
        "module": "FI/CO",
        "parameters": {
            "type": "object",
            "properties": {
                "invoice_id": {"type": "string", "description": "Invoice ID, e.g. INV1000"}
            },
            "required": ["invoice_id"]
        }
    },
    {
        "name": "get_open_invoices",
        "description": "Get list of all open/unpaid invoices from SAP FI. Optionally filter by vendor.",
        "module": "FI/CO",
        "parameters": {
            "type": "object",
            "properties": {
                "vendor_id": {"type": "string", "description": "Optional vendor ID to filter"}
            },
            "required": []
        }
    },
    {
        "name": "get_cost_center_budget",
        "description": "Get cost center budget vs actual spend from SAP CO. Use for budget queries.",
        "module": "FI/CO",
        "parameters": {
            "type": "object",
            "properties": {
                "cost_center_id": {"type": "string", "description": "Cost center ID, e.g. CC100, CC200"}
            },
            "required": ["cost_center_id"]
        }
    },
    {
        "name": "list_all_cost_centers",
        "description": "List all cost centers with budget summary from SAP CO.",
        "module": "FI/CO",
        "parameters": {"type": "object", "properties": {}, "required": []}
    },
    # ── MM Tools ──
    {
        "name": "get_material_info",
        "description": "Get material master data from SAP MM. Use when user asks about a product or raw material.",
        "module": "MM",
        "parameters": {
            "type": "object",
            "properties": {
                "material_id": {"type": "string", "description": "Material ID, e.g. MAT001, MAT002"}
            },
            "required": ["material_id"]
        }
    },
    {
        "name": "get_stock_level",
        "description": "Get current stock/inventory level for a material in SAP MM. Use for stock, inventory queries.",
        "module": "MM",
        "parameters": {
            "type": "object",
            "properties": {
                "material_id": {"type": "string", "description": "Material ID"},
                "plant": {"type": "string", "description": "Plant code, default 1000"}
            },
            "required": ["material_id"]
        }
    },
    {
        "name": "get_purchase_order",
        "description": "Get purchase order details from SAP MM. Use when user asks about a PO.",
        "module": "MM",
        "parameters": {
            "type": "object",
            "properties": {
                "po_id": {"type": "string", "description": "Purchase order ID, e.g. PO2001"}
            },
            "required": ["po_id"]
        }
    },
    {
        "name": "list_open_purchase_orders",
        "description": "List all open purchase orders from SAP MM.",
        "module": "MM",
        "parameters": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "check_reorder_needed",
        "description": "Check which materials need reordering based on stock levels in SAP MM.",
        "module": "MM",
        "parameters": {"type": "object", "properties": {}, "required": []}
    },
    # ── SD Tools ──
    {
        "name": "get_customer_info",
        "description": "Get customer master data from SAP SD. Use when user asks about a customer.",
        "module": "SD",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "Customer ID, e.g. C001"}
            },
            "required": ["customer_id"]
        }
    },
    {
        "name": "get_sales_order",
        "description": "Get sales order details from SAP SD. Use when user asks about a specific sales order.",
        "module": "SD",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "Sales order ID, e.g. SO5001"}
            },
            "required": ["order_id"]
        }
    },
    {
        "name": "get_customer_orders",
        "description": "Get all sales orders for a specific customer from SAP SD.",
        "module": "SD",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "Customer ID"}
            },
            "required": ["customer_id"]
        }
    },
    {
        "name": "create_sales_order",
        "description": "Create a new sales order in SAP SD. Use when user wants to create/place an order.",
        "module": "SD",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "Customer ID"},
                "material_id": {"type": "string", "description": "Material ID"},
                "qty": {"type": "integer", "description": "Order quantity"},
                "delivery_days": {"type": "integer", "description": "Days until delivery, default 14"}
            },
            "required": ["customer_id", "material_id", "qty"]
        }
    },
    {
        "name": "list_open_sales_orders",
        "description": "List all open/in-progress sales orders from SAP SD.",
        "module": "SD",
        "parameters": {"type": "object", "properties": {}, "required": []}
    },
    # ── HR Tools ──
    {
        "name": "get_employee_info",
        "description": "Get employee master data from SAP HR. Use when user asks about an employee.",
        "module": "HR",
        "parameters": {
            "type": "object",
            "properties": {
                "emp_id": {"type": "string", "description": "Employee ID, e.g. EMP001"}
            },
            "required": ["emp_id"]
        }
    },
    {
        "name": "get_leave_balance",
        "description": "Get employee leave balance from SAP HR. Use for leave, vacation, absence queries.",
        "module": "HR",
        "parameters": {
            "type": "object",
            "properties": {
                "emp_id": {"type": "string", "description": "Employee ID"}
            },
            "required": ["emp_id"]
        }
    },
    {
        "name": "get_payslip",
        "description": "Get employee salary/payslip details from SAP HR. Use for salary, pay queries.",
        "module": "HR",
        "parameters": {
            "type": "object",
            "properties": {
                "emp_id": {"type": "string", "description": "Employee ID"}
            },
            "required": ["emp_id"]
        }
    },
    {
        "name": "apply_leave",
        "description": "Submit a leave application for an employee in SAP HR.",
        "module": "HR",
        "parameters": {
            "type": "object",
            "properties": {
                "emp_id": {"type": "string", "description": "Employee ID"},
                "leave_type": {"type": "string", "description": "Type: annual, sick, or casual"},
                "days": {"type": "integer", "description": "Number of days"},
                "reason": {"type": "string", "description": "Reason for leave"}
            },
            "required": ["emp_id", "leave_type", "days"]
        }
    },
    {
        "name": "search_employees",
        "description": "Search employees by department or position in SAP HR.",
        "module": "HR",
        "parameters": {
            "type": "object",
            "properties": {
                "dept": {"type": "string", "description": "Department name, e.g. IT, HR, Sales"},
                "position": {"type": "string", "description": "Job position title"}
            },
            "required": []
        }
    },
    # ── PP Tools ──
    {
        "name": "get_production_order",
        "description": "Get production order details from SAP PP. Use for manufacturing order queries.",
        "module": "PP",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "Production order ID, e.g. PRD7001"}
            },
            "required": ["order_id"]
        }
    },
    {
        "name": "get_bill_of_materials",
        "description": "Get Bill of Materials (BOM) for a material from SAP PP.",
        "module": "PP",
        "parameters": {
            "type": "object",
            "properties": {
                "material_id": {"type": "string", "description": "Material ID"}
            },
            "required": ["material_id"]
        }
    },
    {
        "name": "create_production_order",
        "description": "Create a new production order in SAP PP.",
        "module": "PP",
        "parameters": {
            "type": "object",
            "properties": {
                "material_id": {"type": "string", "description": "Material to produce"},
                "qty": {"type": "integer", "description": "Quantity to produce"},
                "plant": {"type": "string", "description": "Plant code, default 1000"},
                "work_center": {"type": "string", "description": "Work center ID, default WC001"}
            },
            "required": ["material_id", "qty"]
        }
    },
    {
        "name": "list_production_orders",
        "description": "List production orders from SAP PP, optionally filtered by status.",
        "module": "PP",
        "parameters": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filter by status: PLANNED, IN_PROGRESS, or COMPLETED"}
            },
            "required": []
        }
    },
    {
        "name": "get_capacity_utilization",
        "description": "Get work center capacity utilization from SAP PP.",
        "module": "PP",
        "parameters": {"type": "object", "properties": {}, "required": []}
    },
    # ── ABAP Tools ──
    {
        "name": "get_abap_program",
        "description": "Get ABAP program or report details from SAP (SE38). Use when user asks about an ABAP program, report, or custom Z-program.",
        "module": "ABAP",
        "parameters": {
            "type": "object",
            "properties": {
                "program_name": {"type": "string", "description": "ABAP program name, e.g. ZREP_VENDOR_LIST"}
            },
            "required": ["program_name"]
        }
    },
    {
        "name": "get_function_module",
        "description": "Get function module details and parameters from SAP (SE37). Use when user asks about a function module or FM.",
        "module": "ABAP",
        "parameters": {
            "type": "object",
            "properties": {
                "fm_name": {"type": "string", "description": "Function module name, e.g. Z_GET_VENDOR_MASTER"}
            },
            "required": ["fm_name"]
        }
    },
    {
        "name": "get_transport_request",
        "description": "Get transport request status and objects from SAP (SE10/STMS). Use when user asks about a TR, transport, or change request.",
        "module": "ABAP",
        "parameters": {
            "type": "object",
            "properties": {
                "tr_id": {"type": "string", "description": "Transport request ID, e.g. DEVK900123"}
            },
            "required": ["tr_id"]
        }
    },
    {
        "name": "list_abap_programs",
        "description": "List ABAP programs in SAP (SE80), optionally filtered by package. Use when user wants to browse or list custom programs.",
        "module": "ABAP",
        "parameters": {
            "type": "object",
            "properties": {
                "package": {"type": "string", "description": "Optional package name, e.g. ZFICO, ZMM, ZSD, ZHR"}
            },
            "required": []
        }
    },
    {
        "name": "analyze_abap_syntax",
        "description": "Analyze ABAP code snippet for syntax issues, performance problems, and best practice violations. Use when user pastes or asks to check ABAP code.",
        "module": "ABAP",
        "parameters": {
            "type": "object",
            "properties": {
                "code_snippet": {"type": "string", "description": "ABAP code to analyze"}
            },
            "required": ["code_snippet"]
        }
    },
    # ── RE — Receipt Tools (ZFI_RECEIPT_PARK / ZFI_RECEIPT_POST) ──
    {
        "name": "get_customer_unit_outstanding",
        "description": "Get outstanding milestone billing documents for a real estate customer and unit. Use when user asks about dues, outstanding amounts, or receipt creation for Alembic Parivartan project.",
        "module": "RE",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id":  {"type": "string", "description": "RE Customer ID, e.g. ALEC001"},
                "unit_number":  {"type": "string", "description": "Unit number, e.g. T1-304, PC-1102"}
            },
            "required": ["customer_id", "unit_number"]
        }
    },
    {
        "name": "calculate_receipt_allocation",
        "description": "Calculate FIFO allocation of a payment across outstanding milestone billing documents. Use to preview how a receipt will be applied before parking.",
        "module": "RE",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id":   {"type": "string", "description": "RE Customer ID"},
                "unit_number":   {"type": "string", "description": "Unit number"},
                "payment_mode":  {
                    "type": "string",
                    "description": "Payment mode",
                    "enum": ["Cheque","Demand Draft","Direct Remittance","TDS","Debit/Credit Card","Cash","Credit Note Basic Excess","Credit Note TDS Excess","On Account","Journal Voucher"]
                },
                "amount":        {"type": "number", "description": "Payment amount in INR"},
                "reference":     {"type": "string", "description": "Optional instrument reference"}
            },
            "required": ["customer_id", "unit_number", "payment_mode", "amount"]
        }
    },
    {
        "name": "park_customer_receipt",
        "description": "Park a customer receipt in SAP (ZFI_RECEIPT_PARK). Allocates payment using FIFO logic and saves as PARKED. Returns park reference number.",
        "module": "RE",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id":    {"type": "string", "description": "RE Customer ID"},
                "unit_number":    {"type": "string", "description": "Unit number"},
                "payment_mode":   {
                    "type": "string",
                    "enum": ["Cheque","Demand Draft","Direct Remittance","TDS","Debit/Credit Card","Cash","Credit Note Basic Excess","Credit Note TDS Excess","On Account","Journal Voucher"]
                },
                "amount":         {"type": "number", "description": "Amount in INR"},
                "instrument_ref": {"type": "string", "description": "Cheque/DD/UTR number"},
                "instrument_date":{"type": "string", "description": "Instrument date (YYYY-MM-DD)"},
                "bank_name":      {"type": "string", "description": "Bank name"}
            },
            "required": ["customer_id", "unit_number", "payment_mode", "amount", "instrument_ref", "instrument_date"]
        }
    },
    {
        "name": "post_customer_receipt",
        "description": "Post a parked receipt to FI (ZFI_RECEIPT_POST). Updates milestone collections and generates FI document number.",
        "module": "RE",
        "parameters": {
            "type": "object",
            "properties": {
                "park_reference": {"type": "string", "description": "Park reference number, e.g. PRK00000001"}
            },
            "required": ["park_reference"]
        }
    },
    {
        "name": "get_receipt_history",
        "description": "Get receipt history (parked and posted) for a customer and unit in Alembic Parivartan project.",
        "module": "RE",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "RE Customer ID"},
                "unit_number": {"type": "string", "description": "Unit number"}
            },
            "required": ["customer_id", "unit_number"]
        }
    },
    {
        "name": "get_milestone_billing_status",
        "description": "Get milestone-wise billing and collection status for a real estate customer — raised, collected, outstanding per milestone.",
        "module": "RE",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "RE Customer ID"},
                "unit_number": {"type": "string", "description": "Unit number"}
            },
            "required": ["customer_id", "unit_number"]
        }
    },
    # ── RE — SD Parivartan (ZSD_PRINT Smartforms, E-Invoice, Broker) ──
    {
        "name": "get_sales_deed_data",
        "description": "Get Sales Deed data for a customer and unit (SD01E — ZSD_PRINT Smartform). Returns customer, unit, and financial details for legal document generation.",
        "module": "RE",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "RE Customer ID"},
                "unit_number": {"type": "string", "description": "Unit number"}
            },
            "required": ["customer_id", "unit_number"]
        }
    },
    {
        "name": "get_allotment_letter_data",
        "description": "Get Allotment Letter data for a customer/unit. SD01J for Cloud Forest, SD01K for Park Crescent. Use project_code to select the correct letter format.",
        "module": "RE",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id":  {"type": "string", "description": "RE Customer ID"},
                "unit_number":  {"type": "string", "description": "Unit number"},
                "project_code": {
                    "type": "string",
                    "description": "Project code",
                    "enum": ["CLOUD_FOREST", "PARK_CRESCENT"]
                }
            },
            "required": ["customer_id", "unit_number", "project_code"]
        }
    },
    {
        "name": "validate_einvoice_b2b",
        "description": "Validate e-Invoice for a B2B billing document at VF01 (SD01F). Checks if customer has GSTIN (B2B) and verifies IRN exists in J_1IGINVREFNUM.",
        "module": "RE",
        "parameters": {
            "type": "object",
            "properties": {
                "billing_doc_no": {"type": "string", "description": "Billing document number, e.g. 9000010001"}
            },
            "required": ["billing_doc_no"]
        }
    },
    {
        "name": "get_broker_payout_status",
        "description": "Get broker payout eligibility and status for all bookings. Shows collection %, payout amount, and eligibility (min 20% collection required).",
        "module": "RE",
        "parameters": {
            "type": "object",
            "properties": {
                "broker_id": {"type": "string", "description": "Broker ID, e.g. BR001"}
            },
            "required": ["broker_id"]
        }
    },
    {
        "name": "initiate_broker_po",
        "description": "Create a broker payout PO (ME21N) for an eligible booking. Validates 20% collection threshold. Returns PO number and release workflow status.",
        "module": "RE",
        "parameters": {
            "type": "object",
            "properties": {
                "broker_id":   {"type": "string", "description": "Broker ID"},
                "unit_number": {"type": "string", "description": "Unit number"}
            },
            "required": ["broker_id", "unit_number"]
        }
    },
    # ── RE — FI Parivartan ──
    {
        "name": "get_gl_posting_for_receipt",
        "description": "Show GL account mapping for a receipt posting in FI (FB01). Use to verify how a receipt will be posted to the general ledger.",
        "module": "RE",
        "parameters": {
            "type": "object",
            "properties": {
                "park_reference": {"type": "string", "description": "Park reference number"}
            },
            "required": ["park_reference"]
        }
    },
    {
        "name": "get_customer_ledger",
        "description": "FBL5N-style customer ledger — all debit (billing) and credit (receipt) entries with running balance for a real estate customer.",
        "module": "RE",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "RE Customer ID"},
                "unit_number": {"type": "string", "description": "Unit number"}
            },
            "required": ["customer_id", "unit_number"]
        }
    },
    {
        "name": "get_tds_certificate_data",
        "description": "Get TDS deduction summary for Form 16A / 26QB compliance for a real estate customer.",
        "module": "RE",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id":  {"type": "string", "description": "RE Customer ID"},
                "fiscal_year":  {"type": "string", "description": "Fiscal year in format 2025-26"}
            },
            "required": ["customer_id", "fiscal_year"]
        }
    },
    # ── Knowledge Base / Documentation Tool ──
    {
        "name": "search_sap_docs",
        "description": (
            "Search SAP documentation, T-codes, BAPIs, and process guides. "
            "Use when the user asks HOW to do something in SAP, asks about a T-code, BAPI, "
            "business process (P2P, O2C, onboarding), configuration, or error resolution."
        ),
        "module": "Knowledge",
        "parameters": {
            "type": "object",
            "properties": {
                "query":    {"type": "string", "description": "Search query, e.g. 'how to create purchase order' or 'invoice blocked MIRO'"},
                "category": {
                    "type": "string",
                    "description": "Optional filter: tcode, bapi, process, error, or configuration",
                    "enum": ["tcode", "bapi", "process", "error", "configuration"]
                },
                "max_results": {"type": "integer", "description": "Max results to return (default 3)"}
            },
            "required": ["query"]
        }
    },
]

# ─────────────────────────────────────────
# FUNCTION EXECUTOR
# ─────────────────────────────────────────
FUNCTION_MAP = {
    # FI/CO
    "get_vendor_info": fi_co.get_vendor_info,
    "get_invoice_status": fi_co.get_invoice_status,
    "get_open_invoices": fi_co.get_open_invoices,
    "get_cost_center_budget": fi_co.get_cost_center_budget,
    "list_all_cost_centers": fi_co.list_all_cost_centers,
    # MM
    "get_material_info": mm.get_material_info,
    "get_stock_level": mm.get_stock_level,
    "get_purchase_order": mm.get_purchase_order,
    "list_open_purchase_orders": mm.list_open_purchase_orders,
    "check_reorder_needed": mm.check_reorder_needed,
    # SD
    "get_customer_info": sd.get_customer_info,
    "get_sales_order": sd.get_sales_order,
    "get_customer_orders": sd.get_customer_orders,
    "create_sales_order": sd.create_sales_order,
    "list_open_sales_orders": sd.list_open_sales_orders,
    # HR
    "get_employee_info": hr.get_employee_info,
    "get_leave_balance": hr.get_leave_balance,
    "get_payslip": hr.get_payslip,
    "apply_leave": hr.apply_leave,
    "search_employees": hr.search_employees,
    # PP
    "get_production_order": pp.get_production_order,
    "get_bill_of_materials": pp.get_bill_of_materials,
    "create_production_order": pp.create_production_order,
    "list_production_orders": pp.list_production_orders,
    "get_capacity_utilization": pp.get_capacity_utilization,
    # ABAP
    "get_abap_program": abap.get_abap_program,
    "get_function_module": abap.get_function_module,
    "get_transport_request": abap.get_transport_request,
    "list_abap_programs": abap.list_abap_programs,
    "analyze_abap_syntax": abap.analyze_abap_syntax,
    "generate_abap_code": abap.generate_abap_code,
    # Knowledge Base
    "search_sap_docs": search_sap_docs,
    # RE — Receipt
    "get_customer_unit_outstanding": receipt.get_customer_unit_outstanding,
    "calculate_receipt_allocation":  receipt.calculate_receipt_allocation,
    "park_customer_receipt":         receipt.park_customer_receipt,
    "post_customer_receipt":         receipt.post_customer_receipt,
    "get_receipt_history":           receipt.get_receipt_history,
    "get_milestone_billing_status":  receipt.get_milestone_billing_status,
    # RE — SD
    "get_sales_deed_data":           sd.get_sales_deed_data,
    "get_allotment_letter_data":     sd.get_allotment_letter_data,
    "validate_einvoice_b2b":         sd.validate_einvoice_b2b,
    "get_broker_payout_status":      sd.get_broker_payout_status,
    "initiate_broker_po":            sd.initiate_broker_po,
    # RE — FI
    "get_gl_posting_for_receipt":    fi_co.get_gl_posting_for_receipt,
    "get_customer_ledger":           fi_co.get_customer_ledger,
    "get_tds_certificate_data":      fi_co.get_tds_certificate_data,
}


def execute_tool(tool_name: str, parameters: dict) -> dict:
    """Execute a SAP tool by name with given parameters.
    Always injects sap_source so every answer can be verified in SAP."""
    func = FUNCTION_MAP.get(tool_name)
    if not func:
        return {"status": "ERROR", "message": f"Unknown tool: {tool_name}"}
    try:
        result = func(**parameters)
        # Inject SAP source attribution into every successful result
        src = get_sap_source(tool_name)
        if src and isinstance(result, dict):
            result["sap_source"] = src
        return result
    except Exception as e:
        return {"status": "ERROR", "message": f"Tool execution error: {str(e)}"}


def get_tools_for_prompt(allowed_tools: set[str] | None = None) -> str:
    """Format tools as JSON string for Ollama system prompt.
    If allowed_tools is provided, only include those tools (RBAC filtering)."""
    tools_info = []
    for tool in TOOLS:
        if allowed_tools is not None and tool["name"] not in allowed_tools:
            continue
        entry = {
            "name": tool["name"],
            "module": tool["module"],
            "description": tool["description"],
            "parameters": tool["parameters"],
        }
        src = SAP_SOURCES.get(tool["name"])
        if src:
            entry["sap_source"] = {"bapi": src["bapi"], "tcode": src["tcode"], "table": src["table"]}
        tools_info.append(entry)
    return json.dumps(tools_info, indent=2)
