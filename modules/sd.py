"""
SAP SD Module - Sales & Distribution
Simulates BAPI_SALESORDER_*, BAPI_DELIVERY_*, VA*, VL* function modules
"""
from db.connection import query_one, query_all, execute
from typing import Any
import random
import string
from datetime import datetime, timedelta


def get_customer_info(customer_id: str) -> dict[str, Any]:
    """BAPI_CUSTOMER_GETDETAIL - Get customer master data"""
    cust = query_one(
        "SELECT * FROM customers WHERE customer_id = %s",
        (customer_id.upper(),)
    )
    if not cust:
        return {"status": "ERROR", "message": f"Customer {customer_id} not found"}
    cust.pop("created_at", None)
    return {"status": "OK", **cust}


def get_sales_order(order_id: str) -> dict[str, Any]:
    """BAPI_SALESORDER_GETDETAILSOFITEMS - Get sales order details"""
    so = query_one(
        """
        SELECT so.*, c.name AS customer_name, m.description AS material_desc
        FROM sales_orders so
        JOIN customers c ON so.customer_id = c.customer_id
        JOIN materials m ON so.material_id = m.material_id
        WHERE so.order_id = %s
        """,
        (order_id.upper(),)
    )
    if not so:
        return {"status": "ERROR", "message": f"Sales Order {order_id} not found"}
    total_value = float(so["qty"]) * float(so["price"])
    return {
        "status": "OK",
        "order_id": so["order_id"],
        "customer_name": so["customer_name"],
        "material_desc": so["material_desc"],
        "qty": float(so["qty"]),
        "unit_price": float(so["price"]),
        "total_value": total_value,
        "currency": so["currency"],
        "delivery_date": str(so["delivery_date"]),
        "order_status": so["status"],
        "plant": so["plant"],
    }


def get_customer_orders(customer_id: str) -> dict[str, Any]:
    """VA05 - List all orders for a customer"""
    cust = query_one(
        "SELECT name FROM customers WHERE customer_id = %s",
        (customer_id.upper(),)
    )
    if not cust:
        return {"status": "ERROR", "message": f"Customer {customer_id} not found"}
    rows = query_all(
        """
        SELECT so.order_id, m.description AS material, so.qty, so.price,
               so.status, so.delivery_date
        FROM sales_orders so
        JOIN materials m ON so.material_id = m.material_id
        WHERE so.customer_id = %s
        ORDER BY so.created_at DESC
        """,
        (customer_id.upper(),)
    )
    total_value = sum(float(r["qty"]) * float(r["price"]) for r in rows)
    orders = [
        {
            "order_id": r["order_id"],
            "material": r["material"],
            "qty": float(r["qty"]),
            "value": float(r["qty"]) * float(r["price"]),
            "status": r["status"],
            "delivery_date": str(r["delivery_date"]),
        }
        for r in rows
    ]
    return {
        "status": "OK",
        "customer_name": cust["name"],
        "orders": orders,
        "total_orders": len(orders),
        "total_value": total_value,
        "currency": "INR",
    }


def create_sales_order(customer_id: str, material_id: str, qty: int, delivery_days: int = 14) -> dict[str, Any]:
    """BAPI_SALESORDER_CREATEFROMDAT2 - Create a new sales order"""
    cust = query_one(
        "SELECT customer_id, name FROM customers WHERE customer_id = %s AND status = 'ACTIVE'",
        (customer_id.upper(),)
    )
    if not cust:
        return {"status": "ERROR", "message": f"Customer {customer_id} not found or inactive"}
    mat = query_one(
        "SELECT material_id, description, price, currency FROM materials WHERE material_id = %s",
        (material_id.upper(),)
    )
    if not mat:
        return {"status": "ERROR", "message": f"Material {material_id} not found"}

    new_so_id = "SO" + "".join(random.choices(string.digits, k=6))
    delivery_date = (datetime.now() + timedelta(days=delivery_days)).strftime("%Y-%m-%d")
    price = float(mat["price"])
    total_value = qty * price

    execute(
        """
        INSERT INTO sales_orders (order_id, customer_id, material_id, qty, price, currency, status, delivery_date)
        VALUES (%s, %s, %s, %s, %s, %s, 'OPEN', %s)
        """,
        (new_so_id, customer_id.upper(), material_id.upper(), qty, price, mat["currency"], delivery_date)
    )
    return {
        "status": "OK",
        "message": "Sales order created successfully",
        "order_id": new_so_id,
        "customer": cust["name"],
        "material": mat["description"],
        "qty": qty,
        "unit_price": price,
        "total_value": total_value,
        "currency": mat["currency"],
        "delivery_date": delivery_date,
    }


def get_delivery_status(delivery_id: str) -> dict[str, Any]:
    """BAPI_DELIVERY_GETLIST - Get delivery status"""
    deliv = query_one(
        """
        SELECT d.*, c.name AS customer_name
        FROM deliveries d
        JOIN sales_orders so ON d.sales_order_id = so.order_id
        JOIN customers c ON so.customer_id = c.customer_id
        WHERE d.delivery_id = %s
        """,
        (delivery_id.upper(),)
    )
    if not deliv:
        return {"status": "ERROR", "message": f"Delivery {delivery_id} not found"}
    return {
        "status": "OK",
        "delivery_id": deliv["delivery_id"],
        "customer_name": deliv["customer_name"],
        "delivery_status": deliv["status"],
        "ship_date": str(deliv["ship_date"]) if deliv["ship_date"] else None,
        "carrier": deliv["carrier"],
        "tracking_no": deliv["tracking_no"],
        "sales_order": deliv["sales_order_id"],
    }


def list_open_sales_orders() -> dict[str, Any]:
    """VA05 - All open sales orders"""
    rows = query_all(
        """
        SELECT so.order_id, c.name AS customer, m.description AS material,
               so.qty, so.status, so.delivery_date
        FROM sales_orders so
        JOIN customers c ON so.customer_id = c.customer_id
        JOIN materials m ON so.material_id = m.material_id
        WHERE so.status IN ('OPEN', 'IN_PROGRESS')
        ORDER BY so.delivery_date
        """
    )
    results = [
        {**r, "delivery_date": str(r["delivery_date"])} for r in rows
    ]
    return {"status": "OK", "open_orders": results, "count": len(results)}


# ─── Real Estate — Alembic Parivartan Project ─────────────────────────────────

def get_sales_deed_data(customer_id: str, unit_number: str) -> dict[str, Any]:
    """ZSD_PRINT / WFRICE Smartform — Assemble Sales Deed data (SD01E).
    T-code: ZSD_PRINT | Tables: VBAK, KNA1, re_customers, re_milestones"""
    cust = query_one(
        "SELECT * FROM re_customers WHERE customer_id = %s AND unit_number = %s",
        (customer_id.upper(), unit_number.upper())
    )
    if not cust:
        return {"status": "ERROR", "message": f"Customer {customer_id} / unit {unit_number} not found in RE master"}

    milestones = query_all(
        """
        SELECT milestone_code, description, basic_amt, cgst_amt, sgst_amt,
               basic_collected, cgst_collected, sgst_collected, billing_date, status
        FROM re_milestones
        WHERE customer_id = %s AND unit_number = %s
        ORDER BY milestone_code
        """,
        (customer_id.upper(), unit_number.upper())
    )

    total_sale_value = float(cust["sale_value"]) if cust["sale_value"] else 0.0
    total_gst = sum(float(m["cgst_amt"]) + float(m["sgst_amt"]) for m in milestones)
    total_collected = sum(
        float(m["basic_collected"]) + float(m["cgst_collected"]) + float(m["sgst_collected"])
        for m in milestones
    )

    payment_schedule = [
        {
            "milestone":      m["milestone_code"],
            "description":    m["description"],
            "basic_amt":      float(m["basic_amt"]),
            "cgst_amt":       float(m["cgst_amt"]),
            "sgst_amt":       float(m["sgst_amt"]),
            "total_amt":      float(m["basic_amt"]) + float(m["cgst_amt"]) + float(m["sgst_amt"]),
            "collected":      float(m["basic_collected"]) + float(m["cgst_collected"]) + float(m["sgst_collected"]),
            "billing_date":   str(m["billing_date"]) if m["billing_date"] else "TBD",
            "status":         m["status"],
        }
        for m in milestones
    ]

    return {
        "status": "OK",
        "document_type": "Sales Deed",
        "t_code": "ZSD_PRINT",
        "smartform": "WFRICE_SALES_DEED",
        "customer": {
            "customer_id":   cust["customer_id"],
            "name":          cust["name"],
            "pan":           cust["pan_number"],
            "aadhaar":       cust["aadhaar"],
            "dob":           str(cust["dob"]) if cust["dob"] else None,
            "phone":         cust["phone"],
            "email":         cust["email"],
            "address":       cust["address"],
            "city":          cust["city"],
            "state":         cust["state"],
            "co_applicant":  cust["co_applicant"],
        },
        "unit": {
            "project":       cust["project"],
            "unit_number":   cust["unit_number"],
            "tower":         cust["tower"],
            "floor":         cust["floor"],
            "area_sqft":     float(cust["area_sqft"]) if cust["area_sqft"] else None,
            "area_sqm":      float(cust["area_sqm"]) if cust["area_sqm"] else None,
        },
        "financial": {
            "sale_value":     total_sale_value,
            "total_gst":      round(total_gst, 2),
            "total_payable":  round(total_sale_value + total_gst, 2),
            "total_collected": round(total_collected, 2),
            "balance":        round(total_sale_value + total_gst - total_collected, 2),
            "booking_date":   str(cust["booking_date"]) if cust["booking_date"] else None,
        },
        "payment_schedule": payment_schedule,
        "sap_source": {
            "tcode": "ZSD_PRINT",
            "table": "re_customers, re_milestones",
            "bapi":  "Z_SD_PRINT_WFRICE"
        }
    }


def get_allotment_letter_data(customer_id: str, unit_number: str, project_code: str) -> dict[str, Any]:
    """ZSD_PRINT — Allotment Letter data for Cloud Forest (SD01J) or Park Crescent (SD01K).
    T-code: ZSD_PRINT | project_code: CLOUD_FOREST | PARK_CRESCENT"""
    valid_projects = {"CLOUD_FOREST", "PARK_CRESCENT"}
    if project_code.upper() not in valid_projects:
        return {"status": "ERROR", "message": f"Invalid project_code. Use: CLOUD_FOREST or PARK_CRESCENT"}

    cust = query_one(
        "SELECT * FROM re_customers WHERE customer_id = %s AND unit_number = %s AND project = %s",
        (customer_id.upper(), unit_number.upper(), project_code.upper())
    )
    if not cust:
        return {
            "status": "ERROR",
            "message": f"Customer {customer_id} / unit {unit_number} not found in project {project_code}"
        }

    milestones = query_all(
        """
        SELECT milestone_code, description, basic_amt, cgst_amt, sgst_amt, billing_date, status
        FROM re_milestones
        WHERE customer_id = %s AND unit_number = %s
        ORDER BY milestone_code
        """,
        (customer_id.upper(), unit_number.upper())
    )

    # Booking amount = M01
    booking_entry = next((m for m in milestones if m["milestone_code"] == "M01"), None)
    booking_amount = float(booking_entry["basic_amt"]) if booking_entry else 0.0

    smartform = "WFRICE_ALLOT_CF" if project_code.upper() == "CLOUD_FOREST" else "WFRICE_ALLOT_PC"
    fsd_ref   = "SD01J" if project_code.upper() == "CLOUD_FOREST" else "SD01K"

    return {
        "status": "OK",
        "document_type": f"Allotment Letter — {project_code.replace('_', ' ').title()}",
        "fsd_reference": fsd_ref,
        "t_code": "ZSD_PRINT",
        "smartform": smartform,
        "customer": {
            "customer_id":  cust["customer_id"],
            "name":         cust["name"],
            "pan":          cust["pan_number"],
            "phone":        cust["phone"],
            "address":      cust["address"],
            "city":         cust["city"],
            "state":        cust["state"],
            "co_applicant": cust["co_applicant"],
        },
        "unit": {
            "project":     cust["project"],
            "unit_number": cust["unit_number"],
            "tower":       cust["tower"],
            "floor":       cust["floor"],
            "area_sqft":   float(cust["area_sqft"]) if cust["area_sqft"] else None,
            "area_sqm":    float(cust["area_sqm"]) if cust["area_sqm"] else None,
        },
        "financial": {
            "sale_value":    float(cust["sale_value"]) if cust["sale_value"] else 0.0,
            "booking_amount": booking_amount,
            "booking_date":  str(cust["booking_date"]) if cust["booking_date"] else None,
        },
        "payment_schedule": [
            {
                "milestone":    m["milestone_code"],
                "description":  m["description"],
                "basic_amt":    float(m["basic_amt"]),
                "cgst_amt":     float(m["cgst_amt"]),
                "sgst_amt":     float(m["sgst_amt"]),
                "billing_date": str(m["billing_date"]) if m["billing_date"] else "TBD",
                "status":       m["status"],
            }
            for m in milestones
        ],
        "sap_source": {
            "tcode": "ZSD_PRINT",
            "table": "re_customers, re_milestones",
            "bapi":  "Z_SD_PRINT_ALLOTMENT"
        }
    }


def validate_einvoice_b2b(billing_doc_no: str) -> dict[str, Any]:
    """E-Invoice validation for B2B customers at VF01 (SD01F).
    Logic: check gst_number in re_customers (STCD3 equivalent).
    T-code: VF01 | Tables: re_customers, KNA1, J_1IGINVREFNUM"""
    # In demo mode we check re_customers.gst_number (maps to KNA1.STCD3)
    # Real SAP: pass VBELN → VBRK.KUNAG → KNA1.STCD3 → J_1IGINVREFNUM
    cust = query_one(
        """
        SELECT rc.customer_id, rc.name, rc.gst_number
        FROM re_customers rc
        JOIN re_milestones rm ON rc.customer_id = rm.customer_id
        WHERE rm.billing_doc_no = %s
        LIMIT 1
        """,
        (billing_doc_no,)
    )
    if not cust:
        return {
            "status": "ERROR",
            "message": f"Billing document {billing_doc_no} not found in RE milestones"
        }

    is_b2b = bool(cust["gst_number"])

    if not is_b2b:
        return {
            "status":            "OK",
            "billing_doc_no":    billing_doc_no,
            "customer_id":       cust["customer_id"],
            "customer_name":     cust["name"],
            "is_b2b":            False,
            "validation_status": "B2C_EXEMPT",
            "message":           "B2C customer — e-Invoice not required (STCD3 is blank)",
            "sap_source": {
                "tcode": "VF01",
                "table": "re_customers / KNA1, J_1IGINVREFNUM",
                "bapi":  "Z_EINV_VALIDATE"
            }
        }

    # B2B customer — simulate IRN lookup in J_1IGINVREFNUM
    # In real SAP: SELECT DOCNO FROM J_1IGINVREFNUM WHERE VBELN = billing_doc_no
    # Demo: billing docs starting with 90000 have IRN if doc ends in even digit
    last_digit = billing_doc_no[-1] if billing_doc_no else "0"
    irn_found = last_digit in "02468"
    irn = ("f11b236a8e9c3d45" + billing_doc_no[-6:] + "f3d1") if irn_found else None

    return {
        "status":            "OK",
        "billing_doc_no":    billing_doc_no,
        "customer_id":       cust["customer_id"],
        "customer_name":     cust["name"],
        "gstin":             cust["gst_number"],
        "is_b2b":            True,
        "irn_found":         irn_found,
        "irn":               irn,
        "validation_status": "VALID" if irn_found else "MISSING_IRN",
        "message": (
            f"B2B customer — e-Invoice IRN found: {irn}" if irn_found
            else "B2B customer — e-Invoice NOT generated. Please run e-Invoice generation before printing output."
        ),
        "sap_source": {
            "tcode": "VF01",
            "table": "re_customers / KNA1, J_1IGINVREFNUM",
            "bapi":  "Z_EINV_VALIDATE"
        }
    }


def get_broker_payout_status(broker_id: str) -> dict[str, Any]:
    """Broker payout eligibility check (SD01G).
    Rule: collected_pct >= 20% required; 100% payout only.
    T-code: ZSD_BROKER | Tables: re_brokers, re_broker_bookings"""
    broker = query_one(
        "SELECT * FROM re_brokers WHERE broker_id = %s",
        (broker_id.upper(),)
    )
    if not broker:
        return {"status": "ERROR", "message": f"Broker {broker_id} not found"}

    bookings = query_all(
        """
        SELECT rbb.*, rc.name AS customer_name
        FROM re_broker_bookings rbb
        JOIN re_customers rc ON rbb.customer_id = rc.customer_id
        WHERE rbb.broker_id = %s
        ORDER BY rbb.tagged_date
        """,
        (broker_id.upper(),)
    )

    booking_list = []
    total_eligible = 0.0

    for b in bookings:
        collected_pct = float(b["collected_pct"])
        payout_eligible = collected_pct >= 20.0 and b["po_status"] == "NOT_CREATED"
        payout_amount = float(b["payout_amount"]) if b["payout_amount"] else 0.0

        if payout_eligible:
            total_eligible += payout_amount

        booking_list.append({
            "customer_id":      b["customer_id"],
            "customer_name":    b["customer_name"],
            "unit_number":      b["unit_number"],
            "sale_value":       float(b["sale_value"]),
            "payout_amount":    payout_amount,
            "collected_pct":    collected_pct,
            "payout_eligible":  payout_eligible,
            "eligibility_reason": (
                "Eligible — collection >= 20%"  if payout_eligible and collected_pct >= 20
                else "Not Eligible — collection < 20%"  if collected_pct < 20
                else f"PO already {b['po_status']}"
            ),
            "po_status":        b["po_status"],
            "miro_status":      b["miro_status"],
            "tagged_date":      str(b["tagged_date"]) if b["tagged_date"] else None,
        })

    return {
        "status":                "OK",
        "broker_id":             broker["broker_id"],
        "broker_name":           broker["name"],
        "payout_pct":            float(broker["payout_pct"]),
        "pan":                   broker["pan"],
        "gstin":                 broker["gstin"],
        "total_bookings":        len(booking_list),
        "total_eligible_payout": round(total_eligible, 2),
        "bookings":              booking_list,
        "sap_source": {
            "tcode": "ZSD_BROKER",
            "table": "re_brokers, re_broker_bookings",
            "bapi":  "Z_SD_BROKER_PAYOUT"
        }
    }


def initiate_broker_po(broker_id: str, unit_number: str) -> dict[str, Any]:
    """Create broker payout PO — validates 20% collection threshold first (SD01G).
    T-code: ME21N | Table: re_broker_bookings, EKKO"""
    booking = query_one(
        """
        SELECT rbb.*, rb.name AS broker_name, rc.name AS customer_name
        FROM re_broker_bookings rbb
        JOIN re_brokers rb ON rbb.broker_id = rb.broker_id
        JOIN re_customers rc ON rbb.customer_id = rc.customer_id
        WHERE rbb.broker_id = %s AND rbb.unit_number = %s
        """,
        (broker_id.upper(), unit_number.upper())
    )
    if not booking:
        return {"status": "ERROR", "message": f"Booking not found for broker {broker_id} / unit {unit_number}"}

    if float(booking["collected_pct"]) < 20.0:
        return {
            "status": "ERROR",
            "message": (
                f"Cannot initiate PO — only {booking['collected_pct']}% collected. "
                f"Minimum 20% required. Collect at least "
                f"₹{round(float(booking['sale_value']) * 0.20 - float(booking['sale_value']) * float(booking['collected_pct']) / 100, 0):,.0f} more."
            )
        }

    if booking["po_status"] != "NOT_CREATED":
        return {"status": "ERROR", "message": f"PO already {booking['po_status']} for this booking"}

    po_number = "45" + "".join(__import__("random").choices(__import__("string").digits, k=8))
    execute(
        "UPDATE re_broker_bookings SET po_number = %s, po_status = 'CREATED' WHERE broker_id = %s AND unit_number = %s",
        (po_number, broker_id.upper(), unit_number.upper())
    )

    return {
        "status":          "OK",
        "message":         f"Broker PO {po_number} created. Pending Level-1 release by Finance Manager.",
        "po_number":       po_number,
        "broker_name":     booking["broker_name"],
        "customer_name":   booking["customer_name"],
        "unit_number":     unit_number.upper(),
        "payout_amount":   float(booking["payout_amount"]) if booking["payout_amount"] else 0.0,
        "po_status":       "CREATED",
        "release_levels":  2,
        "next_approver":   "Finance Manager (Level-1 Release)",
        "note":            "100% payout — no partial payment allowed. Release both levels before MIRO.",
        "sap_source": {
            "tcode": "ME21N",
            "table": "re_broker_bookings, EKKO",
            "bapi":  "BAPI_PO_CREATE1"
        }
    }
