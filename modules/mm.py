"""
SAP MM Module - Materials Management
Simulates BAPI_MATERIAL_*, BAPI_PO_*, MB_*, ME_* function modules
"""
from db.connection import query_one, query_all
from typing import Any


def get_material_info(material_id: str) -> dict[str, Any]:
    """BAPI_MATERIAL_GET_DETAIL - Get material master data"""
    mat = query_one(
        "SELECT * FROM materials WHERE material_id = %s",
        (material_id.upper(),)
    )
    if not mat:
        return {"status": "ERROR", "message": f"Material {material_id} not found"}
    mat.pop("created_at", None)
    return {"status": "OK", **mat}


def get_stock_level(material_id: str, plant: str = None) -> dict[str, Any]:
    """BAPI_MATERIAL_STOCK_REQ_LIST - Get stock levels"""
    if plant:
        row = query_one(
            """
            SELECT s.*, m.description, m.unit, p.name AS plant_name
            FROM stock s
            JOIN materials m ON s.material_id = m.material_id
            JOIN plants p ON s.plant = p.plant_id
            WHERE s.material_id = %s AND s.plant = %s
            """,
            (material_id.upper(), plant)
        )
    else:
        row = query_one(
            """
            SELECT s.*, m.description, m.unit, p.name AS plant_name
            FROM stock s
            JOIN materials m ON s.material_id = m.material_id
            JOIN plants p ON s.plant = p.plant_id
            WHERE s.material_id = %s
            LIMIT 1
            """,
            (material_id.upper(),)
        )
    if not row:
        return {"status": "ERROR", "message": f"No stock data found for material {material_id}"}
    available = float(row["unrestricted"]) - float(row["reserved"])
    return {
        "status": "OK",
        "material_id": row["material_id"],
        "description": row["description"],
        "plant": row["plant"],
        "plant_name": row["plant_name"],
        "unrestricted": float(row["unrestricted"]),
        "reserved": float(row["reserved"]),
        "in_transit": float(row["in_transit"]),
        "reorder_point": float(row["reorder_point"]),
        "available_to_promise": available,
        "unit": row["unit"],
    }


def get_purchase_order(po_id: str) -> dict[str, Any]:
    """BAPI_PO_GETDETAIL - Get purchase order details"""
    po = query_one(
        """
        SELECT po.*, v.name AS vendor_name, m.description AS material_desc, m.currency
        FROM purchase_orders po
        JOIN vendors v ON po.vendor_id = v.vendor_id
        JOIN materials m ON po.material_id = m.material_id
        WHERE po.po_id = %s
        """,
        (po_id.upper(),)
    )
    if not po:
        return {"status": "ERROR", "message": f"PO {po_id} not found"}
    total_value = float(po["qty"]) * float(po["price"])
    return {
        "status": "OK",
        "po_id": po["po_id"],
        "vendor_name": po["vendor_name"],
        "material_desc": po["material_desc"],
        "qty": float(po["qty"]),
        "unit": po["unit"],
        "unit_price": float(po["price"]),
        "total_value": total_value,
        "delivery_date": str(po["delivery_date"]),
        "po_status": po["status"],
        "currency": po["currency"],
        "plant": po["plant"],
    }


def list_open_purchase_orders() -> dict[str, Any]:
    """ME2M - List all open purchase orders"""
    rows = query_all(
        """
        SELECT po.po_id, v.name AS vendor, m.description AS material,
               po.qty, po.status, po.delivery_date
        FROM purchase_orders po
        JOIN vendors v ON po.vendor_id = v.vendor_id
        JOIN materials m ON po.material_id = m.material_id
        WHERE po.status IN ('OPEN', 'PARTIAL')
        ORDER BY po.delivery_date
        """
    )
    results = [
        {**r, "delivery_date": str(r["delivery_date"])} for r in rows
    ]
    return {"status": "OK", "open_pos": results, "count": len(results)}


def list_all_materials() -> dict[str, Any]:
    """MM60 - List all materials"""
    rows = query_all(
        "SELECT material_id, description, material_type, unit, price, currency, category FROM materials ORDER BY material_id"
    )
    return {"status": "OK", "materials": rows, "count": len(rows)}


def check_reorder_needed() -> dict[str, Any]:
    """MD04 - Check materials needing reorder"""
    rows = query_all(
        """
        SELECT s.material_id, m.description, s.plant, s.unrestricted, s.reserved,
               s.reorder_point, m.unit
        FROM stock s
        JOIN materials m ON s.material_id = m.material_id
        WHERE (s.unrestricted - s.reserved) < s.reorder_point
        ORDER BY s.material_id
        """
    )
    alerts = [
        {
            "material_id": r["material_id"],
            "description": r["description"],
            "plant": r["plant"],
            "available": float(r["unrestricted"]) - float(r["reserved"]),
            "reorder_point": float(r["reorder_point"]),
            "unit": r["unit"],
        }
        for r in rows
    ]
    return {"status": "OK", "reorder_alerts": alerts, "count": len(alerts)}
