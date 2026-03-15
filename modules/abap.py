"""
SAP ABAP Module - Development & Basis
Simulates SE38, SE37, SE10, STMS transactions and ABAP development tools
"""
from mock_data.sap_data import (
    ABAP_PROGRAMS, FUNCTION_MODULES, TRANSPORT_REQUESTS, ABAP_PACKAGES
)
from typing import Any
import re


def get_abap_program(program_name: str) -> dict[str, Any]:
    """SE38 - Get ABAP program/report details"""
    prog = ABAP_PROGRAMS.get(program_name.upper())
    if not prog:
        return {"status": "ERROR", "message": f"ABAP program '{program_name}' not found"}
    return {"status": "OK", "program_name": program_name.upper(), **prog}


def get_function_module(fm_name: str) -> dict[str, Any]:
    """SE37 - Get function module details and parameters"""
    fm = FUNCTION_MODULES.get(fm_name.upper())
    if not fm:
        return {"status": "ERROR", "message": f"Function module '{fm_name}' not found"}
    return {"status": "OK", "function_module": fm_name.upper(), **fm}


def get_transport_request(tr_id: str) -> dict[str, Any]:
    """SE10/STMS - Get transport request status and objects"""
    tr = TRANSPORT_REQUESTS.get(tr_id.upper())
    if not tr:
        return {"status": "ERROR", "message": f"Transport request '{tr_id}' not found"}
    return {"status": "OK", "transport_id": tr_id.upper(), **tr}


def list_abap_programs(package: str = None) -> dict[str, Any]:
    """SE80 - List ABAP programs, optionally filtered by package"""
    results = []
    for prog_name, prog in ABAP_PROGRAMS.items():
        if package is None or prog["package"].upper() == package.upper():
            results.append({
                "program": prog_name,
                "description": prog["description"],
                "type": prog["type"],
                "package": prog["package"],
                "lines": prog["lines"],
                "status": prog["status"],
                "last_changed": prog["last_changed"],
            })
    return {"status": "OK", "programs": results, "count": len(results)}


def analyze_abap_syntax(code_snippet: str) -> dict[str, Any]:
    """Analyze ABAP code snippet for common syntax issues and patterns"""
    issues = []
    suggestions = []
    lines = code_snippet.strip().splitlines()

    for i, line in enumerate(lines, 1):
        stripped = line.strip().upper()

        # Check for SELECT * (performance issue)
        if re.search(r'SELECT\s+\*', stripped):
            issues.append({
                "line": i,
                "severity": "WARNING",
                "message": "Avoid SELECT * — specify only required fields for performance",
            })

        # Check for missing INTO clause in SELECT
        if stripped.startswith("SELECT") and "INTO" not in stripped and "COUNT" not in stripped:
            suggestions.append({
                "line": i,
                "message": "Ensure SELECT has an INTO clause",
            })

        # Detect hard-coded client (SY-MANDT best practice)
        if "MANDT = '100'" in stripped or "CLIENT = '100'" in stripped:
            issues.append({
                "line": i,
                "severity": "ERROR",
                "message": "Hard-coded client '100' detected — use SY-MANDT instead",
            })

        # Missing ENDLOOP
        loop_opens = sum(1 for l in lines if l.strip().upper().startswith("LOOP AT"))
        loop_closes = sum(1 for l in lines if l.strip().upper() == "ENDLOOP.")
        if loop_opens > loop_closes:
            if i == len(lines):
                issues.append({
                    "line": i,
                    "severity": "ERROR",
                    "message": f"Unmatched LOOP AT — found {loop_opens} LOOP(s) but only {loop_closes} ENDLOOP(s)",
                })

    score = max(0, 100 - len(issues) * 20 - len(suggestions) * 5)
    return {
        "status": "OK",
        "lines_analyzed": len(lines),
        "issues_found": len(issues),
        "issues": issues,
        "suggestions": suggestions,
        "quality_score": score,
        "rating": "GOOD" if score >= 80 else "NEEDS_REVIEW" if score >= 50 else "POOR",
    }
