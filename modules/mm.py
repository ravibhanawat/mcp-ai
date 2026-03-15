"""
SAP MM Module - Materials Management
Simulates BAPI_MATERIAL_*, BAPI_PO_*, MB_*, ME_* function modules
"""
from mock_data.sap_data import MATERIALS, STOCK, PURCHASE_ORDERS, VENDORS
from typing import Any


def get_material_info(material_id: str) -> dict[str, Any]:
    """BAPI_MATERIAL_GET_DETAIL - Get material master data"""
    mat = MATERIALS.get(material_id.upper())
    if not mat:
        return {"status": "ERROR", "message": f"Material {material_id} not found"}
    return {"status": "OK", "material_id": material_id, **mat}


def get_stock_level(material_id: str, plant: str = "1000") -> dict[str, Any]:
    """BAPI_MATERIAL_STOCK_REQ_LIST - Get stock levels"""
    key = (material_id.upper(), plant)
    stock = STOCK.get(key)
    if not stock:
        # Try any plant for this material
        for (mat, plt), stk in STOCK.items():
            if mat == material_id.upper():
                stock = stk
                plant = plt
                break
    if not stock:
        return {"status": "ERROR", "message": f"No stock data found for material {material_id}"}
    mat = MATERIALS.get(material_id.upper(), {})
    available = stock["unrestricted"] - stock["reserved"]
    return {
        "status": "OK",
        "material_id": material_id,
        "description": mat.get("desc", ""),
        "plant": plant,
        "plant_name": stock.get("plant", ""),
        "unrestricted": stock["unrestricted"],
        "reserved": stock["reserved"],
        "in_transit": stock["in_transit"],
        "available_to_promise": available,
        "unit": mat.get("unit", "EA")
    }


def get_purchase_order(po_id: str) -> dict[str, Any]:
    """BAPI_PO_GETDETAIL - Get purchase order details"""
    po = PURCHASE_ORDERS.get(po_id.upper())
    if not po:
        return {"status": "ERROR", "message": f"PO {po_id} not found"}
    vendor = VENDORS.get(po["vendor"], {})
    mat = MATERIALS.get(po["material"], {})
    total_value = po["qty"] * po["price"]
    return {
        "status": "OK",
        "po_id": po_id,
        "vendor_name": vendor.get("name", ""),
        "material_desc": mat.get("desc", ""),
        "qty": po["qty"],
        "unit": po["unit"],
        "unit_price": po["price"],
        "total_value": total_value,
        "delivery_date": po["delivery_date"],
        "po_status": po["status"],
        "currency": mat.get("currency", "INR")
    }


def list_open_purchase_orders() -> dict[str, Any]:
    """ME2M - List all open purchase orders"""
    results = []
    for po_id, po in PURCHASE_ORDERS.items():
        if po["status"] in ("OPEN", "PARTIAL"):
            vendor = VENDORS.get(po["vendor"], {})
            mat = MATERIALS.get(po["material"], {})
            results.append({
                "po_id": po_id,
                "vendor": vendor.get("name", ""),
                "material": mat.get("desc", ""),
                "qty": po["qty"],
                "status": po["status"],
                "delivery_date": po["delivery_date"]
            })
    return {"status": "OK", "open_pos": results, "count": len(results)}


def list_all_materials() -> dict[str, Any]:
    """MM60 - List all materials"""
    result = []
    for mat_id, mat in MATERIALS.items():
        result.append({"material_id": mat_id, **mat})
    return {"status": "OK", "materials": result, "count": len(result)}


def check_reorder_needed() -> dict[str, Any]:
    """MD04 - Check materials needing reorder"""
    alerts = []
    REORDER_THRESHOLD = 30  # units
    for (mat_id, plant), stock in STOCK.items():
        available = stock["unrestricted"] - stock["reserved"]
        if available < REORDER_THRESHOLD:
            mat = MATERIALS.get(mat_id, {})
            alerts.append({
                "material_id": mat_id,
                "description": mat.get("desc", ""),
                "plant": plant,
                "available": available,
                "unit": mat.get("unit", "EA")
            })
    return {"status": "OK", "reorder_alerts": alerts, "count": len(alerts)}
