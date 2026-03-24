"""
SAP ABAP Module - Development & Basis
Simulates SE38, SE37, SE10, STMS transactions and ABAP development tools
"""
from db.connection import query_one, query_all
from typing import Any
import re


def get_abap_program(program_name: str) -> dict[str, Any]:
    """SE38 - Get ABAP program/report details"""
    prog = query_one(
        "SELECT * FROM abap_programs WHERE program_name = %s",
        (program_name.upper(),)
    )
    if not prog:
        return {"status": "ERROR", "message": f"ABAP program '{program_name}' not found"}
    return {
        "status": "OK",
        "program_name": prog["program_name"],
        "description": prog["description"],
        "program_type": prog["program_type"],
        "package": prog["package"],
        "created_by": prog["created_by"],
        "created_on": str(prog["created_on"]) if prog["created_on"] else None,
        "lines": prog["line_count"],
        "program_status": prog["status"],
        "last_changed": str(prog["last_changed"]) if prog["last_changed"] else None,
    }


def get_function_module(fm_name: str) -> dict[str, Any]:
    """SE37 - Get function module details and parameters"""
    fm = query_one(
        "SELECT * FROM function_modules WHERE fm_name = %s",
        (fm_name.upper(),)
    )
    if not fm:
        return {"status": "ERROR", "message": f"Function module '{fm_name}' not found"}
    return {
        "status": "OK",
        "function_module": fm["fm_name"],
        "description": fm["description"],
        "function_group": fm["function_group"],
        "package": fm["package"],
        "parameters": fm["parameters"],
        "created_by": fm["created_by"],
        "status": fm["status"],
    }


def get_transport_request(tr_id: str) -> dict[str, Any]:
    """SE10/STMS - Get transport request status and objects"""
    tr = query_one(
        "SELECT * FROM transport_requests WHERE tr_id = %s",
        (tr_id.upper(),)
    )
    if not tr:
        return {"status": "ERROR", "message": f"Transport request '{tr_id}' not found"}
    return {
        "status": "OK",
        "transport_id": tr["tr_id"],
        "description": tr["description"],
        "tr_type": tr["tr_type"],
        "tr_status": tr["status"],
        "owner": tr["owner"],
        "created_on": str(tr["created_on"]) if tr["created_on"] else None,
        "released_on": str(tr["released_on"]) if tr["released_on"] else None,
        "target": tr["target"],
        "objects": tr["objects"],
    }


def list_abap_programs(package: str = None) -> dict[str, Any]:
    """SE80 - List ABAP programs, optionally filtered by package"""
    if package:
        rows = query_all(
            """
            SELECT program_name, description, program_type, package, `lines`, status, last_changed
            FROM abap_programs
            WHERE UPPER(package) = %s
            ORDER BY program_name
            """,
            (package.upper(),)
        )
    else:
        rows = query_all(
            "SELECT program_name, description, program_type, package, `lines`, status, last_changed FROM abap_programs ORDER BY program_name"
        )
    results = [
        {**r, "last_changed": str(r["last_changed"]) if r["last_changed"] else None}
        for r in rows
    ]
    return {"status": "OK", "programs": results, "count": len(results)}


def generate_abap_code(description: str) -> dict[str, Any]:
    """Generate ABAP code based on a natural language description."""
    desc_lower = description.lower()

    # Transport status check
    tr_match = re.search(r'\b([A-Z]{3}K\d{6})\b', description, re.IGNORECASE)
    if tr_match or any(kw in desc_lower for kw in ['transport', 'tr status', 'stms', 'se10', 'change request']):
        tr_id = tr_match.group(1).upper() if tr_match else 'DEVK900123'
        code = f"""REPORT ZCHECK_TRANSPORT_STATUS.
*----------------------------------------------------------------------*
* Program : ZCHECK_TRANSPORT_STATUS
* Purpose : Check transport request status from E070/E07T/E071 tables
* Transport: {tr_id}
*----------------------------------------------------------------------*

DATA: lv_trkorr  TYPE trkorr    VALUE '{tr_id}',
      ls_e070    TYPE e070,
      ls_e07t    TYPE e07t,
      lt_e071    TYPE TABLE OF e071,
      ls_e071    TYPE e071.

*-- Read transport request header (E070)
SELECT SINGLE *
  INTO ls_e070
  FROM e070
  WHERE trkorr = lv_trkorr.

IF sy-subrc <> 0.
  WRITE: / 'Transport request not found:', lv_trkorr.
  RETURN.
ENDIF.

*-- Read transport description (E07T)
SELECT SINGLE *
  INTO ls_e07t
  FROM e07t
  WHERE trkorr = lv_trkorr
    AND langu   = sy-langu.

*-- Read transport objects (E071)
SELECT *
  INTO TABLE lt_e071
  FROM e071
  WHERE trkorr = lv_trkorr.

*-- Display header
WRITE: / '================================================'.
WRITE: / 'TRANSPORT REQUEST STATUS REPORT'.
WRITE: / '================================================'.
WRITE: / 'Transport ID  :', ls_e070-trkorr.
WRITE: / 'Description   :', ls_e07t-as4text.
WRITE: / 'Type          :', ls_e070-trfunction.
WRITE: / 'Owner         :', ls_e070-as4user.
WRITE: / 'Target System :', ls_e070-tarsystem.
WRITE: / 'Category      :', ls_e070-korrdev.

*-- Decode status
WRITE: / 'Status Code   :', ls_e070-trstatus.
CASE ls_e070-trstatus.
  WHEN 'D'.
    WRITE: / 'Status Info   : Modifiable (Development Active)'.
  WHEN 'L'.
    WRITE: / 'Status Info   : Released'.
  WHEN 'O'.
    WRITE: / 'Status Info   : Release Started'.
  WHEN 'R'.
    WRITE: / 'Status Info   : Released for Import'.
  WHEN OTHERS.
    WRITE: / 'Status Info   : Unknown'.
ENDCASE.

*-- Display transport objects
WRITE: / ' '.
WRITE: / 'TRANSPORT OBJECTS:'.
WRITE: / '------------------------------------------'.
LOOP AT lt_e071 INTO ls_e071.
  WRITE: / ls_e071-pgmid, ls_e071-object, ls_e071-obj_name.
ENDLOOP.

IF lt_e071 IS INITIAL.
  WRITE: / 'No objects attached to this transport.'.
ENDIF.

WRITE: / '================================================'."""
        return {
            "status": "OK",
            "description": description,
            "code_type": "Transport Status Check",
            "transport_id": tr_id,
            "tables_used": ["E070", "E07T", "E071"],
            "tcode": "SE10 / STMS",
            "code": code,
            "instructions": [
                f"1. Open SE38 and create program ZCHECK_TRANSPORT_STATUS",
                f"2. Paste the generated code",
                f"3. Press F8 to execute",
                f"4. To check a different transport, change VALUE '{tr_id}' in the DATA statement",
                f"5. You can also check transport directly in SE10 → Enter {tr_id}",
            ],
        }

    # BAPI call template
    if any(kw in desc_lower for kw in ['bapi', 'function module', 'commit', 'fm call']):
        code = """REPORT ZBAPI_CALL_EXAMPLE.
*----------------------------------------------------------------------*
* BAPI Call Example with proper error handling
*----------------------------------------------------------------------*

DATA: ls_return  TYPE bapiret2,
      lt_return  TYPE TABLE OF bapiret2.

*-- Call BAPI
CALL FUNCTION 'BAPI_TRANSACTION_COMMIT'
  EXPORTING
    wait   = 'X'
  IMPORTING
    return = ls_return.

*-- Check return status
IF ls_return-type CA 'AEX'.
  WRITE: / 'BAPI Error:', ls_return-message.
  WRITE: / 'Message No:', ls_return-id, ls_return-number.
ELSE.
  WRITE: / 'BAPI executed successfully.'.
ENDIF."""
        return {
            "status": "OK",
            "description": description,
            "code_type": "BAPI Call",
            "code": code,
            "instructions": [
                "1. Replace 'BAPI_TRANSACTION_COMMIT' with your target BAPI name",
                "2. Add IMPORTING/EXPORTING/TABLES parameters as needed",
                "3. Always check SY-SUBRC and RETURN table after the call",
                "4. Use SE37 to look up BAPI parameters",
            ],
        }

    # SELECT / data read template
    if any(kw in desc_lower for kw in ['select', 'read data', 'fetch', 'open orders', 'sales order', 'purchase order']):
        code = """REPORT ZDATA_READ_EXAMPLE.
*----------------------------------------------------------------------*
* Data Read Example — Modern ABAP 7.4+ style
*----------------------------------------------------------------------*

DATA: lt_vbak TYPE TABLE OF vbak,
      ls_vbak TYPE vbak.

*-- Select with explicit field list (avoid SELECT *)
SELECT vbeln, kunnr, auart, waerk, netwr
  INTO TABLE lt_vbak
  FROM vbak
  WHERE waerk = 'INR'
  ORDER BY vbeln.

IF sy-subrc = 0.
  WRITE: / 'Records found:', lines( lt_vbak ).
  LOOP AT lt_vbak INTO ls_vbak.
    WRITE: / ls_vbak-vbeln, ls_vbak-kunnr, ls_vbak-netwr.
  ENDLOOP.
ELSE.
  WRITE: / 'No records found.'.
ENDIF."""
        return {
            "status": "OK",
            "description": description,
            "code_type": "Data Read / SELECT",
            "code": code,
            "instructions": [
                "1. Replace 'vbak' with your target table (use SE11 to explore)",
                "2. Update the field list and WHERE clause",
                "3. Use FOR ALL ENTRIES to avoid N+1 query patterns",
                "4. Always check SY-SUBRC after SELECT",
            ],
        }

    # Generic program template
    code = f"""REPORT ZCUSTOM_PROGRAM.
*----------------------------------------------------------------------*
* Auto-generated ABAP Program
* Requirement: {description}
*----------------------------------------------------------------------*

DATA: lv_result TYPE string.

START-OF-SELECTION.
  PERFORM get_data.
  PERFORM process_data.
  PERFORM display_results.

*----------------------------------------------------------------------*
FORM get_data.
*----------------------------------------------------------------------*
* TODO: Add data retrieval logic here
* Use SELECT, CALL FUNCTION, or BAPI calls as needed
ENDFORM.

*----------------------------------------------------------------------*
FORM process_data.
*----------------------------------------------------------------------*
* TODO: Add business logic / calculations here
ENDFORM.

*----------------------------------------------------------------------*
FORM display_results.
*----------------------------------------------------------------------*
  WRITE: / 'Program executed successfully.'.
* TODO: Add WRITE / ALV output statements here
ENDFORM."""
    return {
        "status": "OK",
        "description": description,
        "code_type": "Custom ABAP Program",
        "code": code,
        "instructions": [
            "1. Open SE38 and create a new program ZCUSTOM_PROGRAM",
            "2. Fill in the FORM routines with your business logic",
            "3. Press Ctrl+F2 for syntax check before saving",
            "4. Press F8 to execute",
        ],
    }


def analyze_abap_syntax(code_snippet: str) -> dict[str, Any]:
    """
    Comprehensive ABAP code analysis.
    Checks for performance anti-patterns, security issues, structural errors,
    obsolete syntax, and SAP best-practice violations.
    """
    issues: list[dict] = []
    suggestions: list[dict] = []
    info: list[dict] = []
    lines = code_snippet.strip().splitlines()
    upper_lines = [ln.strip().upper() for ln in lines]
    full_upper = "\n".join(upper_lines)

    def add_issue(line_no, severity, code, message, hint=""):
        issues.append({"line": line_no, "severity": severity,
                        "code": code, "message": message, "hint": hint})

    def add_suggestion(line_no, code, message, hint=""):
        suggestions.append({"line": line_no, "code": code,
                             "message": message, "hint": hint})

    def add_info(line_no, code, message):
        info.append({"line": line_no, "code": code, "message": message})

    # ── Global structure checks (single pass over all lines) ──────────────────
    loop_opens  = sum(1 for ln in upper_lines if re.match(r'^LOOP\s+AT\b', ln))
    loop_closes = sum(1 for ln in upper_lines if ln == "ENDLOOP.")
    if_opens    = sum(1 for ln in upper_lines if re.match(r'^IF\b', ln))
    if_closes   = sum(1 for ln in upper_lines if ln == "ENDIF.")
    try_opens   = sum(1 for ln in upper_lines if re.match(r'^TRY\b\.?$', ln))
    try_closes  = sum(1 for ln in upper_lines if re.match(r'^ENDTRY\b', ln))
    form_opens  = sum(1 for ln in upper_lines if re.match(r'^FORM\b', ln))
    form_closes = sum(1 for ln in upper_lines if re.match(r'^ENDFORM\b', ln))

    if loop_opens > loop_closes:
        add_issue(len(lines), "ERROR", "E001",
                  f"Unmatched LOOP AT — {loop_opens} open, {loop_closes} closed",
                  "Add the missing ENDLOOP.")
    if if_opens > if_closes:
        add_issue(len(lines), "ERROR", "E002",
                  f"Unmatched IF — {if_opens} open, {if_closes} closed",
                  "Add the missing ENDIF.")
    if try_opens > try_closes:
        add_issue(len(lines), "ERROR", "E003",
                  f"Unmatched TRY — {try_opens} open, {try_closes} closed",
                  "Add the missing ENDTRY.")
    if form_opens > form_closes:
        add_issue(len(lines), "ERROR", "E004",
                  f"Unmatched FORM — {form_opens} open, {form_closes} closed",
                  "Add the missing ENDFORM.")

    # Detect COMMIT WORK inside a LOOP (data integrity risk)
    in_loop = 0
    for i, ln in enumerate(upper_lines, 1):
        if re.match(r'^LOOP\s+AT\b', ln):  in_loop += 1
        if ln == "ENDLOOP.":               in_loop = max(0, in_loop - 1)
        if in_loop > 0 and re.match(r'^COMMIT\s+WORK', ln):
            add_issue(i, "ERROR", "E005",
                      "COMMIT WORK inside LOOP AT — risk of partial commits and data inconsistency",
                      "Move database commit outside the loop.")

    # Detect SELECT inside a LOOP (N+1 query pattern)
    in_loop = 0
    for i, ln in enumerate(upper_lines, 1):
        if re.match(r'^LOOP\s+AT\b', ln):  in_loop += 1
        if ln == "ENDLOOP.":               in_loop = max(0, in_loop - 1)
        if in_loop > 0 and re.match(r'^SELECT\b', ln):
            add_issue(i, "WARNING", "W001",
                      "SELECT inside LOOP AT — N+1 query anti-pattern degrades performance",
                      "Pre-fetch all required data before the loop using a JOIN or FOR ALL ENTRIES.")

    # ── Per-line checks ───────────────────────────────────────────────────────
    for i, (raw, ln) in enumerate(zip(lines, upper_lines), 1):

        # SELECT * performance
        if re.search(r'^\s*SELECT\s+\*', ln):
            add_issue(i, "WARNING", "W002",
                      "SELECT * fetches all columns — list only the fields you need",
                      "Replace * with explicit field names to reduce I/O and network load.")

        # SELECT without WHERE
        if re.match(r'^SELECT\b', ln) and "WHERE" not in ln and \
                "INTO" in ln and "COUNT" not in ln:
            add_suggestion(i, "S001",
                           "SELECT without WHERE clause — full table scan",
                           "Add a WHERE condition. If intentional, add a comment explaining why.")

        # Hard-coded client
        if re.search(r"MANDT\s*=\s*'[0-9]+'", ln) or \
           re.search(r"CLIENT\s*=\s*'[0-9]+'", ln):
            add_issue(i, "ERROR", "E006",
                      "Hard-coded SAP client number detected",
                      "Use SY-MANDT for the current client or CLIENT SPECIFIED with a variable.")

        # Hard-coded user ID
        if re.search(r"SY-UNAME\s*=\s*'[A-Z0-9]+'", ln):
            add_issue(i, "ERROR", "E007",
                      "Hard-coded user comparison — security vulnerability",
                      "Never compare SY-UNAME to a literal. Use authority checks instead.")

        # Old MOVE statement (obsolete since ABAP 7.4)
        if re.match(r'^MOVE\s+\S+\s+TO\s+', ln):
            add_suggestion(i, "S002",
                           "Obsolete MOVE ... TO — use inline assignment instead",
                           "Replace 'MOVE a TO b.' with 'b = a.' (ABAP 7.4+).")

        # Old WRITE TO (for formatting)
        if re.match(r'^WRITE\s+.*\s+TO\s+', ln) and "NO-ZERO" not in ln:
            add_suggestion(i, "S003",
                           "Consider using string expressions instead of WRITE ... TO",
                           "Use |{ variable }| string templates for cleaner formatting.")

        # Missing SY-SUBRC check after SELECT / CALL FUNCTION
        if re.match(r'^CALL\s+FUNCTION\b', ln):
            # look ahead up to 3 lines for SY-SUBRC
            window = upper_lines[i:min(i+4, len(upper_lines))]
            if not any("SY-SUBRC" in w or "EXCEPTIONS" in w for w in window):
                add_suggestion(i, "S004",
                               "CALL FUNCTION without EXCEPTIONS clause",
                               "Add EXCEPTIONS OTHERS = 1 and check SY-SUBRC after the call.")

        # CATCH without specific exception class
        if re.match(r'^CATCH\s+CX_ROOT\b', ln) or ln.strip() == "CATCH .":
            add_issue(i, "WARNING", "W003",
                      "Catching CX_ROOT catches ALL exceptions — too broad",
                      "Catch specific exception classes to avoid hiding unexpected errors.")

        # Magic number literals in conditions
        if re.search(r'\b(IF|ELSEIF)\b.*\b[0-9]{4,}\b', ln):
            add_suggestion(i, "S005",
                           "Magic number in condition — consider a named CONSTANT",
                           "Define a constant with a meaningful name to improve readability.")

        # Avoid obsolete MESSAGE syntax for user dialogs
        if re.match(r'^MESSAGE\s+[A-Z][0-9]+', ln):
            add_info(i, "I001",
                     "MESSAGE statement detected — consider using exception classes in modern ABAP.")

        # DATA declaration inside FORM/METHOD (should be at top)
        if re.match(r'^DATA\s+', ln) and in_loop > 0:
            add_suggestion(i, "S006",
                           "DATA declaration inside a loop body",
                           "Declare all variables at the top of the method/form, not inside loops.")

        # Use of FIELD-SYMBOLS without <> check
        if re.match(r'^FIELD-SYMBOLS\s*:', ln) and "TYPE" not in ln:
            add_suggestion(i, "S007",
                           "FIELD-SYMBOL declared without TYPE — always type field symbols",
                           "Add TYPE or LIKE to the declaration for type safety.")

        # Concatenation via old CONCATENATE keyword
        if re.match(r'^CONCATENATE\b', ln):
            add_suggestion(i, "S008",
                           "Obsolete CONCATENATE — use string templates instead",
                           "Replace with |{ var1 }{ var2 }| syntax (ABAP 7.4+).")

        # CHECK statement used as early exit (can hide logic)
        if re.match(r'^CHECK\b', ln):
            add_info(i, "I002",
                     "CHECK used for conditional exit — ensure this is intentional and documented.")

    # ── Positive detections (good practices found) ────────────────────────────
    good: list[str] = []
    if "TRY." in full_upper or "TRY\n" in full_upper:
        good.append("Exception handling (TRY/CATCH) found — good practice")
    if re.search(r'\bDATA\([A-Z_]+\)', full_upper):
        good.append("Inline declarations DATA(...) detected — modern ABAP style")
    if re.search(r'CL_ABAP_UNIT_ASSERT\b', full_upper):
        good.append("ABAP Unit test assertions detected — excellent practice")
    if re.search(r'LOG-POINT\b|CL_ABAP_RUNTIME\b', full_upper):
        good.append("Logging/tracing statements detected")

    # ── Score calculation ─────────────────────────────────────────────────────
    error_count   = sum(1 for iss in issues if iss["severity"] == "ERROR")
    warning_count = sum(1 for iss in issues if iss["severity"] == "WARNING")
    score = max(0, 100 - error_count * 25 - warning_count * 10 - len(suggestions) * 3)
    if good:
        score = min(100, score + len(good) * 5)

    rating = "EXCELLENT" if score >= 90 else \
             "GOOD"      if score >= 75 else \
             "NEEDS_REVIEW" if score >= 50 else "POOR"

    return {
        "status":         "OK",
        "lines_analyzed": len(lines),
        "error_count":    error_count,
        "warning_count":  warning_count,
        "suggestion_count": len(suggestions),
        "issues_found":   len(issues),
        "issues":         issues,
        "suggestions":    suggestions,
        "info":           info,
        "good_practices": good,
        "quality_score":  score,
        "rating":         rating,
    }
