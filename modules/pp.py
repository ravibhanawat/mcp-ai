"""
SAP PP Module - Production Planning
Simulates BAPI_PRODORD_*, CO_*, CS_* function modules
"""
from db.connection import query_one, query_all, execute
from typing import Any
import random
import string
from datetime import datetime, timedelta


def get_production_order(order_id: str) -> dict[str, Any]:
    """BAPI_PRODORD_GET_DETAIL - Get production order details"""
    po = query_one(
        """
        SELECT po.*, m.description AS material_desc, m.unit,
               wc.name AS work_center_name
        FROM production_orders po
        JOIN materials m ON po.material_id = m.material_id
        LEFT JOIN work_centers wc ON po.work_center_id = wc.wc_id
        WHERE po.order_id = %s
        """,
        (order_id.upper(),)
    )
    if not po:
        return {"status": "ERROR", "message": f"Production Order {order_id} not found"}
    return {
        "status": "OK",
        "order_id": po["order_id"],
        "material_id": po["material_id"],
        "material_desc": po["material_desc"],
        "qty": float(po["qty"]),
        "unit": po["unit"],
        "plant": po["plant"],
        "work_center_id": po["work_center_id"],
        "work_center_name": po["work_center_name"] or "",
        "order_status": po["status"],
        "planned_start": str(po["planned_start"]) if po["planned_start"] else None,
        "planned_end": str(po["planned_end"]) if po["planned_end"] else None,
    }


def get_work_center_capacity(wc_id: str) -> dict[str, Any]:
    """BAPI_WORKCENTER_GET_DETAIL - Get work center details"""
    wc = query_one(
        "SELECT * FROM work_centers WHERE wc_id = %s",
        (wc_id.upper(),)
    )
    if not wc:
        return {"status": "ERROR", "message": f"Work Center {wc_id} not found"}
    active_count_row = query_one(
        "SELECT COUNT(*) AS cnt FROM production_orders WHERE work_center_id = %s AND status IN ('IN_PROGRESS', 'PLANNED')",
        (wc_id.upper(),)
    )
    active_orders = active_count_row["cnt"] if active_count_row else 0
    return {
        "status": "OK",
        "work_center_id": wc["wc_id"],
        "name": wc["name"],
        "plant": wc["plant"],
        "daily_capacity": float(wc["capacity"]),
        "capacity_unit": wc["capacity_unit"],
        "wc_status": wc["status"],
        "active_orders": active_orders,
    }


def get_bill_of_materials(material_id: str) -> dict[str, Any]:
    """CSAP_MAT_BOM_READ - Get Bill of Materials"""
    mat = query_one(
        "SELECT material_id, description FROM materials WHERE material_id = %s",
        (material_id.upper(),)
    )
    if not mat:
        return {"status": "ERROR", "message": f"Material {material_id} not found"}
    components = query_all(
        """
        SELECT b.component_id, m.description AS component_desc, b.qty, b.unit
        FROM bom b
        JOIN materials m ON b.component_id = m.material_id
        WHERE b.parent_material_id = %s
        ORDER BY b.component_id
        """,
        (material_id.upper(),)
    )
    if not components:
        return {"status": "ERROR", "message": f"No BOM found for material {material_id}"}
    return {
        "status": "OK",
        "material_id": material_id,
        "description": mat["description"],
        "components": [
            {
                "component_id": c["component_id"],
                "description": c["component_desc"],
                "qty": float(c["qty"]),
                "unit": c["unit"],
            }
            for c in components
        ],
        "component_count": len(components),
    }


def create_production_order(material_id: str, qty: int, plant: str = "1000", work_center: str = "WC001", start_days: int = 7) -> dict[str, Any]:
    """BAPI_PRODORD_CREATE - Create a production order"""
    mat = query_one(
        "SELECT material_id, description, unit FROM materials WHERE material_id = %s",
        (material_id.upper(),)
    )
    if not mat:
        return {"status": "ERROR", "message": f"Material {material_id} not found"}
    wc = query_one(
        "SELECT wc_id, name, status FROM work_centers WHERE wc_id = %s",
        (work_center.upper(),)
    )
    if not wc:
        return {"status": "ERROR", "message": f"Work Center {work_center} not found"}
    if wc["status"] == "MAINTENANCE":
        return {"status": "ERROR", "message": f"Work Center {work_center} is under maintenance"}

    new_order_id = "PRD" + "".join(random.choices(string.digits, k=6))
    start_date = (datetime.now() + timedelta(days=start_days)).strftime("%Y-%m-%d")
    end_date = (datetime.now() + timedelta(days=start_days + 14)).strftime("%Y-%m-%d")

    execute(
        """
        INSERT INTO production_orders (order_id, material_id, qty, unit, plant, work_center_id, status, planned_start, planned_end)
        VALUES (%s, %s, %s, %s, %s, %s, 'PLANNED', %s, %s)
        """,
        (new_order_id, material_id.upper(), qty, mat["unit"], plant, work_center.upper(), start_date, end_date)
    )
    return {
        "status": "OK",
        "message": "Production order created successfully",
        "order_id": new_order_id,
        "material": mat["description"],
        "qty": qty,
        "unit": mat["unit"],
        "plant": plant,
        "work_center_name": wc["name"],
        "planned_start": start_date,
        "planned_end": end_date,
    }


def list_production_orders(status: str = None) -> dict[str, Any]:
    """CO40 - List production orders"""
    if status:
        rows = query_all(
            """
            SELECT po.order_id, m.description AS material, po.qty, wc.name AS work_center,
                   po.status, po.planned_start, po.planned_end
            FROM production_orders po
            JOIN materials m ON po.material_id = m.material_id
            LEFT JOIN work_centers wc ON po.work_center_id = wc.wc_id
            WHERE UPPER(po.status) = %s
            ORDER BY po.planned_start
            """,
            (status.upper(),)
        )
    else:
        rows = query_all(
            """
            SELECT po.order_id, m.description AS material, po.qty, wc.name AS work_center,
                   po.status, po.planned_start, po.planned_end
            FROM production_orders po
            JOIN materials m ON po.material_id = m.material_id
            LEFT JOIN work_centers wc ON po.work_center_id = wc.wc_id
            ORDER BY po.planned_start
            """
        )
    results = [
        {
            **r,
            "planned_start": str(r["planned_start"]) if r["planned_start"] else None,
            "planned_end": str(r["planned_end"]) if r["planned_end"] else None,
        }
        for r in rows
    ]
    return {"status": "OK", "orders": results, "count": len(results)}


def get_capacity_utilization() -> dict[str, Any]:
    """CM50 - Capacity utilization overview"""
    rows = query_all(
        """
        SELECT wc.wc_id, wc.name, wc.plant, wc.status,
               COUNT(po.order_id) AS active_production_orders
        FROM work_centers wc
        LEFT JOIN production_orders po ON wc.wc_id = po.work_center_id AND po.status = 'IN_PROGRESS'
        GROUP BY wc.wc_id, wc.name, wc.plant, wc.status
        ORDER BY wc.wc_id
        """
    )
    return {"status": "OK", "work_centers": rows}
