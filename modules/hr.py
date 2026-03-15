"""
SAP HR/HCM Module - Human Resources
Simulates BAPI_EMPLOYEE_*, HR_*, HRPAD* function modules
"""
from mock_data.sap_data import EMPLOYEES, LEAVE_BALANCES, PAYROLL
from typing import Any
import random
import string


def get_employee_info(emp_id: str) -> dict[str, Any]:
    """BAPI_EMPLOYEE_GETDATA - Get employee master data"""
    emp = EMPLOYEES.get(emp_id.upper())
    if not emp:
        return {"status": "ERROR", "message": f"Employee {emp_id} not found"}
    manager = EMPLOYEES.get(emp["manager"], {})
    return {
        "status": "OK",
        "employee_id": emp_id,
        "name": emp["name"],
        "department": emp["dept"],
        "position": emp["position"],
        "grade": emp["grade"],
        "join_date": emp["join_date"],
        "manager_name": manager.get("name", "N/A"),
        "manager_id": emp["manager"]
    }


def get_leave_balance(emp_id: str) -> dict[str, Any]:
    """HR_ABSENCE_OVERVIEW - Get leave balance"""
    emp = EMPLOYEES.get(emp_id.upper())
    if not emp:
        return {"status": "ERROR", "message": f"Employee {emp_id} not found"}
    lb = LEAVE_BALANCES.get(emp_id.upper())
    if not lb:
        return {"status": "ERROR", "message": f"No leave data for {emp_id}"}
    return {
        "status": "OK",
        "employee_id": emp_id,
        "employee_name": emp["name"],
        "annual_leave": {"entitled": lb["annual"], "used": lb["used_annual"], "balance": lb["annual"] - lb["used_annual"]},
        "sick_leave": {"entitled": lb["sick"], "used": lb["used_sick"], "balance": lb["sick"] - lb["used_sick"]},
        "casual_leave": {"entitled": lb["casual"], "used": lb["used_casual"], "balance": lb["casual"] - lb["used_casual"]},
    }


def get_payslip(emp_id: str) -> dict[str, Any]:
    """HRPAD00 - Get payslip/salary details"""
    emp = EMPLOYEES.get(emp_id.upper())
    if not emp:
        return {"status": "ERROR", "message": f"Employee {emp_id} not found"}
    pay = PAYROLL.get(emp_id.upper())
    if not pay:
        return {"status": "ERROR", "message": f"No payroll data for {emp_id}"}
    return {
        "status": "OK",
        "employee_id": emp_id,
        "employee_name": emp["name"],
        "position": emp["position"],
        "basic_salary": pay["basic"],
        "hra": pay["hra"],
        "other_allowances": pay["allowances"],
        "total_deductions": pay["deductions"],
        "net_salary": pay["net"],
        "currency": pay["currency"]
    }


def apply_leave(emp_id: str, leave_type: str, days: int, reason: str = "") -> dict[str, Any]:
    """HR_ABSENCE_CREATE - Submit a leave application"""
    emp = EMPLOYEES.get(emp_id.upper())
    if not emp:
        return {"status": "ERROR", "message": f"Employee {emp_id} not found"}
    lb = LEAVE_BALANCES.get(emp_id.upper())
    leave_map = {"annual": "used_annual", "sick": "used_sick", "casual": "used_casual"}
    lt = leave_type.lower()
    if lt not in leave_map:
        return {"status": "ERROR", "message": f"Invalid leave type. Use: annual, sick, casual"}
    entitled_key = lt
    used_key = leave_map[lt]
    balance = lb[entitled_key] - lb[used_key]
    if days > balance:
        return {"status": "ERROR", "message": f"Insufficient {leave_type} leave. Available: {balance} days, Requested: {days} days"}
    # Apply leave
    lb[used_key] += days
    app_id = "LA" + "".join(random.choices(string.digits, k=5))
    return {
        "status": "OK",
        "message": "Leave application submitted successfully",
        "application_id": app_id,
        "employee_name": emp["name"],
        "leave_type": leave_type,
        "days_requested": days,
        "remaining_balance": balance - days,
        "reason": reason
    }


def search_employees(dept: str = None, position: str = None) -> dict[str, Any]:
    """PA20 - Search employees by criteria"""
    results = []
    for emp_id, emp in EMPLOYEES.items():
        match = True
        if dept and dept.lower() not in emp["dept"].lower():
            match = False
        if position and position.lower() not in emp["position"].lower():
            match = False
        if match:
            results.append({
                "employee_id": emp_id,
                "name": emp["name"],
                "department": emp["dept"],
                "position": emp["position"],
                "grade": emp["grade"]
            })
    return {"status": "OK", "employees": results, "count": len(results)}


def get_org_chart(emp_id: str) -> dict[str, Any]:
    """PPOSE - Get organizational hierarchy"""
    emp = EMPLOYEES.get(emp_id.upper())
    if not emp:
        return {"status": "ERROR", "message": f"Employee {emp_id} not found"}
    manager = EMPLOYEES.get(emp["manager"], {})
    # Find direct reports
    direct_reports = []
    for eid, e in EMPLOYEES.items():
        if e.get("manager") == emp_id.upper():
            direct_reports.append({"id": eid, "name": e["name"], "position": e["position"]})
    return {
        "status": "OK",
        "employee": {"id": emp_id, "name": emp["name"], "position": emp["position"]},
        "manager": {"id": emp["manager"], "name": manager.get("name", "N/A"), "position": manager.get("position", "N/A")},
        "direct_reports": direct_reports,
        "reports_count": len(direct_reports)
    }
