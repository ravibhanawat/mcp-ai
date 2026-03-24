# SAP AI Agent — Inline Report & Visualization System

## What This Is

When a user types a natural-language query asking for a report or a specific
visualization, the system:

1. Detects the visualization intent in the chat
2. A dedicated **Report Agent** fetches + aggregates the right data from SAP modules
3. Returns a structured `report` payload alongside (or instead of) the text reply
4. The frontend renders the chosen chart **inline inside the chat bubble**

No separate dashboard. The widget appears exactly where the answer would appear.

---

## User Experience Examples

```
User: "show me open invoices by vendor as a pie chart"
  → Agent fetches open invoices, groups by vendor_name
  → Renders: pie chart inline in chat

User: "give me headcount by department as a bar chart"
  → Agent fetches employees, groups by department
  → Renders: horizontal bar chart in chat

User: "heat map of budget utilization across cost centers"
  → Agent fetches all cost centers, maps utilization_pct → color intensity
  → Renders: heat map grid in chat

User: "pivot table of production orders by status and work center"
  → Agent fetches all production orders
  → Renders: pivot table with row = status, col = work center, value = count

User: "show stock levels for all materials as a table"
  → Agent fetches materials + stock, calculates available vs reorder
  → Renders: sortable mini-table with color-coded rows in chat
```

---

## Architecture

```
User message (chat)
      │
      ▼
 /chat endpoint (api/server.py)
      │
      ├── is_report_query()? ──YES──► ReportAgent.generate()
      │                                    ├── parse intent  (LLM or rule-based)
      │                                    │     ├── what data?  (module + function)
      │                                    │     └── what view?  (pie/bar/heat/pivot/table)
      │                                    ├── fetch data from modules/*
      │                                    ├── aggregate / group / calculate
      │                                    └── return ReportPayload
      │                                          {type:"report", chart_type, title, data, config}
      │
      └── normal query ──► existing LLM chat flow
                                    │
                                    └── return {reply: "...", report: null}

ChatResponse (extended):
  {
    reply:  "Here is the open invoice breakdown by vendor:",
    report: {
      type:       "report",
      chart_type: "pie",           # pie | bar | heatmap | pivot | table
      title:      "Open Invoices by Vendor",
      data:       [...],           # chart-type-specific shape
      config:     {...}            # colors, labels, thresholds
    }
  }

Frontend (App.jsx / ReportWidget.jsx):
  MessageRow detects msg.report != null
  → renders <ReportWidget report={msg.report} />
  → dispatches to: <PieChart> | <BarChart> | <HeatMap> | <PivotTable> | <DataTable>
  → all drawn with pure SVG + CSS (zero chart libraries)
```

---

## Visualization Types & Data Shapes

### 1. Pie Chart
```json
{
  "chart_type": "pie",
  "title": "Open Invoices by Vendor",
  "data": [
    { "label": "Infosys Ltd",   "value": 3, "pct": 33.3 },
    { "label": "TCS Corp",      "value": 2, "pct": 22.2 },
    { "label": "Wipro",         "value": 4, "pct": 44.5 }
  ],
  "config": { "unit": "invoices", "value_label": "Count" }
}
```
**Rendered as:** SVG conic/arc pie with legend. Hover shows label + value + %.

---

### 2. Bar Chart (horizontal or vertical)
```json
{
  "chart_type": "bar",
  "title": "Headcount by Department",
  "data": [
    { "label": "Engineering",  "value": 45 },
    { "label": "Finance",      "value": 20 },
    { "label": "HR",           "value": 12 }
  ],
  "config": {
    "orientation": "horizontal",
    "unit": "employees",
    "color": "#0070D2"
  }
}
```
**Rendered as:** CSS flex bars with labels. Max bar = 100% width relative to max value.

---

### 3. Heat Map
```json
{
  "chart_type": "heatmap",
  "title": "Budget Utilization by Cost Center",
  "data": [
    { "id": "CC100", "label": "Finance",    "value": 67.5, "status": "normal" },
    { "id": "CC200", "label": "Sales",      "value": 92.1, "status": "critical" },
    { "id": "CC300", "label": "Production", "value": 78.0, "status": "warning" }
  ],
  "config": {
    "unit": "%",
    "thresholds": { "warning": 75, "critical": 90 },
    "low_color":  "#16a34a",
    "mid_color":  "#d97706",
    "high_color": "#dc2626"
  }
}
```
**Rendered as:** Grid of colored tiles. Color intensity = value. Label + value inside each tile.

---

### 4. Pivot Table
```json
{
  "chart_type": "pivot",
  "title": "Production Orders by Status × Work Center",
  "rows":    ["IN_PROGRESS", "PLANNED", "COMPLETED"],
  "columns": ["WC001 – Assembly", "WC002 – Painting", "WC003 – Testing"],
  "values":  [
    [3, 1, 0],
    [2, 4, 1],
    [0, 2, 6]
  ],
  "config": { "value_label": "Orders", "row_label": "Status", "col_label": "Work Center" }
}
```
**Rendered as:** HTML table, column totals, row totals, heat-tinted cells.

---

### 5. Data Table (smart, sortable)
```json
{
  "chart_type": "table",
  "title": "Stock Levels — All Materials",
  "columns": ["Material", "Description", "Available", "Reorder Point", "Status"],
  "rows": [
    ["MAT001", "Steel Sheets",  "450", "200", "ok"],
    ["MAT002", "Copper Wire",   "30",  "100", "critical"],
    ["MAT003", "Plastic Resin", "80",  "150", "warning"]
  ],
  "config": {
    "status_column": 4,
    "status_map": { "ok": "normal", "warning": "warning", "critical": "critical" }
  }
}
```
**Rendered as:** Styled table, rows color-coded by status, client-side sort by column header click.

---

## Intent Detection: How the Agent Knows What to Show

### Trigger Keywords (rule-based, no LLM needed)
```
Visualization intent = message contains any of:
  pie chart, pie graph, donut, breakdown as pie
  bar chart, bar graph, histogram, column chart
  heat map, heatmap, intensity map, color map
  pivot table, pivot, cross-tab, matrix view
  table, tabular, as a table, show as table
  chart, graph, visualize, visual, report, dashboard widget

Data intent = module keyword present:
  invoice, vendor, payable                → fi_co
  material, stock, purchase order, PO     → mm
  sales order, customer, delivery         → sd
  employee, headcount, department, HR     → hr
  production, work center, capacity       → pp
  budget, cost center, utilization        → fi_co
```

### Fallback: LLM extracts intent
If rule-based parse is ambiguous, the LLM is asked:
```
Given user query: "..."
Extract JSON: { "chart_type": "pie|bar|heatmap|pivot|table", "data_source": "invoices|employees|..." }
```

---

## Report Agent: Data Source Mapping

| User asks about           | Function called                          | Group by / aggregate          |
|---------------------------|------------------------------------------|-------------------------------|
| open invoices by vendor   | fi_co.get_open_invoices()                | group vendor_name → count     |
| budget utilization        | fi_co.list_all_cost_centers()            | each CC → utilization_pct     |
| headcount by dept         | hr.search_employees()                    | group department → count      |
| stock status              | mm.check_reorder_needed() + materials    | status tiers (ok/warn/crit)   |
| open POs by vendor        | mm.list_open_purchase_orders()           | group vendor → count          |
| sales by customer         | sd.list_open_sales_orders()              | group customer → count/value  |
| production by status      | pp.list_production_orders()              | group status → count          |
| capacity by work center   | pp.get_capacity_utilization()            | each WC → active orders       |
| invoice total by vendor   | fi_co.get_open_invoices()                | group vendor → sum(amount)    |

---

## File Plan

| File                               | Action         | Purpose                                               |
|------------------------------------|----------------|-------------------------------------------------------|
| `agent/report_agent.py`            | **CREATE**     | Intent detection, data fetch, aggregation, payload    |
| `api/server.py`                    | **EDIT** +15ln | Detect report intent in /chat, call ReportAgent       |
| `frontend/src/ReportWidget.jsx`    | **CREATE**     | PieChart, BarChart, HeatMap, PivotTable, DataTable    |
| `frontend/src/App.jsx`             | **EDIT** +5ln  | MessageRow: if msg.report → render <ReportWidget>     |
| `frontend/src/App.css`             | **EDIT** +80ln | Styles for all widget types (pure CSS, no libs)       |

**No new Python packages. No new npm packages.**
All charts: pure SVG + CSS (consistent with existing zero-library policy).

---

## Chat Response Flow (extended)

### Current `/chat` response:
```json
{ "reply": "...", "tool_used": "...", "mode": "tool_call" }
```

### Extended `/chat` response (backward-compatible):
```json
{
  "reply": "Here is the open invoice breakdown by vendor:",
  "tool_used": "get_open_invoices",
  "mode": "report",
  "report": {
    "chart_type": "pie",
    "title": "Open Invoices by Vendor",
    "data": [...],
    "config": { "unit": "invoices" }
  }
}
```
If `report` is null/absent → existing frontend behaviour unchanged.

---

## Implementation Steps (in order)

### Step 1 — `agent/report_agent.py`
- `is_report_query(text)` → bool (keyword scan)
- `detect_intent(text)` → `{ chart_type, data_source, group_by }` (rule-based + LLM fallback)
- `fetch_and_aggregate(intent)` → raw data dict
- `build_payload(chart_type, raw, title)` → `ReportPayload` dict

### Step 2 — `api/server.py`
- In `/chat` handler: before LLM call, run `is_report_query()`
- If yes: call `ReportAgent.generate(query)` → attach to response as `report` field
- `reply` = short descriptive text ("Here is X as a Y chart")

### Step 3 — `frontend/src/ReportWidget.jsx`
- `<PieChart data config>` — SVG arcs, legend below
- `<BarChart data config>` — CSS flex bars, value labels
- `<HeatMap data config>` — CSS grid, color interpolation
- `<PivotTable rows cols values config>` — table with totals + cell tinting
- `<DataTable columns rows config>` — sortable table, status row tinting
- `<ReportWidget report>` — dispatches to above

### Step 4 — `frontend/src/App.jsx`
- `MessageRow`: detect `msg.report` field
- If present: render text reply above, then `<ReportWidget report={msg.report} />`

### Step 5 — CSS
- Chart layout, SVG arc helpers, heat color gradient, pivot cell tinting, table sort arrow
