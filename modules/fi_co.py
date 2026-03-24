"""
SAP FI/CO Module - Finance & Controlling
Simulates BAPI_ACC_*, FI_*, CO_* function module calls
"""
from db.connection import query_one, query_all
from typing import Any


def get_vendor_info(vendor_id: str) -> dict[str, Any]:
    """BAPI_VENDOR_GETDETAIL - Get vendor master data"""
    row = query_one(
        "SELECT * FROM vendors WHERE vendor_id = %s",
        (vendor_id.upper(),)
    )
    if not row:
        return {"status": "ERROR", "message": f"Vendor {vendor_id} not found"}
    row.pop("created_at", None)
    return {"status": "OK", **row}


def get_invoice_status(invoice_id: str) -> dict[str, Any]:
    """BAPI_INCOMINGINVOICE_GETDETAIL - Get invoice status"""
    row = query_one(
        """
        SELECT i.*, v.name AS vendor_name
        FROM invoices i
        JOIN vendors v ON i.vendor_id = v.vendor_id
        WHERE i.invoice_id = %s
        """,
        (invoice_id.upper(),)
    )
    if not row:
        return {"status": "ERROR", "message": f"Invoice {invoice_id} not found"}
    row.pop("created_at", None)
    return {"status": "OK", **row}


def get_open_invoices(vendor_id: str = None) -> dict[str, Any]:
    """FI_DOCUMENT_GET_LIST - Get list of open invoices"""
    if vendor_id:
        rows = query_all(
            """
            SELECT i.invoice_id, v.name AS vendor_name, i.amount, i.currency, i.due_date
            FROM invoices i
            JOIN vendors v ON i.vendor_id = v.vendor_id
            WHERE i.status = 'OPEN' AND i.vendor_id = %s
            ORDER BY i.due_date
            """,
            (vendor_id.upper(),)
        )
    else:
        rows = query_all(
            """
            SELECT i.invoice_id, v.name AS vendor_name, i.amount, i.currency, i.due_date
            FROM invoices i
            JOIN vendors v ON i.vendor_id = v.vendor_id
            WHERE i.status = 'OPEN'
            ORDER BY i.due_date
            """
        )
    return {"status": "OK", "open_invoices": rows, "count": len(rows)}


def get_cost_center_budget(cost_center_id: str) -> dict[str, Any]:
    """BAPI_COSTCENTER_GETDETAIL - Get cost center budget vs actuals"""
    cc = query_one(
        "SELECT * FROM cost_centers WHERE cost_center_id = %s",
        (cost_center_id.upper(),)
    )
    if not cc:
        return {"status": "ERROR", "message": f"Cost center {cost_center_id} not found"}
    budget = float(cc["budget"])
    actual = float(cc["actual"])
    remaining = budget - actual
    utilization = round((actual / budget) * 100, 2) if budget else 0.0
    return {
        "status": "OK",
        "cost_center": cc["cost_center_id"],
        "name": cc["name"],
        "department": cc["department"],
        "budget": budget,
        "actual": actual,
        "remaining": remaining,
        "utilization_pct": utilization,
        "currency": cc["currency"],
        "fiscal_year": cc["fiscal_year"],
    }


def get_gl_account_balance(gl_account: str) -> dict[str, Any]:
    """BAPI_GL_GETGLACCOUNTBYLEDNO - Get GL account balance"""
    acc = query_one(
        "SELECT * FROM gl_accounts WHERE gl_account = %s",
        (gl_account,)
    )
    if not acc:
        return {"status": "ERROR", "message": f"GL Account {gl_account} not found"}
    acc.pop("created_at", None)
    return {"status": "OK", **acc}


def list_all_cost_centers() -> dict[str, Any]:
    """List all cost centers with budget summary"""
    rows = query_all("SELECT * FROM cost_centers ORDER BY cost_center_id")
    summary = []
    for cc in rows:
        budget = float(cc["budget"])
        actual = float(cc["actual"])
        utilization = round((actual / budget) * 100, 2) if budget else 0.0
        summary.append({
            "id": cc["cost_center_id"],
            "name": cc["name"],
            "department": cc["department"],
            "budget": budget,
            "actual": actual,
            "utilization_pct": utilization,
            "currency": cc["currency"],
        })
    return {"status": "OK", "cost_centers": summary}
