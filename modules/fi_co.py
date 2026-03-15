"""
SAP FI/CO Module - Finance & Controlling
Simulates BAPI_ACC_*, FI_*, CO_* function module calls
"""
from mock_data.sap_data import VENDORS, INVOICES, COST_CENTERS, GL_ACCOUNTS
from typing import Any


def get_vendor_info(vendor_id: str) -> dict[str, Any]:
    """BAPI_VENDOR_GETDETAIL - Get vendor master data"""
    v = VENDORS.get(vendor_id.upper())
    if not v:
        return {"status": "ERROR", "message": f"Vendor {vendor_id} not found"}
    return {"status": "OK", "vendor_id": vendor_id, **v}


def get_invoice_status(invoice_id: str) -> dict[str, Any]:
    """BAPI_INCOMINGINVOICE_GETDETAIL - Get invoice status"""
    inv = INVOICES.get(invoice_id.upper())
    if not inv:
        return {"status": "ERROR", "message": f"Invoice {invoice_id} not found"}
    vendor = VENDORS.get(inv["vendor"], {})
    return {
        "status": "OK",
        "invoice_id": invoice_id,
        "vendor_name": vendor.get("name", "Unknown"),
        **inv
    }


def get_open_invoices(vendor_id: str = None) -> dict[str, Any]:
    """FI_DOCUMENT_GET_LIST - Get list of open invoices"""
    results = []
    for inv_id, inv in INVOICES.items():
        if inv["status"] == "OPEN":
            if vendor_id is None or inv["vendor"] == vendor_id.upper():
                vendor = VENDORS.get(inv["vendor"], {})
                results.append({
                    "invoice_id": inv_id,
                    "vendor_name": vendor.get("name", "Unknown"),
                    "amount": inv["amount"],
                    "currency": inv["currency"],
                    "due_date": inv["due_date"]
                })
    return {"status": "OK", "open_invoices": results, "count": len(results)}


def get_cost_center_budget(cost_center_id: str) -> dict[str, Any]:
    """BAPI_COSTCENTER_GETDETAIL - Get cost center budget vs actuals"""
    cc = COST_CENTERS.get(cost_center_id.upper())
    if not cc:
        return {"status": "ERROR", "message": f"Cost center {cost_center_id} not found"}
    remaining = cc["budget"] - cc["actual"]
    utilization = round((cc["actual"] / cc["budget"]) * 100, 2)
    return {
        "status": "OK",
        "cost_center": cost_center_id,
        "name": cc["name"],
        "budget": cc["budget"],
        "actual": cc["actual"],
        "remaining": remaining,
        "utilization_pct": utilization,
        "currency": cc["currency"]
    }


def get_gl_account_balance(gl_account: str) -> dict[str, Any]:
    """BAPI_GL_GETGLACCOUNTBYLEDNO - Get GL account balance"""
    acc = GL_ACCOUNTS.get(gl_account)
    if not acc:
        return {"status": "ERROR", "message": f"GL Account {gl_account} not found"}
    return {"status": "OK", "gl_account": gl_account, **acc}


def list_all_cost_centers() -> dict[str, Any]:
    """List all cost centers with budget summary"""
    summary = []
    for cc_id, cc in COST_CENTERS.items():
        utilization = round((cc["actual"] / cc["budget"]) * 100, 2)
        summary.append({
            "id": cc_id,
            "name": cc["name"],
            "budget": cc["budget"],
            "actual": cc["actual"],
            "utilization_pct": utilization,
            "currency": cc["currency"]
        })
    return {"status": "OK", "cost_centers": summary}
