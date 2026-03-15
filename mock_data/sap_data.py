"""
Mock SAP data for all modules - FI/CO, MM, SD, HR, PP
Simulates SAP BAPI/RFC responses without a real SAP connection
"""

# ─────────────────────────────────────────
# FI/CO - Finance & Controlling
# ─────────────────────────────────────────
VENDORS = {
    "V001": {"name": "Tata Consultancy Services", "city": "Mumbai", "country": "IN", "payment_terms": "30 days"},
    "V002": {"name": "Infosys Ltd", "city": "Bangalore", "country": "IN", "payment_terms": "45 days"},
    "V003": {"name": "SAP AG", "city": "Walldorf", "country": "DE", "payment_terms": "60 days"},
}

INVOICES = {
    "INV1000": {"vendor": "V001", "amount": 250000.00, "currency": "INR", "status": "OPEN", "due_date": "2026-04-01", "po": "PO2001"},
    "INV1001": {"vendor": "V002", "amount": 180000.00, "currency": "INR", "status": "PAID", "due_date": "2026-03-15", "po": "PO2002"},
    "INV1002": {"vendor": "V003", "amount": 50000.00, "currency": "EUR", "status": "BLOCKED", "due_date": "2026-04-10", "po": "PO2003"},
}

COST_CENTERS = {
    "CC100": {"name": "IT Department", "budget": 5000000.00, "actual": 3200000.00, "currency": "INR"},
    "CC200": {"name": "HR Department", "budget": 2000000.00, "actual": 1750000.00, "currency": "INR"},
    "CC300": {"name": "Sales Department", "budget": 8000000.00, "actual": 6100000.00, "currency": "INR"},
}

GL_ACCOUNTS = {
    "40001": {"name": "Office Supplies", "type": "EXPENSE", "balance": -45000.00},
    "40002": {"name": "Travel Expenses", "type": "EXPENSE", "balance": -120000.00},
    "10001": {"name": "Main Bank Account", "type": "ASSET", "balance": 5000000.00},
}

# ─────────────────────────────────────────
# MM - Materials Management
# ─────────────────────────────────────────
MATERIALS = {
    "MAT001": {"desc": "Laptop Dell XPS 15", "type": "FERT", "unit": "EA", "price": 85000.00, "currency": "INR"},
    "MAT002": {"desc": "Office Chair Ergonomic", "type": "FERT", "unit": "EA", "price": 12000.00, "currency": "INR"},
    "MAT003": {"desc": "Steel Rod 10mm", "type": "ROH", "unit": "KG", "price": 75.00, "currency": "INR"},
    "MAT004": {"desc": "Printer Paper A4", "type": "HIBE", "unit": "RM", "price": 450.00, "currency": "INR"},
}

STOCK = {
    ("MAT001", "1000"): {"unrestricted": 50, "reserved": 10, "in_transit": 5, "plant": "Plant Mumbai"},
    ("MAT002", "1000"): {"unrestricted": 120, "reserved": 20, "in_transit": 0, "plant": "Plant Mumbai"},
    ("MAT003", "2000"): {"unrestricted": 5000, "reserved": 500, "in_transit": 200, "plant": "Plant Delhi"},
    ("MAT004", "1000"): {"unrestricted": 300, "reserved": 50, "in_transit": 0, "plant": "Plant Mumbai"},
}

PURCHASE_ORDERS = {
    "PO2001": {"vendor": "V001", "material": "MAT001", "qty": 20, "unit": "EA", "price": 85000.00, "status": "OPEN", "delivery_date": "2026-04-05"},
    "PO2002": {"vendor": "V002", "material": "MAT002", "qty": 50, "unit": "EA", "price": 12000.00, "status": "DELIVERED", "delivery_date": "2026-03-10"},
    "PO2003": {"vendor": "V003", "material": "MAT003", "qty": 1000, "unit": "KG", "price": 75.00, "status": "PARTIAL", "delivery_date": "2026-04-15"},
}

# ─────────────────────────────────────────
# SD - Sales & Distribution
# ─────────────────────────────────────────
CUSTOMERS = {
    "C001": {"name": "Reliance Industries", "city": "Mumbai", "credit_limit": 10000000.00, "payment_terms": "30 days"},
    "C002": {"name": "Wipro Ltd", "city": "Bangalore", "credit_limit": 5000000.00, "payment_terms": "45 days"},
    "C003": {"name": "HDFC Bank", "city": "Mumbai", "credit_limit": 20000000.00, "payment_terms": "15 days"},
}

SALES_ORDERS = {
    "SO5001": {"customer": "C001", "material": "MAT001", "qty": 10, "price": 90000.00, "status": "OPEN", "delivery_date": "2026-04-20"},
    "SO5002": {"customer": "C002", "material": "MAT002", "qty": 30, "price": 13000.00, "status": "DELIVERED", "delivery_date": "2026-03-20"},
    "SO5003": {"customer": "C003", "material": "MAT004", "qty": 100, "price": 500.00, "status": "IN_PROGRESS", "delivery_date": "2026-04-10"},
}

DELIVERIES = {
    "DEL6001": {"sales_order": "SO5001", "status": "PENDING", "ship_date": "2026-04-18", "carrier": "BlueDart"},
    "DEL6002": {"sales_order": "SO5002", "status": "DELIVERED", "ship_date": "2026-03-19", "carrier": "DTDC"},
}

# ─────────────────────────────────────────
# HR/HCM - Human Resources
# ─────────────────────────────────────────
EMPLOYEES = {
    "EMP001": {"name": "Ravi Sharma", "dept": "IT", "position": "Senior Developer", "grade": "E5", "join_date": "2021-06-01", "manager": "EMP010"},
    "EMP002": {"name": "Priya Singh", "dept": "HR", "position": "HR Manager", "grade": "M2", "join_date": "2019-03-15", "manager": "EMP011"},
    "EMP003": {"name": "Amit Patel", "dept": "Sales", "position": "Sales Executive", "grade": "E3", "join_date": "2022-11-01", "manager": "EMP012"},
    "EMP010": {"name": "Sunita Joshi", "dept": "IT", "position": "IT Manager", "grade": "M3", "join_date": "2018-01-10", "manager": "EMP020"},
}

LEAVE_BALANCES = {
    "EMP001": {"annual": 15, "sick": 7, "casual": 5, "used_annual": 5, "used_sick": 2, "used_casual": 1},
    "EMP002": {"annual": 18, "sick": 7, "casual": 5, "used_annual": 10, "used_sick": 0, "used_casual": 3},
    "EMP003": {"annual": 12, "sick": 7, "casual": 5, "used_annual": 2, "used_sick": 1, "used_casual": 0},
}

PAYROLL = {
    "EMP001": {"basic": 80000, "hra": 32000, "allowances": 15000, "deductions": 12000, "net": 115000, "currency": "INR"},
    "EMP002": {"basic": 90000, "hra": 36000, "allowances": 18000, "deductions": 14000, "net": 130000, "currency": "INR"},
    "EMP003": {"basic": 50000, "hra": 20000, "allowances": 10000, "deductions": 8000, "net": 72000, "currency": "INR"},
}

# ─────────────────────────────────────────
# PP - Production Planning
# ─────────────────────────────────────────
WORK_CENTERS = {
    "WC001": {"name": "Assembly Line A", "plant": "1000", "capacity": 8, "unit": "HR", "status": "ACTIVE"},
    "WC002": {"name": "Welding Station", "plant": "2000", "capacity": 16, "unit": "HR", "status": "ACTIVE"},
    "WC003": {"name": "Quality Control", "plant": "1000", "capacity": 4, "unit": "HR", "status": "MAINTENANCE"},
}

PRODUCTION_ORDERS = {
    "PRD7001": {"material": "MAT001", "qty": 50, "plant": "1000", "work_center": "WC001", "status": "IN_PROGRESS", "start": "2026-03-01", "end": "2026-03-31"},
    "PRD7002": {"material": "MAT003", "qty": 2000, "plant": "2000", "work_center": "WC002", "status": "PLANNED", "start": "2026-04-01", "end": "2026-04-20"},
    "PRD7003": {"material": "MAT002", "qty": 100, "plant": "1000", "work_center": "WC001", "status": "COMPLETED", "start": "2026-02-01", "end": "2026-02-28"},
}

BOM = {
    "MAT001": [
        {"component": "CPU", "qty": 1, "unit": "EA"},
        {"component": "RAM_16GB", "qty": 2, "unit": "EA"},
        {"component": "SSD_512", "qty": 1, "unit": "EA"},
        {"component": "CHASSIS", "qty": 1, "unit": "EA"},
    ],
    "MAT002": [
        {"component": "SEAT_FOAM", "qty": 1, "unit": "EA"},
        {"component": "STEEL_FRAME", "qty": 5, "unit": "KG"},
        {"component": "WHEELS", "qty": 5, "unit": "EA"},
        {"component": "ARMRESTS", "qty": 2, "unit": "EA"},
    ],
}

# ─────────────────────────────────────────
# ABAP - Development & Basis
# ─────────────────────────────────────────
ABAP_PROGRAMS = {
    "ZREP_VENDOR_LIST": {
        "description": "Custom Vendor List Report",
        "type": "REPORT",
        "package": "ZFICO",
        "created_by": "EMP001",
        "created_on": "2023-05-10",
        "lines": 320,
        "status": "ACTIVE",
        "last_changed": "2025-11-20",
    },
    "ZREP_STOCK_ALERT": {
        "description": "Stock Below Reorder Level Alert",
        "type": "REPORT",
        "package": "ZMM",
        "created_by": "EMP010",
        "created_on": "2023-08-15",
        "lines": 210,
        "status": "ACTIVE",
        "last_changed": "2026-01-05",
    },
    "ZBAPI_SO_CREATE": {
        "description": "Custom Sales Order Creation Enhancement",
        "type": "PROGRAM",
        "package": "ZSD",
        "created_by": "EMP001",
        "created_on": "2024-01-20",
        "lines": 540,
        "status": "ACTIVE",
        "last_changed": "2026-02-14",
    },
    "ZFORM_PAYSLIP": {
        "description": "Payslip Smartform Driver Program",
        "type": "REPORT",
        "package": "ZHR",
        "created_by": "EMP002",
        "created_on": "2022-12-01",
        "lines": 180,
        "status": "ACTIVE",
        "last_changed": "2025-09-30",
    },
}

FUNCTION_MODULES = {
    "Z_GET_VENDOR_MASTER": {
        "description": "Custom FM to fetch vendor master with extensions",
        "function_group": "ZFICO_UTIL",
        "package": "ZFICO",
        "parameters": ["IV_VENDOR_ID (Import)", "ES_VENDOR_DATA (Export)", "ET_RETURN (Tables)"],
        "created_by": "EMP001",
        "status": "ACTIVE",
    },
    "Z_CREATE_SALES_ORDER": {
        "description": "Custom FM wrapping BAPI_SALESORDER_CREATEFROMDAT2",
        "function_group": "ZSD_BAPI",
        "package": "ZSD",
        "parameters": ["IS_ORDER_HEADER (Import)", "IT_ITEMS (Tables)", "EV_ORDER_ID (Export)"],
        "created_by": "EMP001",
        "status": "ACTIVE",
    },
    "Z_HR_LEAVE_VALIDATE": {
        "description": "Validates leave request against HR policy rules",
        "function_group": "ZHR_UTIL",
        "package": "ZHR",
        "parameters": ["IV_EMP_ID (Import)", "IV_DAYS (Import)", "EV_APPROVED (Export)"],
        "created_by": "EMP002",
        "status": "ACTIVE",
    },
}

TRANSPORT_REQUESTS = {
    "DEVK900123": {
        "description": "Vendor List Report - Production Fix",
        "type": "Workbench",
        "status": "RELEASED",
        "owner": "EMP001",
        "created_on": "2026-02-01",
        "released_on": "2026-02-10",
        "target": "PRD",
        "objects": ["ZREP_VENDOR_LIST", "Z_GET_VENDOR_MASTER"],
    },
    "DEVK900124": {
        "description": "Sales Order BAPI Enhancement",
        "type": "Workbench",
        "status": "MODIFIABLE",
        "owner": "EMP001",
        "created_on": "2026-03-01",
        "released_on": None,
        "target": "QAS",
        "objects": ["ZBAPI_SO_CREATE", "Z_CREATE_SALES_ORDER"],
    },
    "DEVK900125": {
        "description": "HR Leave Validation Policy Update",
        "type": "Workbench",
        "status": "RELEASED",
        "owner": "EMP002",
        "created_on": "2026-02-20",
        "released_on": "2026-02-28",
        "target": "PRD",
        "objects": ["Z_HR_LEAVE_VALIDATE", "ZFORM_PAYSLIP"],
    },
}

ABAP_PACKAGES = {
    "ZFICO": {
        "description": "Custom Finance & Controlling Objects",
        "programs": ["ZREP_VENDOR_LIST"],
        "function_groups": ["ZFICO_UTIL"],
    },
    "ZMM": {
        "description": "Custom Materials Management Objects",
        "programs": ["ZREP_STOCK_ALERT"],
        "function_groups": [],
    },
    "ZSD": {
        "description": "Custom Sales & Distribution Objects",
        "programs": ["ZBAPI_SO_CREATE"],
        "function_groups": ["ZSD_BAPI"],
    },
    "ZHR": {
        "description": "Custom HR Objects",
        "programs": ["ZFORM_PAYSLIP"],
        "function_groups": ["ZHR_UTIL"],
    },
}
