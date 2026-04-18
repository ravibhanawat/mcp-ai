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


# ─── Real Estate — Alembic Parivartan Project ─────────────────────────────────

def get_gl_posting_for_receipt(park_reference: str) -> dict[str, Any]:
    """GL account mapping for a receipt posting (FI integration).
    T-code: FB01 | Tables: customer_receipts, BKPF/BSEG"""
    receipt = query_one(
        "SELECT * FROM customer_receipts WHERE park_ref = %s",
        (park_reference.upper(),)
    )
    if not receipt:
        return {"status": "ERROR", "message": f"Park reference {park_reference} not found"}

    amount = float(receipt["amount"])

    # GL account mapping based on payment mode
    gl_bank = {
        "Cheque": "100001", "Demand Draft": "100001",
        "Direct Remittance": "100001", "Debit/Credit Card": "100001",
        "Cash": "100001", "On Account": "200002",
        "Journal Voucher": "200002", "TDS": "200003",
        "Credit Note Basic Excess": "200004",
        "Credit Note TDS Excess": "200004",
    }.get(receipt["payment_mode"], "100001")

    gl_descriptions = {
        "100001": "Cash & Bank Balances",
        "200002": "Advance from Customers",
        "200003": "TDS Recoverable Account",
        "200004": "Customer Credit Note Account",
    }

    postings = [
        {
            "posting_key":   "40",
            "gl_account":    gl_bank,
            "account_name":  gl_descriptions.get(gl_bank, "Bank Account"),
            "amount":        amount,
            "dc_indicator":  "Debit",
            "description":   f"Receipt from customer - {receipt['payment_mode']}",
        },
        {
            "posting_key":   "15",
            "gl_account":    "100002",
            "account_name":  "Accounts Receivable — Trade",
            "amount":        amount,
            "dc_indicator":  "Credit",
            "description":   f"Clear customer AR - Unit {receipt['unit_number']}",
        },
    ]

    if float(receipt["excess_basic"]) > 0:
        postings.append({
            "posting_key":  "50",
            "gl_account":   "200002",
            "account_name": "Advance from Customers",
            "amount":       float(receipt["excess_basic"]),
            "dc_indicator": "Credit",
            "description":  "Excess basic amount on-account",
        })

    return {
        "status":         "OK",
        "park_reference": park_reference,
        "fi_doc_no":      receipt["fi_doc_no"],
        "receipt_status": receipt["status"],
        "amount":         amount,
        "payment_mode":   receipt["payment_mode"],
        "postings":       postings,
        "company_code":   "ALEC",
        "posting_period": __import__("datetime").datetime.now().strftime("%m/%Y"),
        "sap_source": {
            "tcode": "FB01",
            "table": "customer_receipts, BKPF/BSEG",
            "bapi":  "BAPI_ACC_DOCUMENT_POST"
        }
    }


def get_customer_ledger(customer_id: str, unit_number: str) -> dict[str, Any]:
    """FBL5N-style customer open item display — debit (billing) and credit (receipt) entries.
    T-code: FBL5N | Tables: re_milestones, customer_receipts"""
    cust = query_one(
        "SELECT name FROM re_customers WHERE customer_id = %s AND unit_number = %s",
        (customer_id.upper(), unit_number.upper())
    )
    if not cust:
        return {"status": "ERROR", "message": f"Customer {customer_id} / unit {unit_number} not found"}

    # Debit entries — billing documents
    milestones = query_all(
        """
        SELECT milestone_code, description, billing_doc_no,
               basic_amt, cgst_amt, sgst_amt, billing_date, status
        FROM re_milestones
        WHERE customer_id = %s AND unit_number = %s AND billing_doc_no IS NOT NULL
        ORDER BY billing_date NULLS LAST, milestone_code
        """,
        (customer_id.upper(), unit_number.upper())
    )

    # Credit entries — posted receipts
    receipts = query_all(
        """
        SELECT park_ref, payment_mode, amount, instrument_date, fi_doc_no, posted_at
        FROM customer_receipts
        WHERE customer_id = %s AND unit_number = %s AND status = 'POSTED'
        ORDER BY posted_at
        """,
        (customer_id.upper(), unit_number.upper())
    )

    ledger_items = []
    running_balance = 0.0

    for m in milestones:
        gross = float(m["basic_amt"]) + float(m["cgst_amt"]) + float(m["sgst_amt"])
        running_balance += gross
        ledger_items.append({
            "doc_type":      "DR",
            "document_no":   m["billing_doc_no"],
            "description":   m["description"],
            "posting_date":  str(m["billing_date"]) if m["billing_date"] else "Pending",
            "debit":         round(gross, 2),
            "credit":        0.0,
            "balance":       round(running_balance, 2),
        })

    for r in receipts:
        running_balance -= float(r["amount"])
        ledger_items.append({
            "doc_type":      "CR",
            "document_no":   r["fi_doc_no"] or r["park_ref"],
            "description":   f"Receipt — {r['payment_mode']}",
            "posting_date":  r["posted_at"].strftime("%Y-%m-%d") if r["posted_at"] else None,
            "debit":         0.0,
            "credit":        float(r["amount"]),
            "balance":       round(running_balance, 2),
        })

    # Sort by posting date for proper FBL5N view
    ledger_items.sort(key=lambda x: x["posting_date"] or "")

    # Recalculate running balance in sorted order
    running = 0.0
    for item in ledger_items:
        running += item["debit"] - item["credit"]
        item["balance"] = round(running, 2)

    return {
        "status":          "OK",
        "customer_name":   cust["name"],
        "customer_id":     customer_id.upper(),
        "unit_number":     unit_number.upper(),
        "ledger_items":    ledger_items,
        "total_debit":     round(sum(i["debit"] for i in ledger_items), 2),
        "total_credit":    round(sum(i["credit"] for i in ledger_items), 2),
        "closing_balance": round(running, 2),
        "currency":        "INR",
        "sap_source": {
            "tcode": "FBL5N",
            "table": "re_milestones, customer_receipts / BSID, BSAD",
            "bapi":  "BAPI_CUSTOMER_GETACCOUNTDETAIL"
        }
    }


def get_tds_certificate_data(customer_id: str, fiscal_year: str) -> dict[str, Any]:
    """TDS deduction summary for Form 16A / 26QB compliance.
    T-code: S_PH0_48000514 | Table: customer_receipts / WITH_ITEM"""
    cust = query_one(
        "SELECT name, pan_number, unit_number FROM re_customers WHERE customer_id = %s",
        (customer_id.upper(),)
    )
    if not cust:
        return {"status": "ERROR", "message": f"Customer {customer_id} not found"}

    # In demo mode: fetch TDS-mode receipts posted in the fiscal year
    # FY format: "2025-26" means 2025-04-01 to 2026-03-31
    try:
        fy_start_year = int(fiscal_year.split("-")[0])
        fy_start = f"{fy_start_year}-04-01"
        fy_end   = f"{fy_start_year + 1}-03-31"
    except (ValueError, IndexError):
        return {"status": "ERROR", "message": "Invalid fiscal_year format. Use: 2025-26"}

    tds_receipts = query_all(
        """
        SELECT park_ref, amount, payment_mode, instrument_date, fi_doc_no, posted_at
        FROM customer_receipts
        WHERE customer_id = %s
          AND payment_mode = 'TDS'
          AND status = 'POSTED'
          AND posted_at BETWEEN %s AND %s
        ORDER BY posted_at
        """,
        (customer_id.upper(), fy_start, fy_end)
    )

    tds_entries = [
        {
            "document_no":   r["fi_doc_no"] or r["park_ref"],
            "deduction_date": r["posted_at"].strftime("%Y-%m-%d") if r["posted_at"] else None,
            "tds_amount":    float(r["amount"]),
            "payment_mode":  r["payment_mode"],
        }
        for r in tds_receipts
    ]

    total_tds = sum(e["tds_amount"] for e in tds_entries)

    return {
        "status":           "OK",
        "certificate_type": "Form 16A / 26QB",
        "fiscal_year":      fiscal_year,
        "customer_id":      customer_id.upper(),
        "customer_name":    cust["name"],
        "pan_deductee":     cust["pan_number"],
        "pan_deductor":     "AAACA1234B",    # Alembic Real Estate PAN (demo)
        "tan_deductor":     "AHMA12345B",    # TAN (demo)
        "tds_entries":      tds_entries,
        "total_tds_deducted": round(total_tds, 2),
        "tds_rate_pct":     1.0,
        "section":          "194-IA (TDS on Immovable Property)",
        "currency":         "INR",
        "sap_source": {
            "tcode": "S_PH0_48000514",
            "table": "customer_receipts / WITH_ITEM",
            "bapi":  "N/A"
        }
    }
