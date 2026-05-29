---
name: ai-response-ui-redesign
description: Full card redesign of the AI response bubble, inline table with action buttons, and visualization intent detection (backend + frontend)
metadata:
  type: project
---

# AI Response UI Redesign — Design Spec

**Date:** 2026-05-30  
**Status:** Approved

## Summary

Three coordinated changes:
1. **Backend** — detect visualization intent and emit `show_visualization: true` in the `done` SSE event
2. **Frontend response card** — replace the flat bubble with a structured card (icon avatar, animated reasoning steps, action bar)
3. **Inline table + visualization flow** — table header with "View Larger" / "Visualize" buttons; auto-open chart modal when visualization intent is detected

---

## 1. Architecture & Data Flow

```
User types "visualize budget vs actual"
        │
        ▼
Backend /chat/stream
  ├─ keyword check: "visualize" → sets show_visualization=True
  ├─ SSE: status → "Generating chart..."
  ├─ SSE: text_delta → LLM response text
  ├─ SSE: table_start / table_rows / table_end (if data returned)
  └─ SSE: done { ..., show_visualization: true }
        │
        ▼
Frontend event handler
  ├─ done.show_visualization=true → auto-open DataViewModal (chart tab)
  └─ done.tableData → inline DataTable + action buttons
```

One new field in the `done` SSE payload: `show_visualization: bool`. No new endpoints, no DB schema changes.

---

## 2. Backend Changes (`api/server.py`)

**Location:** Top of the `/chat/stream` generator, before the intent-check cascade.

```python
_VIZ_KEYWORDS = {
    "visualize", "visualise", "chart", "plot", "graph",
    "bar chart", "pie chart", "trend", "show me a chart",
    "histogram", "scatter"
}
_show_viz = any(kw in body.message.lower() for kw in _VIZ_KEYWORDS)
```

Add `"show_visualization": _show_viz` to **every** `done` SSE yield. There are five paths:
- ABAP code generation early exit
- ABAP syntax check early exit
- Report agent early exit
- Main agent `done` event (intercepted and re-yielded)
- Error path (set to `False` here — no visualization on errors)

**Main agent path special case:** The current code re-yields `event_str` from `agent.chat_stream` unchanged via `yield event_str`. For the main path, intercept the `done` event, parse its JSON, inject `show_visualization`, and yield a rebuilt SSE string instead:

```python
if event_str.startswith("event: done"):
    # ... existing metadata extraction ...
    done_data["show_visualization"] = _show_viz
    yield f"event: done\ndata: {json.dumps(done_data, cls=_JsonEncoder)}\n\n"
    continue  # skip the original yield event_str below
yield event_str
```

No DB persistence needed — the flag is ephemeral.

---

## 3. Frontend: AI Response Card Redesign (`App.jsx`)

### 3a. Avatar

- Bot avatar: replace `"AI"` text with a small inline SVG spark/diamond icon in brand color `#0070D2`. Size 20×20, centered in the existing `.bot-av` circle.
- User avatar: unchanged (initials).

### 3b. Reasoning Steps

**During streaming** (in `StreamingMessageRow`):
- Steps render as a vertical list above the response text
- Each step: small dot indicator + muted monospace text
- Active (last) step: dot pulses with a CSS `@keyframes` animation
- Completed steps: static filled dot, slightly dimmed text
- Vertical track: a 1px left-border connecting dots

**After streaming completes** (in `MessageRow`):
- Steps collapse into a `<details>` element: summary reads `"Reasoning — N steps"`
- When expanded, same dot + text list, all dots static/filled
- Replaces the current plain `<details>` with gray dots

### 3c. Response Bubble

- Keep `MarkdownRenderer` output unchanged
- Bubble style: subtle `1px solid var(--border)` border, `var(--bg-card)` background, `var(--r-lg)` border-radius
- Remove any harsh background fill that made it look "old"
- Typography unchanged

### 3d. Action Bar

Appears **below the bubble**, only on completed bot messages (not streaming, not user messages):

```
[Copy]  [View Table ▦]  [Visualize ◈]
```

- **Copy**: always shown; copies `msg.content` to clipboard; shows "Copied!" for 1.8s (reuse existing `copied` state pattern)
- **View Table**: shown only when `msg.tableData` exists; calls `handleViewData(msg.tableData, title)`
- **Visualize**: shown only when `msg.tableData` exists; calls `handleVisualizeData(msg.tableData, title)`
- Title = first 60 chars of the user message that preceded this bot response (pass via `msg.userQuery` field set at send time)
- Buttons: small, ghost-style (`btn-ghost` class), icon + label, 12px font

### 3e. `MessageRow` — prop change

`MessageRow` needs access to `handleViewData` and `handleVisualizeData`. Pass them as props from the parent render loop. The parent `App` already has these functions.

### 3f. Streaming card

`StreamingMessageRow` gets the same card shell (avatar + step track + bubble). Action bar is hidden during streaming. No other changes.

---

## 4. Inline Table + Visualization Flow

### 4a. Inline table wrapper

Wrap the existing `DataTable` render in a new `InlineTableHeader` shell:

```
┌─ ▦ 42 records ────────────── [View Larger] [Visualize] ─┐
│  <DataTable ... />                                        │
└───────────────────────────────────────────────────────────┘
```

- Header: table icon + `"N records"` + two ghost buttons right-aligned
- **View Larger** → `handleViewData(msg.tableData, title)` → DataViewModal, table tab
- **Visualize** → `handleVisualizeData(msg.tableData, title)` → DataViewModal, chart tab
- `DataTable` component itself is unchanged

Apply to both `MessageRow` (completed) and `StreamingMessageRow` (live streaming — buttons hidden while `loading: true`).

### 4b. Auto-open chart modal

In the `done` event handler in the `sendMessage` function:

```js
if (payload.show_visualization && tableRef.current) {
  handleVisualizeData(
    { ...tableRef.current, loading: false },
    userMessage.slice(0, 60)
  )
}
```

- If `show_visualization: true` but no `tableData`: silently skip (no modal).
- If `show_visualization: true` and `tableData` present: open DataViewModal on chart tab.

### 4c. History messages

`_extractTableData` already reconstructs `tableData` for history messages. The action bar and `InlineTableHeader` buttons work identically on history messages.

---

## 5. CSS Changes (`App.css`)

New classes needed:
- `.ai-card` — card shell replacing the flat bot bubble
- `.step-track` — vertical connector for reasoning steps
- `.step-dot-active` — pulsing animation for active streaming step
- `.action-bar` — flex row for Copy / View Table / Visualize buttons
- `.btn-ghost` — small borderless button with hover state
- `.inline-table-header` — header row above DataTable

All use existing CSS variables (`--border`, `--bg-card`, `--accent`, `--text-muted`, etc.) for automatic dark-mode support.

---

## 6. Files Changed

| File | Change |
|------|--------|
| `api/server.py` | Add `_show_viz` detection; add `show_visualization` to all `done` yields |
| `frontend/src/App.jsx` | Redesign `MessageRow`, `StreamingMessageRow`; add `InlineTableHeader`; wire action bar; handle `show_visualization` in `done` handler |
| `frontend/src/App.css` | New classes for card, steps, action bar, inline table header |

No other files touched. `DataTable`, `DataVisualizer`, `DataViewModal` components are unchanged.

---

## 7. Out of Scope

- Changes to `DataTable`, `DataVisualizer`, or `DataViewModal` internals
- New backend endpoints or DB columns
- Visualization for non-tabular data (text-only responses)
- Changing the MarkdownRenderer
