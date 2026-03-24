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
