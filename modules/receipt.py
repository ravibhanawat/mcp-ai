"""
SAP RE Receipt Module — Alembic Parivartan Project
Implements ZFI_RECEIPT_PARK and ZFI_RECEIPT_POST logic for customer receipt creation.
FIFO allocation across milestone billing documents with 10 payment mode variants.
"""
from db.connection import query_one, query_all, execute
from typing import Any
from datetime import datetime
import random
import string


# Payment modes that adjust Basic + GST (FIFO)
_BASIC_GST_MODES = {
    "Cheque", "Demand Draft", "Direct Remittance",
    "Debit/Credit Card", "Cash", "On Account", "Journal Voucher"
}


def get_customer_unit_outstanding(customer_id: str, unit_number: str) -> dict[str, Any]:
    """ZFI_RECEIPT_PARK — Fetch outstanding milestone billing docs for a customer/unit.
    T-code: ZFI_RECEIPT_PARK | Table: re_customers, re_milestones"""
    cust = query_one(
        "SELECT * FROM re_customers WHERE customer_id = %s AND unit_number = %s",
        (customer_id.upper(), unit_number.upper())
    )
    if not cust:
        return {"status": "ERROR", "message": f"Customer {customer_id} / unit {unit_number} not found"}

    milestones = query_all(
        """
        SELECT milestone_code, description, billing_doc_no,
               basic_amt, cgst_amt, sgst_amt, tds_amt,
               basic_collected, cgst_collected, sgst_collected, tds_collected,
               status, billing_date
        FROM re_milestones
        WHERE customer_id = %s AND unit_number = %s
        ORDER BY milestone_code
        """,
        (customer_id.upper(), unit_number.upper())
    )

    outstanding_items = []
    total_basic_os = 0.0
    total_cgst_os = 0.0
    total_sgst_os = 0.0
    total_tds_os = 0.0

    for m in milestones:
        basic_os = float(m["basic_amt"]) - float(m["basic_collected"])
        cgst_os  = float(m["cgst_amt"])  - float(m["cgst_collected"])
        sgst_os  = float(m["sgst_amt"])  - float(m["sgst_collected"])
        tds_os   = float(m["tds_amt"])   - float(m["tds_collected"])
        net_os   = basic_os + cgst_os + sgst_os - tds_os

        if net_os <= 0 and m["status"] == "COLLECTED":
            continue  # skip fully collected milestones from outstanding display

        outstanding_items.append({
            "milestone_code":   m["milestone_code"],
            "description":      m["description"],
            "billing_doc_no":   m["billing_doc_no"],
            "basic_outstanding": round(basic_os, 2),
            "cgst_outstanding":  round(cgst_os, 2),
            "sgst_outstanding":  round(sgst_os, 2),
            "tds_outstanding":   round(tds_os, 2),
            "net_outstanding":   round(net_os, 2),
            "billing_date":      str(m["billing_date"]) if m["billing_date"] else None,
            "status":            m["status"],
        })
        total_basic_os += basic_os
        total_cgst_os  += cgst_os
        total_sgst_os  += sgst_os
        total_tds_os   += tds_os

    return {
        "status":                "OK",
        "customer_id":           cust["customer_id"],
        "customer_name":         cust["name"],
        "pan":                   cust["pan_number"],
        "project":               cust["project"],
        "unit_number":           cust["unit_number"],
        "tower":                 cust["tower"],
        "floor":                 cust["floor"],
        "area_sqft":             float(cust["area_sqft"]) if cust["area_sqft"] else None,
        "sale_value":            float(cust["sale_value"]) if cust["sale_value"] else None,
        "outstanding_items":     outstanding_items,
        "total_basic_outstanding": round(total_basic_os, 2),
        "total_cgst_outstanding":  round(total_cgst_os, 2),
        "total_sgst_outstanding":  round(total_sgst_os, 2),
        "total_tds_outstanding":   round(total_tds_os, 2),
        "total_outstanding":       round(total_basic_os + total_cgst_os + total_sgst_os - total_tds_os, 2),
        "sap_source": {
            "tcode": "ZFI_RECEIPT_PARK",
            "table": "re_customers, re_milestones",
            "bapi":  "Z_RE_GET_OUTSTANDING"
        }
    }


def calculate_receipt_allocation(
    customer_id: str,
    unit_number: str,
    payment_mode: str,
    amount: float,
    reference: str = ""
) -> dict[str, Any]:
    """Pure FIFO allocation logic — no DB writes.
    T-code: ZFI_RECEIPT_PARK | Logic: SD01ZM FIFO rules"""
    milestones = query_all(
        """
        SELECT milestone_code, description, billing_doc_no,
               basic_amt, cgst_amt, sgst_amt, tds_amt,
               basic_collected, cgst_collected, sgst_collected, tds_collected
        FROM re_milestones
        WHERE customer_id = %s AND unit_number = %s
          AND status IN ('PENDING', 'PARTIAL')
        ORDER BY milestone_code
        """,
        (customer_id.upper(), unit_number.upper())
    )

    if not milestones:
        return {"status": "ERROR", "message": "No outstanding milestones found for allocation"}

    remaining = float(amount)
    allocation = []
    excess_basic = 0.0
    excess_tds   = 0.0

    if payment_mode == "TDS":
        # Mode 4 — adjust against TDS only (FIFO)
        for m in milestones:
            if remaining <= 0:
                break
            tds_os = float(m["tds_amt"]) - float(m["tds_collected"])
            if tds_os <= 0:
                continue
            applied = min(remaining, tds_os)
            allocation.append({
                "milestone_code": m["milestone_code"],
                "description":    m["description"],
                "billing_doc_no": m["billing_doc_no"],
                "basic_applied":  0.0,
                "cgst_applied":   0.0,
                "sgst_applied":   0.0,
                "tds_applied":    round(applied, 2),
            })
            remaining -= applied
        if remaining > 0:
            excess_tds = round(remaining, 2)

    elif payment_mode == "Credit Note Basic Excess":
        # Mode 7 — adjust basic excess only (FIFO)
        for m in milestones:
            if remaining <= 0:
                break
            basic_os = float(m["basic_amt"]) - float(m["basic_collected"])
            if basic_os <= 0:
                continue
            applied = min(remaining, basic_os)
            allocation.append({
                "milestone_code": m["milestone_code"],
                "description":    m["description"],
                "billing_doc_no": m["billing_doc_no"],
                "basic_applied":  round(applied, 2),
                "cgst_applied":   0.0,
                "sgst_applied":   0.0,
                "tds_applied":    0.0,
            })
            remaining -= applied
        if remaining > 0:
            excess_basic = round(remaining, 2)

    elif payment_mode == "Credit Note TDS Excess":
        # Mode 8 — adjust TDS excess only (FIFO)
        for m in milestones:
            if remaining <= 0:
                break
            tds_os = float(m["tds_amt"]) - float(m["tds_collected"])
            if tds_os <= 0:
                continue
            applied = min(remaining, tds_os)
            allocation.append({
                "milestone_code": m["milestone_code"],
                "description":    m["description"],
                "billing_doc_no": m["billing_doc_no"],
                "basic_applied":  0.0,
                "cgst_applied":   0.0,
                "sgst_applied":   0.0,
                "tds_applied":    round(applied, 2),
            })
            remaining -= applied
        if remaining > 0:
            excess_tds = round(remaining, 2)

    elif payment_mode in _BASIC_GST_MODES:
        # Modes 1,2,3,5,6,9,10 — adjust Basic first, then CGST, then SGST (FIFO)
        for m in milestones:
            if remaining <= 0:
                break
            basic_os = float(m["basic_amt"]) - float(m["basic_collected"])
            cgst_os  = float(m["cgst_amt"])  - float(m["cgst_collected"])
            sgst_os  = float(m["sgst_amt"])  - float(m["sgst_collected"])

            basic_applied = cgst_applied = sgst_applied = 0.0

            if basic_os > 0 and remaining > 0:
                basic_applied = min(remaining, basic_os)
                remaining -= basic_applied
            if cgst_os > 0 and remaining > 0:
                cgst_applied = min(remaining, cgst_os)
                remaining -= cgst_applied
            if sgst_os > 0 and remaining > 0:
                sgst_applied = min(remaining, sgst_os)
                remaining -= sgst_applied

            if basic_applied > 0 or cgst_applied > 0 or sgst_applied > 0:
                allocation.append({
                    "milestone_code": m["milestone_code"],
                    "description":    m["description"],
                    "billing_doc_no": m["billing_doc_no"],
                    "basic_applied":  round(basic_applied, 2),
                    "cgst_applied":   round(cgst_applied, 2),
                    "sgst_applied":   round(sgst_applied, 2),
                    "tds_applied":    0.0,
                })
        if remaining > 0:
            excess_basic = round(remaining, 2)
    else:
        return {"status": "ERROR", "message": f"Unknown payment mode: {payment_mode}"}

    total_applied = round(float(amount) - remaining, 2)
    return {
        "status":        "OK",
        "payment_mode":  payment_mode,
        "amount":        float(amount),
        "total_applied": total_applied,
        "excess_basic":  excess_basic,
        "excess_tds":    excess_tds,
        "allocation":    allocation,
        "posting_ready": len(allocation) > 0,
    }


def park_customer_receipt(
    customer_id: str,
    unit_number: str,
    payment_mode: str,
    amount: float,
    instrument_ref: str,
    instrument_date: str,
    bank_name: str = ""
) -> dict[str, Any]:
    """ZFI_RECEIPT_PARK — Park a receipt and write PARKED record.
    T-code: ZFI_RECEIPT_PARK | Table: customer_receipts, receipt_allocations"""
    # Validate customer/unit
    cust = query_one(
        "SELECT name FROM re_customers WHERE customer_id = %s AND unit_number = %s",
        (customer_id.upper(), unit_number.upper())
    )
    if not cust:
        return {"status": "ERROR", "message": f"Customer {customer_id} / unit {unit_number} not found"}

    # Run allocation logic
    alloc = calculate_receipt_allocation(customer_id, unit_number, payment_mode, amount)
    if alloc["status"] == "ERROR":
        return alloc
    if not alloc["posting_ready"]:
        return {"status": "ERROR", "message": "No outstanding items to allocate against"}

    # Generate park reference
    park_ref = "PRK" + "".join(random.choices(string.digits, k=8))

    # Write receipt header
    execute(
        """
        INSERT INTO customer_receipts
          (park_ref, customer_id, unit_number, payment_mode, amount,
           instrument_ref, instrument_date, bank_name, excess_basic, excess_tds, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PARKED')
        """,
        (
            park_ref, customer_id.upper(), unit_number.upper(),
            payment_mode, float(amount),
            instrument_ref, instrument_date, bank_name,
            alloc["excess_basic"], alloc["excess_tds"]
        )
    )

    # Write allocation lines
    for line in alloc["allocation"]:
        execute(
            """
            INSERT INTO receipt_allocations
              (park_ref, milestone_code, billing_doc_no,
               basic_applied, cgst_applied, sgst_applied, tds_applied)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                park_ref, line["milestone_code"], line.get("billing_doc_no"),
                line["basic_applied"], line["cgst_applied"],
                line["sgst_applied"], line["tds_applied"]
            )
        )

    return {
        "status":         "OK",
        "message":        f"Receipt parked successfully. Reference: {park_ref}",
        "park_reference": park_ref,
        "customer_name":  cust["name"],
        "payment_mode":   payment_mode,
        "amount":         float(amount),
        "allocation":     alloc["allocation"],
        "excess_basic":   alloc["excess_basic"],
        "excess_tds":     alloc["excess_tds"],
        "receipt_status": "PARKED",
        "sap_source": {
            "tcode": "ZFI_RECEIPT_PARK",
            "table": "customer_receipts, receipt_allocations",
            "bapi":  "Z_RE_RECEIPT_PARK"
        }
    }


def post_customer_receipt(park_reference: str) -> dict[str, Any]:
    """ZFI_RECEIPT_POST — Post a parked receipt to FI and update milestone collections.
    T-code: ZFI_RECEIPT_POST | Table: customer_receipts, re_milestones"""
    receipt = query_one(
        "SELECT * FROM customer_receipts WHERE park_ref = %s",
        (park_reference.upper(),)
    )
    if not receipt:
        return {"status": "ERROR", "message": f"Park reference {park_reference} not found"}
    if receipt["status"] != "PARKED":
        return {"status": "ERROR", "message": f"Receipt {park_reference} is already {receipt['status']}"}

    # Generate FI document number
    fi_doc_no = "18" + "".join(random.choices(string.digits, k=10))

    # Fetch allocation lines
    lines = query_all(
        "SELECT * FROM receipt_allocations WHERE park_ref = %s",
        (park_reference.upper(),)
    )

    # Update milestone collections
    for line in lines:
        execute(
            """
            UPDATE re_milestones
            SET basic_collected = basic_collected + %s,
                cgst_collected  = cgst_collected  + %s,
                sgst_collected  = sgst_collected  + %s,
                tds_collected   = tds_collected   + %s,
                status = CASE
                    WHEN (basic_amt - (basic_collected + %s)) <= 0.01
                         AND (cgst_amt - (cgst_collected + %s)) <= 0.01
                         AND (sgst_amt - (sgst_collected + %s)) <= 0.01
                    THEN 'COLLECTED'
                    WHEN (basic_collected + %s) > 0
                    THEN 'PARTIAL'
                    ELSE status
                END
            WHERE customer_id = %s AND unit_number = %s AND milestone_code = %s
            """,
            (
                line["basic_applied"], line["cgst_applied"],
                line["sgst_applied"],  line["tds_applied"],
                line["basic_applied"], line["cgst_applied"],
                line["sgst_applied"],  line["basic_applied"],
                receipt["customer_id"], receipt["unit_number"], line["milestone_code"]
            )
        )

    # Update receipt status to POSTED
    execute(
        """
        UPDATE customer_receipts
        SET status = 'POSTED', fi_doc_no = %s, posted_at = NOW()
        WHERE park_ref = %s
        """,
        (fi_doc_no, park_reference.upper())
    )

    return {
        "status":         "OK",
        "message":        f"Receipt posted successfully. FI Document: {fi_doc_no}",
        "park_reference": park_reference,
        "fi_doc_no":      fi_doc_no,
        "posted_amount":  float(receipt["amount"]),
        "payment_mode":   receipt["payment_mode"],
        "receipt_status": "POSTED",
        "posted_at":      datetime.now().isoformat(),
        "sap_source": {
            "tcode": "ZFI_RECEIPT_POST",
            "table": "customer_receipts, re_milestones",
            "bapi":  "Z_RE_RECEIPT_POST"
        }
    }


def get_receipt_history(customer_id: str, unit_number: str) -> dict[str, Any]:
    """List all receipts (parked and posted) for a customer/unit.
    T-code: ZFI_RECEIPT_PARK | Table: customer_receipts"""
    cust = query_one(
        "SELECT name FROM re_customers WHERE customer_id = %s AND unit_number = %s",
        (customer_id.upper(), unit_number.upper())
    )
    if not cust:
        return {"status": "ERROR", "message": f"Customer {customer_id} / unit {unit_number} not found"}

    rows = query_all(
        """
        SELECT park_ref, payment_mode, amount, instrument_ref, instrument_date,
               bank_name, excess_basic, excess_tds, status, fi_doc_no,
               parked_at, posted_at
        FROM customer_receipts
        WHERE customer_id = %s AND unit_number = %s
        ORDER BY parked_at DESC
        """,
        (customer_id.upper(), unit_number.upper())
    )

    receipts = []
    total_collected = 0.0
    for r in rows:
        if r["status"] == "POSTED":
            total_collected += float(r["amount"])
        receipts.append({
            "park_ref":       r["park_ref"],
            "payment_mode":   r["payment_mode"],
            "amount":         float(r["amount"]),
            "instrument_ref": r["instrument_ref"],
            "instrument_date": str(r["instrument_date"]) if r["instrument_date"] else None,
            "bank_name":      r["bank_name"],
            "excess_basic":   float(r["excess_basic"]),
            "excess_tds":     float(r["excess_tds"]),
            "status":         r["status"],
            "fi_doc_no":      r["fi_doc_no"],
            "parked_at":      r["parked_at"].isoformat() if r["parked_at"] else None,
            "posted_at":      r["posted_at"].isoformat() if r["posted_at"] else None,
        })

    return {
        "status":           "OK",
        "customer_name":    cust["name"],
        "customer_id":      customer_id.upper(),
        "unit_number":      unit_number.upper(),
        "receipts":         receipts,
        "total_receipts":   len(receipts),
        "total_collected":  round(total_collected, 2),
        "sap_source": {
            "tcode": "ZFI_RECEIPT_PARK",
            "table": "customer_receipts",
            "bapi":  "Z_RE_RECEIPT_LIST"
        }
    }


def get_milestone_billing_status(customer_id: str, unit_number: str) -> dict[str, Any]:
    """Milestone-level collection status — raised, collected, outstanding per milestone.
    T-code: VF03 | Table: re_milestones"""
    cust = query_one(
        "SELECT name, project, sale_value FROM re_customers WHERE customer_id = %s AND unit_number = %s",
        (customer_id.upper(), unit_number.upper())
    )
    if not cust:
        return {"status": "ERROR", "message": f"Customer {customer_id} / unit {unit_number} not found"}

    milestones = query_all(
        """
        SELECT milestone_code, description, billing_doc_no,
               basic_amt, cgst_amt, sgst_amt, tds_amt,
               basic_collected, cgst_collected, sgst_collected, tds_collected,
               status, billing_date
        FROM re_milestones
        WHERE customer_id = %s AND unit_number = %s
        ORDER BY milestone_code
        """,
        (customer_id.upper(), unit_number.upper())
    )

    items = []
    total_raised = 0.0
    total_collected = 0.0

    for m in milestones:
        raised = float(m["basic_amt"]) + float(m["cgst_amt"]) + float(m["sgst_amt"])
        collected = float(m["basic_collected"]) + float(m["cgst_collected"]) + float(m["sgst_collected"])
        outstanding = raised - collected
        total_raised += raised
        total_collected += collected

        items.append({
            "milestone_code":  m["milestone_code"],
            "description":     m["description"],
            "billing_doc_no":  m["billing_doc_no"],
            "basic_raised":    float(m["basic_amt"]),
            "cgst_raised":     float(m["cgst_amt"]),
            "sgst_raised":     float(m["sgst_amt"]),
            "basic_collected": float(m["basic_collected"]),
            "cgst_collected":  float(m["cgst_collected"]),
            "sgst_collected":  float(m["sgst_collected"]),
            "outstanding":     round(outstanding, 2),
            "billing_date":    str(m["billing_date"]) if m["billing_date"] else "Not Raised",
            "status":          m["status"],
        })

    return {
        "status":           "OK",
        "customer_name":    cust["name"],
        "project":          cust["project"],
        "unit_number":      unit_number.upper(),
        "milestones":       items,
        "total_raised":     round(total_raised, 2),
        "total_collected":  round(total_collected, 2),
        "total_outstanding": round(total_raised - total_collected, 2),
        "collection_pct":   round((total_collected / total_raised * 100) if total_raised else 0, 2),
        "sap_source": {
            "tcode": "VF03",
            "table": "re_milestones",
            "bapi":  "BAPI_BILLING_GETDETAIL"
        }
    }
