"""
SAP HR/HCM Module - Human Resources
Simulates BAPI_EMPLOYEE_*, HR_*, HRPAD* function modules
"""
from db.connection import query_one, query_all, execute
from typing import Any
import random
import string


def get_employee_info(emp_id: str) -> dict[str, Any]:
    """BAPI_EMPLOYEE_GETDATA - Get employee master data"""
    emp = query_one(
        """
        SELECT e.emp_id, e.name, e.department, e.position, e.grade,
               e.join_date, e.manager_id, e.email, e.phone, e.status,
               m.name AS manager_name
        FROM employees e
        LEFT JOIN employees m ON e.manager_id = m.emp_id
        WHERE e.emp_id = %s
        """,
        (emp_id.upper(),)
    )
    if not emp:
        return {"status": "ERROR", "message": f"Employee {emp_id} not found"}
    return {
        "status": "OK",
        "employee_id": emp["emp_id"],
        "name": emp["name"],
        "department": emp["department"],
        "position": emp["position"],
        "grade": emp["grade"],
        "join_date": str(emp["join_date"]) if emp["join_date"] else None,
        "manager_id": emp["manager_id"],
        "manager_name": emp["manager_name"] or "N/A",
        "email": emp["email"],
        "phone": emp["phone"],
        "status": emp["status"],
    }


def get_leave_balance(emp_id: str) -> dict[str, Any]:
    """HR_ABSENCE_OVERVIEW - Get leave balance"""
    emp = query_one(
        "SELECT emp_id, name FROM employees WHERE emp_id = %s",
        (emp_id.upper(),)
    )
    if not emp:
        return {"status": "ERROR", "message": f"Employee {emp_id} not found"}
    lb = query_one(
        "SELECT * FROM leave_balances WHERE emp_id = %s ORDER BY fiscal_year DESC LIMIT 1",
        (emp_id.upper(),)
    )
    if not lb:
        return {"status": "ERROR", "message": f"No leave data for {emp_id}"}
    return {
        "status": "OK",
        "employee_id": emp_id,
        "employee_name": emp["name"],
        "fiscal_year": lb["fiscal_year"],
        "annual_leave": {
            "entitled": lb["annual_entitled"],
            "used": float(lb["annual_used"]),
            "balance": lb["annual_entitled"] - float(lb["annual_used"]),
        },
        "sick_leave": {
            "entitled": lb["sick_entitled"],
            "used": float(lb["sick_used"]),
            "balance": lb["sick_entitled"] - float(lb["sick_used"]),
        },
        "casual_leave": {
            "entitled": lb["casual_entitled"],
            "used": float(lb["casual_used"]),
            "balance": lb["casual_entitled"] - float(lb["casual_used"]),
        },
    }


def get_payslip(emp_id: str) -> dict[str, Any]:
    """HRPAD00 - Get payslip/salary details"""
    emp = query_one(
        "SELECT emp_id, name, position FROM employees WHERE emp_id = %s",
        (emp_id.upper(),)
    )
    if not emp:
        return {"status": "ERROR", "message": f"Employee {emp_id} not found"}
    pay = query_one(
        "SELECT * FROM payroll WHERE emp_id = %s ORDER BY pay_year DESC, pay_month DESC LIMIT 1",
        (emp_id.upper(),)
    )
    if not pay:
        return {"status": "ERROR", "message": f"No payroll data for {emp_id}"}
    return {
        "status": "OK",
        "employee_id": emp_id,
        "employee_name": emp["name"],
        "position": emp["position"],
        "pay_period": f"{pay['pay_month']:02d}/{pay['pay_year']}",
        "basic_salary": float(pay["basic"]),
        "hra": float(pay["hra"]),
        "other_allowances": float(pay["allowances"]),
        "total_deductions": float(pay["deductions"]),
        "net_salary": float(pay["net"]),
        "currency": pay["currency"],
        "processed_on": str(pay["processed_on"]) if pay["processed_on"] else None,
    }


def apply_leave(emp_id: str, leave_type: str, days: int, reason: str = "") -> dict[str, Any]:
    """HR_ABSENCE_CREATE - Submit a leave application"""
    emp = query_one(
        "SELECT emp_id, name FROM employees WHERE emp_id = %s AND status = 'ACTIVE'",
        (emp_id.upper(),)
    )
    if not emp:
        return {"status": "ERROR", "message": f"Employee {emp_id} not found or inactive"}

    lt = leave_type.lower()
    leave_col_map = {
        "annual":  ("annual_entitled",  "annual_used"),
        "sick":    ("sick_entitled",    "sick_used"),
        "casual":  ("casual_entitled",  "casual_used"),
    }
    if lt not in leave_col_map:
        return {"status": "ERROR", "message": "Invalid leave type. Use: annual, sick, casual"}

    entitled_col, used_col = leave_col_map[lt]
    lb = query_one(
        f"SELECT lb_id, {entitled_col}, {used_col} FROM leave_balances WHERE emp_id = %s ORDER BY fiscal_year DESC LIMIT 1",
        (emp_id.upper(),)
    )
    if not lb:
        return {"status": "ERROR", "message": f"No leave balance record for {emp_id}"}

    entitled = lb[entitled_col]
    used = float(lb[used_col])
    balance = entitled - used

    if days > balance:
        return {
            "status": "ERROR",
            "message": f"Insufficient {leave_type} leave. Available: {balance} days, Requested: {days} days",
        }

    execute(
        f"UPDATE leave_balances SET {used_col} = {used_col} + %s WHERE lb_id = %s",
        (days, lb["lb_id"])
    )
    app_id = "LA" + "".join(random.choices(string.digits, k=6))
    return {
        "status": "OK",
        "message": "Leave application submitted successfully",
        "application_id": app_id,
        "employee_name": emp["name"],
        "leave_type": leave_type,
        "days_requested": days,
        "remaining_balance": balance - days,
        "reason": reason,
    }


def search_employees(dept: str = None, position: str = None) -> dict[str, Any]:
    """PA20 - Search employees by criteria"""
    sql = "SELECT emp_id, name, department, position, grade FROM employees WHERE status = 'ACTIVE'"
    params: list = []
    if dept:
        sql += " AND LOWER(department) LIKE %s"
        params.append(f"%{dept.lower()}%")
    if position:
        sql += " AND LOWER(position) LIKE %s"
        params.append(f"%{position.lower()}%")
    sql += " ORDER BY name"
    rows = query_all(sql, tuple(params))
    return {"status": "OK", "employees": rows, "count": len(rows)}


def get_org_chart(emp_id: str) -> dict[str, Any]:
    """PPOSE - Get organizational hierarchy"""
    emp = query_one(
        """
        SELECT e.emp_id, e.name, e.position, e.manager_id,
               m.name AS manager_name, m.position AS manager_position
        FROM employees e
        LEFT JOIN employees m ON e.manager_id = m.emp_id
        WHERE e.emp_id = %s
        """,
        (emp_id.upper(),)
    )
    if not emp:
        return {"status": "ERROR", "message": f"Employee {emp_id} not found"}
    reports = query_all(
        "SELECT emp_id, name, position FROM employees WHERE manager_id = %s AND status = 'ACTIVE'",
        (emp_id.upper(),)
    )
    return {
        "status": "OK",
        "employee": {"id": emp["emp_id"], "name": emp["name"], "position": emp["position"]},
        "manager": {
            "id": emp["manager_id"],
            "name": emp["manager_name"] or "N/A",
            "position": emp["manager_position"] or "N/A",
        },
        "direct_reports": [{"id": r["emp_id"], "name": r["name"], "position": r["position"]} for r in reports],
        "reports_count": len(reports),
    }
