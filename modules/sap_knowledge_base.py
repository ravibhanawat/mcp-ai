"""
SAP Knowledge Base — Documentation Search
Provides searchable SAP documentation: T-codes, BAPIs, business processes,
configuration guides, and error troubleshooting.
Used by the 'search_sap_docs' tool for SAP Documentation Search feature.
"""
from __future__ import annotations
import re

# ─── SAP Knowledge Base ────────────────────────────────────────────────────────
# Structured as: { category: [ { title, content, keywords, module, tcode, bapi } ] }

SAP_DOCS: dict[str, list[dict]] = {

    "tcode": [
        {
            "title": "ME21N - Create Purchase Order",
            "tcode": "ME21N", "module": "MM", "bapi": "BAPI_PO_CREATE1",
            "content": (
                "Transaction ME21N is used to create purchase orders in SAP MM. "
                "Steps: (1) Enter vendor, purchasing org, plant. (2) Add line items with material, quantity, price. "
                "(3) Check account assignment (cost center or project). (4) Save to generate PO number. "
                "The PO goes through release strategy if configured. BAPI equivalent: BAPI_PO_CREATE1."
            ),
            "keywords": ["create purchase order", "po", "me21n", "procurement", "vendor order"],
        },
        {
            "title": "MIRO - Invoice Verification",
            "tcode": "MIRO", "module": "MM/FI", "bapi": "BAPI_INCOMINGINVOICE_CREATE",
            "content": (
                "MIRO is used for logistics invoice verification in SAP. It performs 3-way match: "
                "PO (purchase order) vs GR (goods receipt) vs Invoice. "
                "Steps: (1) Enter invoice date and reference. (2) Select PO/GR reference. "
                "(3) System auto-proposes values. (4) Check tolerances. (5) Post or park. "
                "Blocked invoices appear in MRBR for release."
            ),
            "keywords": ["invoice verification", "miro", "3-way match", "post invoice", "accounts payable"],
        },
        {
            "title": "VA01 - Create Sales Order",
            "tcode": "VA01", "module": "SD", "bapi": "BAPI_SALESORDER_CREATEFROMDAT2",
            "content": (
                "VA01 creates sales orders in SAP SD. "
                "Steps: (1) Select order type (e.g. OR for standard). (2) Enter sales org, dist. channel, division. "
                "(3) Add customer and items with quantities. (4) Check pricing, delivery dates. "
                "(5) Save. System checks credit limit and availability. "
                "Use VA02 to change, VA03 to display."
            ),
            "keywords": ["create sales order", "va01", "order entry", "customer order", "sd"],
        },
        {
            "title": "PA40 - HR Personnel Actions",
            "tcode": "PA40", "module": "HR", "bapi": "BAPI_EMPLOYEE_ENQUEUE",
            "content": (
                "PA40 is used for all HR personnel actions including hiring, transfer, promotion, termination. "
                "Steps: (1) Enter employee ID. (2) Select action type (e.g. 01=Hire, 02=Transfer). "
                "(3) Enter action date. (4) System executes infotype sequence. "
                "Common infotypes: IT0001 (Org Assignment), IT0002 (Personal Data), IT0008 (Basic Pay)."
            ),
            "keywords": ["personnel action", "hire employee", "pa40", "onboarding", "hr action", "transfer"],
        },
        {
            "title": "F110 - Automatic Payment Run",
            "tcode": "F110", "module": "FI", "bapi": "BAPI_ACC_DOCUMENT_POST",
            "content": (
                "F110 runs automatic vendor payments in SAP FI. "
                "Steps: (1) Set run date and identification. (2) Define parameters (company code, payment methods, vendor range). "
                "(3) Execute proposal run. (4) Review and edit proposal. (5) Execute payment run. "
                "(6) Print payment media (checks/bank files). "
                "Use FBZP to configure payment methods first."
            ),
            "keywords": ["payment run", "f110", "automatic payment", "vendor payment", "ap", "accounts payable"],
        },
        {
            "title": "CO01 - Create Production Order",
            "tcode": "CO01", "module": "PP", "bapi": "BAPI_PRODORD_CREATE",
            "content": (
                "CO01 creates production orders in SAP PP. "
                "Steps: (1) Enter material, plant, order type. (2) Set quantity and basic dates. "
                "(3) System reads BOM and routing. (4) Schedule the order. (5) Release and print. "
                "Use CO02 to change, CO03 to display. COOIS for mass list."
            ),
            "keywords": ["production order", "co01", "manufacturing", "work order", "pp"],
        },
        {
            "title": "SE38 - ABAP Editor",
            "tcode": "SE38", "module": "ABAP", "bapi": "N/A",
            "content": (
                "SE38 is the ABAP program editor. Use it to create, edit, and execute ABAP reports. "
                "Steps: (1) Enter program name. (2) Choose Create/Change/Display/Execute. "
                "(3) For Z-programs, assign to package and transport. "
                "Use F8 to execute, Ctrl+F2 for syntax check. "
                "SE80 (Object Navigator) provides a hierarchical view of all objects."
            ),
            "keywords": ["abap editor", "se38", "z program", "report", "program", "abap development"],
        },
        {
            "title": "STMS - Transport Management System",
            "tcode": "STMS", "module": "Basis/ABAP", "bapi": "N/A",
            "content": (
                "STMS manages the transport of SAP objects between systems (DEV → QAS → PRD). "
                "Steps: (1) In SE10, create transport request and add objects. "
                "(2) Release the task and request. (3) In STMS, import into target system. "
                "Transport types: Workbench (cross-client objects), Customizing (client-specific). "
                "Check import logs in STMS → Import Queue → Logs."
            ),
            "keywords": ["transport", "stms", "basis", "deployment", "system change", "tr"],
        },
    ],

    "bapi": [
        {
            "title": "BAPI_PO_CREATE1 - Purchase Order Creation",
            "tcode": "ME21N", "module": "MM", "bapi": "BAPI_PO_CREATE1",
            "content": (
                "BAPI_PO_CREATE1 creates purchase orders programmatically. "
                "Key parameters: POHEADER (header data), POITEM (line items), POSCHEDULE (delivery schedule). "
                "Returns: PURCHASEORDER (PO number), RETURN (messages). "
                "Always call BAPI_TRANSACTION_COMMIT after success. "
                "Common errors: No source of supply, missing account assignment, price unit mismatch."
            ),
            "keywords": ["bapi po create", "create purchase order api", "bapi_po_create1"],
        },
        {
            "title": "BAPI_SALESORDER_CREATEFROMDAT2 - Sales Order Creation",
            "tcode": "VA01", "module": "SD", "bapi": "BAPI_SALESORDER_CREATEFROMDAT2",
            "content": (
                "Creates sales orders via BAPI. Key parameters: ORDER_HEADER_IN (header), "
                "ORDER_ITEMS_IN (line items), ORDER_PARTNERS (sold-to, ship-to). "
                "Returns: SALESDOCUMENT (order number), RETURN (messages). "
                "Check credit limit before creation. Always commit after success."
            ),
            "keywords": ["bapi sales order", "sd api", "bapi_salesorder_createfromdat2"],
        },
        {
            "title": "BAPI_EMPLOYEE_GETDATA - Employee Master Data",
            "tcode": "PA20", "module": "HR", "bapi": "BAPI_EMPLOYEE_GETDATA",
            "content": (
                "Retrieves employee master data from HR infotypes. "
                "Key parameters: EMPLOYEENUMBER, BEGDA (start date), ENDDA (end date), INFOTYPE (optional filter). "
                "Returns data from IT0001 (org), IT0002 (personal), IT0006 (address), IT0008 (pay). "
                "Use BAPI_EMPLOYEE_ENQUEUE before updating employee records."
            ),
            "keywords": ["employee data api", "hr bapi", "bapi_employee_getdata"],
        },
    ],

    "process": [
        {
            "title": "Procure-to-Pay (P2P) Process",
            "tcode": "Multiple", "module": "MM/FI", "bapi": "Multiple",
            "content": (
                "The Procure-to-Pay process in SAP: "
                "1. Purchase Requisition (ME51N) — internal demand. "
                "2. Request for Quotation (ME41) — vendor quotes. "
                "3. Purchase Order (ME21N) — formal order to vendor. "
                "4. Goods Receipt (MIGO) — material received. "
                "5. Invoice Verification (MIRO) — 3-way match. "
                "6. Payment (F110) — automatic payment run. "
                "Key tables: EKKO (PO header), EKPO (PO items), MSEG (material doc)."
            ),
            "keywords": ["procure to pay", "p2p", "procurement process", "purchase process", "po process"],
        },
        {
            "title": "Order-to-Cash (O2C) Process",
            "tcode": "Multiple", "module": "SD/FI", "bapi": "Multiple",
            "content": (
                "The Order-to-Cash process in SAP: "
                "1. Sales Inquiry (VA11) — customer inquiry. "
                "2. Sales Quotation (VA21) — formal quote. "
                "3. Sales Order (VA01) — confirmed order. "
                "4. Delivery (VL01N) — outbound delivery. "
                "5. Goods Issue (VL02N) — stock reduced. "
                "6. Billing (VF01) — invoice to customer. "
                "7. Payment Receipt (F-28) — incoming payment. "
                "Key tables: VBAK (SO header), VBAP (SO items), LIKP (delivery header)."
            ),
            "keywords": ["order to cash", "o2c", "sales process", "billing process", "customer order process"],
        },
        {
            "title": "Employee Onboarding Process",
            "tcode": "PA40/PA30", "module": "HR", "bapi": "BAPI_EMPLOYEE_ENQUEUE",
            "content": (
                "SAP HR Employee Onboarding: "
                "1. Create personnel number (PA40, action 01 - Hire). "
                "2. Maintain IT0001 - Org Assignment (position, cost center, company code). "
                "3. Maintain IT0002 - Personal Data (name, DoB, gender). "
                "4. Maintain IT0006 - Addresses. "
                "5. Maintain IT0008 - Basic Pay (pay grade, wage type). "
                "6. IT0105 - Communication (SAP user link). "
                "7. ESS/MSS portal access provisioning. "
                "SuccessFactors: Use Onboarding module for pre-day-1 tasks."
            ),
            "keywords": ["onboarding", "hire employee", "new hire", "hr onboarding", "personnel"],
        },
        {
            "title": "Month-End Closing Process",
            "tcode": "Multiple", "module": "FI/CO", "bapi": "Multiple",
            "content": (
                "SAP FI/CO Month-End Close: "
                "1. Post all open items and accruals (F-02, FB60). "
                "2. Depreciation run (AFAB). "
                "3. GR/IR account clearing (F.13). "
                "4. Foreign currency revaluation (FAGL_FC_VAL). "
                "5. Intercompany reconciliation. "
                "6. Cost center settlement (KSV5). "
                "7. Profitability analysis (KE5T). "
                "8. Close posting period (OB52). "
                "9. Financial statements (F.01). "
                "Key: Always check open items in FBL3N before close."
            ),
            "keywords": ["month end close", "period close", "closing", "financial close", "fi closing"],
        },
        {
            "title": "MRP - Material Requirements Planning",
            "tcode": "MD01/MD02", "module": "PP/MM", "bapi": "BAPI_REQUIREMENTS_CREATE",
            "content": (
                "SAP MRP (Material Requirements Planning): "
                "1. Ensure material master MRP views are maintained (MM02). "
                "2. Check current stock (MMBE) and open POs/production orders. "
                "3. Run MRP (MD01 for plant, MD02 for single material). "
                "4. Review planned orders (MD04 - Stock Requirements List). "
                "5. Convert planned orders to POs (ME57) or production orders (CO40). "
                "MRP types: PD (standard), VB (reorder point), MK (Kanban). "
                "Key tables: PLAF (planned orders), RESB (reservations)."
            ),
            "keywords": ["mrp", "material planning", "md01", "md02", "md04", "planned orders", "requirements planning"],
        },
    ],

    "error": [
        {
            "title": "ME21N: No source of supply found",
            "tcode": "ME21N", "module": "MM", "bapi": "BAPI_PO_CREATE1",
            "content": (
                "Error: 'No source of supply found for material X'. "
                "Root cause: No info record, contract, or source list maintained. "
                "Fix: (1) Create info record (ME11) for vendor-material combination. "
                "(2) Or create outline agreement (ME31K for contract). "
                "(3) Or manually enter vendor in PO and override source. "
                "Check ME13 (info record list) and ME3M (contracts by material)."
            ),
            "keywords": ["no source of supply", "me21n error", "po error", "info record missing"],
        },
        {
            "title": "MIRO: Invoice blocked for payment",
            "tcode": "MIRO/MRBR", "module": "MM/FI", "bapi": "N/A",
            "content": (
                "Invoice blocked in MIRO due to tolerance breach in 3-way match. "
                "Types: (R) = Price variance, (Q) = Quantity variance, (D) = Date. "
                "Fix: (1) Go to MRBR to review blocked invoices. "
                "(2) Release manually if within approval authority. "
                "(3) Or correct the GR (MIGO) or PO price (ME22N) to match invoice. "
                "(4) Check tolerance limits in OMRX."
            ),
            "keywords": ["invoice blocked", "miro blocked", "3 way match", "price variance", "mrbr"],
        },
        {
            "title": "Credit block on sales order",
            "tcode": "VKM1/VKM3", "module": "SD/FI", "bapi": "N/A",
            "content": (
                "Sales order blocked due to customer credit limit exceeded. "
                "Fix: (1) Credit manager reviews in VKM1 (blocked SD documents). "
                "(2) Increase credit limit in FD32 (customer credit master). "
                "(3) Or reduce open items via incoming payment (F-28). "
                "(4) Release order in VKM3. "
                "Credit check config: OVA8 (automatic credit control)."
            ),
            "keywords": ["credit block", "credit limit", "vkm1", "fd32", "sales order blocked"],
        },
    ],

    "configuration": [
        {
            "title": "Payment Terms Configuration",
            "tcode": "OBB8", "module": "FI", "bapi": "N/A",
            "content": (
                "Configure payment terms in SAP: T-code OBB8. "
                "Payment terms define: payment due date, early payment discount (cash discount). "
                "Example: NT30 = Net 30 days. 2/10 Net 30 = 2% discount if paid in 10 days, else net 30. "
                "Assign to vendor master (XK01/XK02) in payment tab. "
                "Assign to customer master (XD01/XD02) for billing."
            ),
            "keywords": ["payment terms", "obb8", "cash discount", "net days", "vendor payment terms"],
        },
        {
            "title": "Release Strategy for Purchase Orders",
            "tcode": "OMGS/ME29N", "module": "MM", "bapi": "N/A",
            "content": (
                "Release strategy controls PO approval workflow in SAP MM. "
                "Configuration: (1) Define release groups (OMGS). "
                "(2) Define release codes (approvers). "
                "(3) Define release indicators and conditions (amount thresholds). "
                "(4) Assign strategy to PO document type. "
                "Users approve in ME29N. OMGQ shows strategy overview. "
                "Condition: e.g. PO value > 100,000 requires manager approval."
            ),
            "keywords": ["release strategy", "po approval", "me29n", "approval workflow", "purchasing approval"],
        },
    ],
}


class SAPKnowledgeBase:
    """Searchable SAP documentation index."""

    def search(self, query: str, category: str | None = None, max_results: int = 3) -> list[dict]:
        """
        Search SAP documentation by keyword query.
        Returns up to max_results matching documents.
        """
        q_words = set(re.sub(r"[^a-z0-9 ]", "", query.lower()).split())
        results = []

        categories = [category] if category and category in SAP_DOCS else list(SAP_DOCS.keys())

        for cat in categories:
            for doc in SAP_DOCS[cat]:
                # Score: count keyword matches
                kw_hits = sum(1 for kw in doc["keywords"] if any(w in kw for w in q_words))
                content_hits = sum(1 for w in q_words if w in doc["content"].lower())
                title_hits = sum(2 for w in q_words if w in doc["title"].lower())
                score = kw_hits * 3 + content_hits + title_hits

                if score > 0:
                    results.append({
                        "score": score,
                        "category": cat,
                        "title": doc["title"],
                        "tcode": doc.get("tcode", ""),
                        "module": doc.get("module", ""),
                        "bapi": doc.get("bapi", ""),
                        "content": doc["content"],
                        "keywords": doc["keywords"],
                    })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:max_results]


# Module-level singleton
_kb = SAPKnowledgeBase()


def search_sap_docs(query: str, category: str = None, max_results: int = 3) -> dict:
    """
    Tool function: Search SAP documentation.
    category options: tcode, bapi, process, error, configuration (or None for all)
    """
    if not query or not query.strip():
        return {"status": "ERROR", "message": "Query cannot be empty"}

    results = _kb.search(query, category=category, max_results=max_results)

    if not results:
        return {
            "status": "NOT_FOUND",
            "query": query,
            "message": f"No SAP documentation found for '{query}'. Try different keywords.",
            "results": [],
        }

    return {
        "status": "OK",
        "query": query,
        "category_filter": category or "all",
        "result_count": len(results),
        "results": [
            {
                "title": r["title"],
                "category": r["category"],
                "module": r["module"],
                "tcode": r["tcode"],
                "bapi": r["bapi"],
                "content": r["content"],
            }
            for r in results
        ],
    }
