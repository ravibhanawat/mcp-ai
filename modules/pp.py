"""
SAP PP Module - Production Planning
Simulates BAPI_PRODORD_*, CO_*, CS_* function modules
"""
from mock_data.sap_data import PRODUCTION_ORDERS, WORK_CENTERS, BOM, MATERIALS
from typing import Any
import random
import string
from datetime import datetime, timedelta


def get_production_order(order_id: str) -> dict[str, Any]:
    """BAPI_PRODORD_GET_DETAIL - Get production order details"""
    po = PRODUCTION_ORDERS.get(order_id.upper())
    if not po:
        return {"status": "ERROR", "message": f"Production Order {order_id} not found"}
    mat = MATERIALS.get(po["material"], {})
    wc = WORK_CENTERS.get(po["work_center"], {})
    return {
        "status": "OK",
        "order_id": order_id,
        "material_desc": mat.get("desc", ""),
        "material_id": po["material"],
        "qty": po["qty"],
        "unit": mat.get("unit", "EA"),
        "plant": po["plant"],
        "work_center": po["work_center"],
        "work_center_name": wc.get("name", ""),
        "order_status": po["status"],
        "planned_start": po["start"],
        "planned_end": po["end"]
    }


def get_work_center_capacity(wc_id: str) -> dict[str, Any]:
    """BAPI_WORKCENTER_GET_DETAIL - Get work center details"""
    wc = WORK_CENTERS.get(wc_id.upper())
    if not wc:
        return {"status": "ERROR", "message": f"Work Center {wc_id} not found"}
    # Count active orders at this work center
    active_orders = [o for o in PRODUCTION_ORDERS.values()
                     if o["work_center"] == wc_id.upper() and o["status"] in ("IN_PROGRESS", "PLANNED")]
    return {
        "status": "OK",
        "work_center_id": wc_id,
        "name": wc["name"],
        "plant": wc["plant"],
        "daily_capacity": wc["capacity"],
        "capacity_unit": wc["unit"],
        "wc_status": wc["status"],
        "active_orders": len(active_orders)
    }


def get_bill_of_materials(material_id: str) -> dict[str, Any]:
    """CSAP_MAT_BOM_READ - Get Bill of Materials"""
    mat = MATERIALS.get(material_id.upper())
    if not mat:
        return {"status": "ERROR", "message": f"Material {material_id} not found"}
    bom = BOM.get(material_id.upper())
    if not bom:
        return {"status": "ERROR", "message": f"No BOM found for material {material_id}"}
    return {
        "status": "OK",
        "material_id": material_id,
        "description": mat["desc"],
        "components": bom,
        "component_count": len(bom)
    }


def create_production_order(material_id: str, qty: int, plant: str = "1000", work_center: str = "WC001", start_days: int = 7) -> dict[str, Any]:
    """BAPI_PRODORD_CREATE - Create a production order"""
    if material_id.upper() not in MATERIALS:
        return {"status": "ERROR", "message": f"Material {material_id} not found"}
    if work_center.upper() not in WORK_CENTERS:
        return {"status": "ERROR", "message": f"Work Center {work_center} not found"}
    wc = WORK_CENTERS[work_center.upper()]
    if wc["status"] == "MAINTENANCE":
        return {"status": "ERROR", "message": f"Work Center {work_center} is under maintenance"}
    mat = MATERIALS[material_id.upper()]
    new_order_id = "PRD" + "".join(random.choices(string.digits, k=4))
    start_date = (datetime.now() + timedelta(days=start_days)).strftime("%Y-%m-%d")
    end_date = (datetime.now() + timedelta(days=start_days + 14)).strftime("%Y-%m-%d")
    PRODUCTION_ORDERS[new_order_id] = {
        "material": material_id.upper(),
        "qty": qty,
        "plant": plant,
        "work_center": work_center.upper(),
        "status": "PLANNED",
        "start": start_date,
        "end": end_date
    }
    return {
        "status": "OK",
        "message": "Production order created successfully",
        "order_id": new_order_id,
        "material": mat["desc"],
        "qty": qty,
        "unit": mat["unit"],
        "plant": plant,
        "work_center_name": wc["name"],
        "planned_start": start_date,
        "planned_end": end_date
    }


def list_production_orders(status: str = None) -> dict[str, Any]:
    """CO40 - List production orders"""
    results = []
    for ord_id, po in PRODUCTION_ORDERS.items():
        if status is None or po["status"].upper() == status.upper():
            mat = MATERIALS.get(po["material"], {})
            wc = WORK_CENTERS.get(po["work_center"], {})
            results.append({
                "order_id": ord_id,
                "material": mat.get("desc", ""),
                "qty": po["qty"],
                "work_center": wc.get("name", ""),
                "status": po["status"],
                "start": po["start"],
                "end": po["end"]
            })
    return {"status": "OK", "orders": results, "count": len(results)}


def get_capacity_utilization() -> dict[str, Any]:
    """CM50 - Capacity utilization overview"""
    utilization = []
    for wc_id, wc in WORK_CENTERS.items():
        active = sum(1 for o in PRODUCTION_ORDERS.values()
                     if o["work_center"] == wc_id and o["status"] == "IN_PROGRESS")
        utilization.append({
            "work_center_id": wc_id,
            "name": wc["name"],
            "plant": wc["plant"],
            "status": wc["status"],
            "active_production_orders": active
        })
    return {"status": "OK", "work_centers": utilization}
