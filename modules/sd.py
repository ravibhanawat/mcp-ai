"""
SAP SD Module - Sales & Distribution
Simulates BAPI_SALESORDER_*, BAPI_DELIVERY_*, VA*, VL* function modules
"""
from mock_data.sap_data import CUSTOMERS, SALES_ORDERS, DELIVERIES, MATERIALS
from typing import Any
import random
import string
from datetime import datetime, timedelta


def get_customer_info(customer_id: str) -> dict[str, Any]:
    """BAPI_CUSTOMER_GETDETAIL - Get customer master data"""
    cust = CUSTOMERS.get(customer_id.upper())
    if not cust:
        return {"status": "ERROR", "message": f"Customer {customer_id} not found"}
    return {"status": "OK", "customer_id": customer_id, **cust}


def get_sales_order(order_id: str) -> dict[str, Any]:
    """BAPI_SALESORDER_GETDETAILSOFITEMS - Get sales order details"""
    so = SALES_ORDERS.get(order_id.upper())
    if not so:
        return {"status": "ERROR", "message": f"Sales Order {order_id} not found"}
    cust = CUSTOMERS.get(so["customer"], {})
    mat = MATERIALS.get(so["material"], {})
    total_value = so["qty"] * so["price"]
    return {
        "status": "OK",
        "order_id": order_id,
        "customer_name": cust.get("name", ""),
        "material_desc": mat.get("desc", ""),
        "qty": so["qty"],
        "unit_price": so["price"],
        "total_value": total_value,
        "currency": "INR",
        "delivery_date": so["delivery_date"],
        "order_status": so["status"]
    }


def get_customer_orders(customer_id: str) -> dict[str, Any]:
    """VA05 - List all orders for a customer"""
    cust = CUSTOMERS.get(customer_id.upper())
    if not cust:
        return {"status": "ERROR", "message": f"Customer {customer_id} not found"}
    orders = []
    total_value = 0
    for so_id, so in SALES_ORDERS.items():
        if so["customer"] == customer_id.upper():
            mat = MATERIALS.get(so["material"], {})
            val = so["qty"] * so["price"]
            total_value += val
            orders.append({
                "order_id": so_id,
                "material": mat.get("desc", ""),
                "qty": so["qty"],
                "value": val,
                "status": so["status"],
                "delivery_date": so["delivery_date"]
            })
    return {
        "status": "OK",
        "customer_name": cust["name"],
        "orders": orders,
        "total_orders": len(orders),
        "total_value": total_value,
        "currency": "INR"
    }


def create_sales_order(customer_id: str, material_id: str, qty: int, delivery_days: int = 14) -> dict[str, Any]:
    """BAPI_SALESORDER_CREATEFROMDAT2 - Create a new sales order"""
    if customer_id.upper() not in CUSTOMERS:
        return {"status": "ERROR", "message": f"Customer {customer_id} not found"}
    if material_id.upper() not in MATERIALS:
        return {"status": "ERROR", "message": f"Material {material_id} not found"}
    mat = MATERIALS[material_id.upper()]
    cust = CUSTOMERS[customer_id.upper()]
    new_so_id = "SO" + "".join(random.choices(string.digits, k=4))
    delivery_date = (datetime.now() + timedelta(days=delivery_days)).strftime("%Y-%m-%d")
    total_value = qty * mat["price"]
    # Add to mock data
    SALES_ORDERS[new_so_id] = {
        "customer": customer_id.upper(),
        "material": material_id.upper(),
        "qty": qty,
        "price": mat["price"],
        "status": "OPEN",
        "delivery_date": delivery_date
    }
    return {
        "status": "OK",
        "message": "Sales order created successfully",
        "order_id": new_so_id,
        "customer": cust["name"],
        "material": mat["desc"],
        "qty": qty,
        "unit_price": mat["price"],
        "total_value": total_value,
        "currency": mat["currency"],
        "delivery_date": delivery_date
    }


def get_delivery_status(delivery_id: str) -> dict[str, Any]:
    """BAPI_DELIVERY_GETLIST - Get delivery status"""
    deliv = DELIVERIES.get(delivery_id.upper())
    if not deliv:
        return {"status": "ERROR", "message": f"Delivery {delivery_id} not found"}
    so = SALES_ORDERS.get(deliv["sales_order"], {})
    cust = CUSTOMERS.get(so.get("customer", ""), {})
    return {
        "status": "OK",
        "delivery_id": delivery_id,
        "customer_name": cust.get("name", ""),
        "delivery_status": deliv["status"],
        "ship_date": deliv["ship_date"],
        "carrier": deliv["carrier"],
        "sales_order": deliv["sales_order"]
    }


def list_open_sales_orders() -> dict[str, Any]:
    """VA05 - All open sales orders"""
    results = []
    for so_id, so in SALES_ORDERS.items():
        if so["status"] in ("OPEN", "IN_PROGRESS"):
            cust = CUSTOMERS.get(so["customer"], {})
            mat = MATERIALS.get(so["material"], {})
            results.append({
                "order_id": so_id,
                "customer": cust.get("name", ""),
                "material": mat.get("desc", ""),
                "qty": so["qty"],
                "status": so["status"],
                "delivery_date": so["delivery_date"]
            })
    return {"status": "OK", "open_orders": results, "count": len(results)}
