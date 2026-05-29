# AI Response UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the AI response card (avatar, animated reasoning steps, action bar), add inline table with View Larger/Visualize buttons, and auto-open the chart modal when the user's message contains visualization intent keywords.

**Architecture:** Backend detects visualization keywords and emits `show_visualization: true` in every `done` SSE event. Frontend redesigns `MessageRow` and `StreamingMessageRow` into a card layout with a bot icon, styled step track, and action bar (Copy / View Table / Visualize). A new `InlineTableHeader` component wraps the existing `DataTable` with header buttons. The `done` event handler reads `show_visualization` and auto-opens `DataViewModal` on the chart tab.

**Tech Stack:** Python / FastAPI (backend SSE), React 18 / Vite (frontend, no external UI libs), plain CSS with CSS variables.

---

## File Map

| File | What changes |
|------|-------------|
| `api/server.py` | Add `_show_viz` keyword set; inject `"show_visualization"` into 3 early-exit `done` yields (lines 876, 921, 940) and intercept + rebuild the main-agent `done` event at line 995 |
| `tests/test_agent.py` | Add `TestVizKeywords` class testing `_show_viz` logic |
| `frontend/src/App.css` | Add `.inline-table-header`, `.btn-ghost`, `.action-bar`, `.step-track`, `.step-dot-pulse` (keyframe), updated `.bot-av`, `.stream-steps-collapsed` summary style |
| `frontend/src/App.jsx` | Add `InlineTableHeader` component; redesign `MessageRow` and `StreamingMessageRow`; update `sendMessage` done handler |

---

## Task 1: Backend — add `_show_viz` detection and inject into early-exit done yields

**Files:**
- Modify: `api/server.py:833-881` (inside `event_generator()`)

- [ ] **Step 1: Add the keyword set and flag at the top of `event_generator()`**

  Find the line `async def event_generator():` (line 833). Add the following block immediately after the existing local variable declarations (after line 846 `_streamed_rows = []`):

  ```python
  # ── Visualization intent detection ────────────────────────────────────
  _VIZ_KEYWORDS = {
      "visualize", "visualise", "chart", "plot", "graph",
      "bar chart", "pie chart", "trend", "show me a chart",
      "histogram", "scatter",
  }
  _show_viz = any(kw in body.message.lower() for kw in _VIZ_KEYWORDS)
  ```

- [ ] **Step 2: Inject `show_visualization` into the ABAP code generation `done` yield (line 876)**

  Replace:
  ```python
  yield _sse("done", {
      "tool_called": tool_called, "tool_result": None,
      "sap_source": None, "report": None,
      "abap_check": None, "abap_code": abap_code_payload,
  })
  ```
  With:
  ```python
  yield _sse("done", {
      "tool_called": tool_called, "tool_result": None,
      "sap_source": None, "report": None,
      "abap_check": None, "abap_code": abap_code_payload,
      "show_visualization": False,
  })
  ```

- [ ] **Step 3: Inject into the ABAP syntax check `done` yield (line 921)**

  Replace:
  ```python
  yield _sse("done", {
      "tool_called": tool_called, "tool_result": None,
      "sap_source": None, "report": None,
      "abap_check": abap_check_payload, "abap_code": None,
  })
  ```
  With:
  ```python
  yield _sse("done", {
      "tool_called": tool_called, "tool_result": None,
      "sap_source": None, "report": None,
      "abap_check": abap_check_payload, "abap_code": None,
      "show_visualization": False,
  })
  ```

- [ ] **Step 4: Inject into the report agent `done` yield (line 940)**

  Replace:
  ```python
  yield _sse("done", {
      "tool_called": tool_called, "tool_result": None,
      "sap_source": None, "report": report_payload,
      "abap_check": None, "abap_code": None,
  })
  ```
  With:
  ```python
  yield _sse("done", {
      "tool_called": tool_called, "tool_result": None,
      "sap_source": None, "report": report_payload,
      "abap_check": None, "abap_code": None,
      "show_visualization": _show_viz,
  })
  ```

- [ ] **Step 5: Intercept and rebuild the main-agent `done` event (line 953-995)**

  Find the block starting at line 953:
  ```python
  if event_str.startswith("event: done"):
      try:
          data_line = next(l for l in event_str.split("\n") if l.startswith("data:"))
          done_data  = json.loads(data_line[5:])
          tool_called  = done_data.get("tool_called")
          tool_result  = done_data.get("tool_result")
          sap_source   = done_data.get("sap_source")
      except Exception:
          pass
  ```
  Replace with:
  ```python
  if event_str.startswith("event: done"):
      try:
          data_line = next(l for l in event_str.split("\n") if l.startswith("data:"))
          done_data  = json.loads(data_line[5:])
          tool_called  = done_data.get("tool_called")
          tool_result  = done_data.get("tool_result")
          sap_source   = done_data.get("sap_source")
          done_data["show_visualization"] = _show_viz
          yield f"event: done\ndata: {json.dumps(done_data, cls=_JsonEncoder)}\n\n"
      except Exception:
          yield event_str
      continue
  ```
  The `continue` skips the `yield event_str` at the bottom of the loop for `done` events. All other events still reach `yield event_str` unchanged.

- [ ] **Step 6: Commit**

  ```bash
  git add api/server.py
  git commit -m "feat: add show_visualization flag to all done SSE events"
  ```

---

## Task 2: Backend test — verify keyword detection logic

**Files:**
- Modify: `tests/test_agent.py`

- [ ] **Step 1: Write failing tests**

  Add this class at the bottom of `tests/test_agent.py`:

  ```python
  # ── Visualization keyword detection tests ─────────────────────────────────────
  class TestVizKeywords(unittest.TestCase):
      """Tests that _show_viz logic correctly identifies visualization intent."""

      _VIZ_KEYWORDS = {
          "visualize", "visualise", "chart", "plot", "graph",
          "bar chart", "pie chart", "trend", "show me a chart",
          "histogram", "scatter",
      }

      def _show_viz(self, message):
          return any(kw in message.lower() for kw in self._VIZ_KEYWORDS)

      def test_visualize_keyword(self):
          self.assertTrue(self._show_viz("visualize budget vs actual"))

      def test_chart_keyword(self):
          self.assertTrue(self._show_viz("Show me a chart of open POs"))

      def test_plot_keyword(self):
          self.assertTrue(self._show_viz("plot employee headcount by department"))

      def test_graph_keyword(self):
          self.assertTrue(self._show_viz("graph the cost center spend"))

      def test_bar_chart(self):
          self.assertTrue(self._show_viz("give me a bar chart of invoices"))

      def test_pie_chart(self):
          self.assertTrue(self._show_viz("pie chart of material stock"))

      def test_no_viz_intent(self):
          self.assertFalse(self._show_viz("get cost center budget for CC200"))

      def test_no_viz_intent_list(self):
          self.assertFalse(self._show_viz("list all open purchase orders"))

      def test_case_insensitive(self):
          self.assertTrue(self._show_viz("VISUALIZE the data"))
  ```

- [ ] **Step 2: Run tests to verify they pass**

  ```bash
  cd /Users/ravibhanawat/Documents/sap_ai_agent
  python -m pytest tests/test_agent.py::TestVizKeywords -v
  ```

  Expected output: 9 tests, all PASS.

- [ ] **Step 3: Commit**

  ```bash
  git add tests/test_agent.py
  git commit -m "test: add visualization keyword detection tests"
  ```

---

## Task 3: CSS — add new classes for card, steps, action bar, inline table header

**Files:**
- Modify: `frontend/src/App.css`

- [ ] **Step 1: Add all new CSS at the end of `App.css`**

  Append the following block to the very end of `frontend/src/App.css`:

  ```css
  /* ─── AI Response Card Redesign ──────────────────────────────────────────── */

  /* Bot avatar: slightly larger, brand-colored icon */
  .bot-av {
    background: #EFF6FF !important;
    border: 1.5px solid #BFDBFE !important;
    color: #0070D2 !important;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .dark .bot-av {
    background: #1e3a5f !important;
    border-color: #2563eb !important;
  }

  /* ─── Reasoning step track ──────────────────────────────────────────────── */
  .step-track {
    display: flex;
    flex-direction: column;
    gap: 0;
    margin-bottom: 10px;
    padding-left: 2px;
  }

  .step-track-item {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    position: relative;
    padding: 3px 0 3px 0;
  }

  .step-track-item:not(:last-child)::after {
    content: '';
    position: absolute;
    left: 5px;
    top: 18px;
    bottom: -6px;
    width: 1px;
    background: var(--border);
  }

  .step-dot-wrap {
    flex-shrink: 0;
    width: 12px;
    height: 12px;
    margin-top: 3px;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .step-dot-done {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--accent, #0070D2);
    opacity: 0.6;
  }

  .step-dot-active {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--accent, #0070D2);
    animation: stepPulse 1.2s ease-in-out infinite;
  }

  @keyframes stepPulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50%       { opacity: 0.4; transform: scale(0.75); }
  }

  .step-track-text {
    font-size: 11.5px;
    font-family: var(--font-mono, monospace);
    color: var(--text-muted);
    line-height: 1.5;
  }

  .step-track-text.active {
    color: var(--text-secondary);
  }

  /* Collapsed reasoning steps summary — improved over old version */
  .stream-steps-collapsed {
    margin-bottom: 8px;
    border: 1px solid var(--border);
    border-radius: var(--r-md, 6px);
    background: var(--bg-subtle, var(--bg-card));
    overflow: hidden;
  }

  .stream-steps-collapsed summary {
    cursor: pointer;
    font-size: 11.5px;
    font-weight: 600;
    color: var(--text-muted);
    padding: 6px 10px;
    list-style: none;
    display: flex;
    align-items: center;
    gap: 6px;
    user-select: none;
  }

  .stream-steps-collapsed summary::before {
    content: '›';
    font-size: 14px;
    transition: transform 0.15s;
    display: inline-block;
  }

  .stream-steps-collapsed[open] summary::before {
    transform: rotate(90deg);
  }

  .stream-steps-collapsed .step-track {
    padding: 4px 10px 8px 10px;
    margin-bottom: 0;
    border-top: 1px solid var(--border);
  }

  /* ─── Action bar ────────────────────────────────────────────────────────── */
  .action-bar {
    display: flex;
    align-items: center;
    gap: 4px;
    margin-top: 8px;
    flex-wrap: wrap;
  }

  .btn-ghost {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 9px;
    font-size: 11.5px;
    font-weight: 500;
    color: var(--text-muted);
    background: transparent;
    border: 1px solid transparent;
    border-radius: var(--r-md, 6px);
    cursor: pointer;
    transition: background 0.12s, color 0.12s, border-color 0.12s;
    white-space: nowrap;
  }

  .btn-ghost:hover {
    background: var(--bg-subtle, #f4f4f5);
    border-color: var(--border);
    color: var(--text-primary);
  }

  .dark .btn-ghost:hover {
    background: rgba(255,255,255,0.06);
  }

  .btn-ghost.copied {
    color: var(--success, #16a34a);
  }

  /* ─── Inline table header ───────────────────────────────────────────────── */
  .inline-table-header {
    margin-top: 12px;
  }

  .inline-table-bar {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 10px;
    background: var(--bg-subtle, #f8f9fa);
    border: 1px solid var(--border);
    border-bottom: none;
    border-radius: var(--r-md, 6px) var(--r-md, 6px) 0 0;
    font-size: 12px;
    color: var(--text-muted);
  }

  .dark .inline-table-bar {
    background: rgba(255,255,255,0.04);
  }

  .inline-table-bar-count {
    flex: 1;
    font-weight: 600;
    color: var(--text-secondary);
  }

  .inline-table-bar .btn-ghost {
    font-size: 11px;
    padding: 2px 7px;
  }

  /* Make DataTable inside InlineTableHeader flush with header */
  .inline-table-header .dt-wrap {
    border-top-left-radius: 0;
    border-top-right-radius: 0;
  }
  ```

- [ ] **Step 2: Verify no syntax errors**

  ```bash
  cd /Users/ravibhanawat/Documents/sap_ai_agent/frontend
  npm run build 2>&1 | tail -20
  ```

  Expected: build succeeds (exit 0). CSS parse errors show as warnings/errors in the output.

- [ ] **Step 3: Commit**

  ```bash
  git add frontend/src/App.css
  git commit -m "style: add card, step-track, action-bar, inline-table CSS classes"
  ```

---

## Task 4: Frontend — add `InlineTableHeader` component

**Files:**
- Modify: `frontend/src/App.jsx` — add `InlineTableHeader` component after the `DataTable` component (after line 475)

- [ ] **Step 1: Add `InlineTableHeader` component**

  Find the line `// ─── getNumericColumns Helper ──────────────────────────────────────────────` (around line 477). Insert the following component **before** that line:

  ```jsx
  // ─── InlineTableHeader ───────────────────────────────────────────────────────
  // Wraps DataTable with a header bar showing record count + action buttons.

  function InlineTableHeader({ tableData, onViewData, onVisualizeData, userQuery, loading }) {
    const count = tableData?.total ?? tableData?.rows?.length ?? 0
    const title = (userQuery || '').slice(0, 60) || 'Data'
    const canAct = !loading && tableData?.rows?.length > 0

    return (
      <div className="inline-table-header">
        <div className="inline-table-bar">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <rect width="18" height="18" x="3" y="3" rx="2" />
            <path d="M3 9h18" /><path d="M9 21V9" />
          </svg>
          <span className="inline-table-bar-count">
            {loading ? `Loading… ${tableData?.rows?.length ?? 0} rows` : `${count} record${count !== 1 ? 's' : ''}`}
          </span>
          {canAct && onViewData && (
            <button className="btn-ghost" onClick={() => onViewData(tableData, title)}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
              </svg>
              View Larger
            </button>
          )}
          {canAct && onVisualizeData && (
            <button className="btn-ghost" onClick={() => onVisualizeData(tableData, title)}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/>
              </svg>
              Visualize
            </button>
          )}
        </div>
        <DataTable
          columns={tableData.columns}
          rows={tableData.rows}
          total={tableData.total}
          loading={loading}
        />
      </div>
    )
  }
  ```

- [ ] **Step 2: Build to verify no syntax errors**

  ```bash
  cd /Users/ravibhanawat/Documents/sap_ai_agent/frontend
  npm run build 2>&1 | tail -10
  ```

  Expected: exit 0, no errors.

- [ ] **Step 3: Commit**

  ```bash
  git add frontend/src/App.jsx
  git commit -m "feat: add InlineTableHeader component with View Larger and Visualize buttons"
  ```

---

## Task 5: Frontend — redesign `MessageRow`

**Files:**
- Modify: `frontend/src/App.jsx:1062-1111`

- [ ] **Step 1: Add the Clavis bot icon to the `Icons` map**

  Find the `Icons` object (around line 124). Add a `clavis` entry at the end, before the closing `}`:

  ```jsx
  clavis: () => (
    <Svg size={18}>
      <path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" />
    </Svg>
  ),
  ```

- [ ] **Step 2: Replace the entire `MessageRow` function**

  Find `function MessageRow({ msg }) {` (line 1064) and replace the entire function through its closing `}` (line 1111) with:

  ```jsx
  function MessageRow({ msg, onViewData, onVisualizeData }) {
    const [copied, setCopied] = useState(false)
    const isUser = msg.role === 'user'

    const doCopy = () => {
      navigator.clipboard.writeText(msg.content || '')
      setCopied(true)
      setTimeout(() => setCopied(false), 1800)
    }

    const title = (msg.userQuery || '').slice(0, 60) || 'Data'

    return (
      <div className={`msg-row ${isUser ? 'user' : 'bot'}`}>
        <div className={`msg-avatar ${isUser ? 'user-av' : 'bot-av'}`}>
          {isUser
            ? (msg.userInitial || 'U')
            : msg.research_mode
              ? <Icons.beaker />
              : <Icons.clavis />
          }
        </div>
        <div className="msg-body">

          {/* Reasoning steps — collapsed details with styled step track */}
          {!isUser && msg.status_steps?.length > 0 && (
            <details className="stream-steps-collapsed">
              <summary>Reasoning — {msg.status_steps.length} step{msg.status_steps.length !== 1 ? 's' : ''}</summary>
              <div className="step-track">
                {msg.status_steps.map((s, i) => (
                  <div key={i} className="step-track-item">
                    <div className="step-dot-wrap"><div className="step-dot-done" /></div>
                    <span className="step-track-text">{s}</span>
                  </div>
                ))}
              </div>
            </details>
          )}

          {/* Message content */}
          {msg.research_mode ? (
            <ResearchReport result={msg.research_result} />
          ) : isUser ? (
            <div className="msg-bubble">{msg.content}</div>
          ) : (
            <div className="msg-bubble md-bubble">
              <MarkdownRenderer content={msg.content} />
            </div>
          )}

          {/* Meta badges */}
          <div className="msg-meta">
            {msg.research_mode && <span className="badge badge-research">AUTO RESEARCH</span>}
          </div>

          {/* SAP source */}
          {!msg.research_mode && msg.sap_source && <SapSourceBadge source={msg.sap_source} />}

          {/* Inline table */}
          {msg.tableData && (
            <InlineTableHeader
              tableData={msg.tableData}
              onViewData={onViewData}
              onVisualizeData={onVisualizeData}
              userQuery={msg.userQuery}
              loading={false}
            />
          )}

          {/* Other widgets */}
          {msg.report && <ReportWidget report={msg.report} />}
          {msg.abap_check && <AbapReviewWidget abap_check={msg.abap_check} />}
          {msg.abap_code && <AbapCodeWidget abap_code={msg.abap_code} />}
          {msg.tool_result && (msg.tool_result.outstanding_items || msg.tool_result.park_reference) && (
            <ReceiptWidget initialData={msg.tool_result.outstanding_items ? msg.tool_result : null} />
          )}
          {(msg.tool_called === "autonomous_agent" || msg.tool_called === "action_plan" || msg.action_plan) && (
            <Plan planData={msg.action_plan} />
          )}

          {/* Action bar — bot messages only */}
          {!isUser && (
            <div className="action-bar">
              <button className={`btn-ghost ${copied ? 'copied' : ''}`} onClick={doCopy}>
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>
                </svg>
                {copied ? 'Copied!' : 'Copy'}
              </button>
              {msg.tableData && onViewData && (
                <button className="btn-ghost" onClick={() => onViewData(msg.tableData, title)}>
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18"/><path d="M9 21V9"/>
                  </svg>
                  View Table
                </button>
              )}
              {msg.tableData && onVisualizeData && (
                <button className="btn-ghost" onClick={() => onVisualizeData(msg.tableData, title)}>
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/>
                  </svg>
                  Visualize
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    )
  }
  ```

- [ ] **Step 3: Build to verify no errors**

  ```bash
  cd /Users/ravibhanawat/Documents/sap_ai_agent/frontend
  npm run build 2>&1 | tail -10
  ```

  Expected: exit 0.

- [ ] **Step 4: Commit**

  ```bash
  git add frontend/src/App.jsx
  git commit -m "feat: redesign MessageRow with icon avatar, step track, and action bar"
  ```

---

## Task 6: Frontend — redesign `StreamingMessageRow`

**Files:**
- Modify: `frontend/src/App.jsx:1591-1630`

- [ ] **Step 1: Replace the entire `StreamingMessageRow` function**

  Find `function StreamingMessageRow({ msg }) {` (line 1593) and replace through its closing `}` (line 1630) with:

  ```jsx
  function StreamingMessageRow({ msg, onViewData, onVisualizeData }) {
    return (
      <div className="msg-row bot">
        <div className="msg-avatar bot-av">
          <Icons.clavis />
        </div>
        <div className="msg-body">

          {/* Animated reasoning step track */}
          {msg.status_steps.length > 0 && (
            <div className="step-track">
              {msg.status_steps.map((step, i) => {
                const isActive = i === msg.status_steps.length - 1
                return (
                  <div key={i} className="step-track-item">
                    <div className="step-dot-wrap">
                      <div className={isActive ? 'step-dot-active' : 'step-dot-done'} />
                    </div>
                    <span className={`step-track-text ${isActive ? 'active' : ''}`}>{step}</span>
                  </div>
                )
              })}
            </div>
          )}

          {/* Streaming content */}
          {msg.content ? (
            <div className="msg-bubble" style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
              {msg.content}
            </div>
          ) : (
            <div className="stream-thinking">
              <ShiningText text="clavis is thinking..." />
            </div>
          )}

          {/* Live table (no action buttons while loading) */}
          {msg.tableData && (
            <InlineTableHeader
              tableData={msg.tableData}
              onViewData={onViewData}
              onVisualizeData={onVisualizeData}
              loading={msg.tableData.loading}
            />
          )}

          {(msg.tool_called === "autonomous_agent" || msg.tool_called === "action_plan" || msg.action_plan) && (
            <Plan planData={msg.action_plan} />
          )}
        </div>
      </div>
    )
  }
  ```

- [ ] **Step 2: Build to verify no errors**

  ```bash
  cd /Users/ravibhanawat/Documents/sap_ai_agent/frontend
  npm run build 2>&1 | tail -10
  ```

  Expected: exit 0.

- [ ] **Step 3: Commit**

  ```bash
  git add frontend/src/App.jsx
  git commit -m "feat: redesign StreamingMessageRow with icon avatar and animated step track"
  ```

---

## Task 7: Frontend — update `sendMessage` done handler

**Files:**
- Modify: `frontend/src/App.jsx` — the `sendMessage` useCallback

**Context:** `sendMessage` is a `useCallback` that starts with `const sendMessage = useCallback(async (text) => {`. The `done` event handler is the `else if (eventType === 'done')` block around line 3029. The user's message text is captured in `const msg = text.trim()` at the top of the callback (line 2930).

- [ ] **Step 1: Add `userQuery` to `finalMsg` and handle `show_visualization`**

  Find the `else if (eventType === 'done')` block. It currently reads:

  ```js
  } else if (eventType === 'done') {
    if (rafRef.current) { cancelAnimationFrame(rafRef.current); rafRef.current = null }
    if (tableRafRef.current) { cancelAnimationFrame(tableRafRef.current); tableRafRef.current = null }
    const finalMsg = {
      role: 'bot',
      content: streamingRef.current.content,
      status_steps: streamingRef.current.status_steps,
      tool_called: payload.tool_called || null,
      tool_result: payload.tool_result || null,
      sap_source: payload.sap_source || null,
      report: payload.report || null,
      abap_check: payload.abap_check || null,
      abap_code: payload.abap_code || null,
      tableData: tableRef.current ? { ...tableRef.current, loading: false } : null,
    }
    setStreamingMsg(null)
    setMessages(p => [...p, finalMsg])
    loadConversations()
  ```

  Replace with:

  ```js
  } else if (eventType === 'done') {
    if (rafRef.current) { cancelAnimationFrame(rafRef.current); rafRef.current = null }
    if (tableRafRef.current) { cancelAnimationFrame(tableRafRef.current); tableRafRef.current = null }
    const finalTableData = tableRef.current ? { ...tableRef.current, loading: false } : null
    const finalMsg = {
      role: 'bot',
      content: streamingRef.current.content,
      status_steps: streamingRef.current.status_steps,
      tool_called: payload.tool_called || null,
      tool_result: payload.tool_result || null,
      sap_source: payload.sap_source || null,
      report: payload.report || null,
      abap_check: payload.abap_check || null,
      abap_code: payload.abap_code || null,
      tableData: finalTableData,
      userQuery: msg,
    }
    setStreamingMsg(null)
    setMessages(p => [...p, finalMsg])
    if (payload.show_visualization && finalTableData) {
      setModalData({ ...finalTableData, title: msg.slice(0, 60) })
      setModalTab('chart')
      setShowDataModal(true)
    }
    loadConversations()
  ```

- [ ] **Step 2: Build to verify no errors**

  ```bash
  cd /Users/ravibhanawat/Documents/sap_ai_agent/frontend
  npm run build 2>&1 | tail -10
  ```

  Expected: exit 0.

- [ ] **Step 3: Commit**

  ```bash
  git add frontend/src/App.jsx
  git commit -m "feat: add userQuery to finalMsg and auto-open chart modal on show_visualization"
  ```

---

## Task 8: Manual end-to-end verification

Start the backend and frontend, then run through the golden path and edge cases.

- [ ] **Step 1: Start the backend**

  ```bash
  cd /Users/ravibhanawat/Documents/sap_ai_agent
  source .venv/bin/activate
  python main.py
  ```

  Expected: server starts on port 8000, no import errors.

- [ ] **Step 2: Start the frontend dev server**

  ```bash
  cd /Users/ravibhanawat/Documents/sap_ai_agent/frontend
  npm run dev
  ```

  Expected: Vite serves on http://localhost:5173 (or similar).

- [ ] **Step 3: Verify the new bot avatar**

  Log in and send any message. Check that the bot avatar shows the star/diamond icon instead of the "AI" text label.

- [ ] **Step 4: Verify reasoning steps track**

  Ask: `"What is the budget for CC100?"` — this triggers a tool call and emits status steps.
  - During streaming: should see animated pulsing dot on the active step, static dots on completed steps, monospace text in a vertical track.
  - After response: steps collapse into a `<details>` with summary "Reasoning — N steps". Click to expand and verify the same dot + text list appears.

- [ ] **Step 5: Verify action bar**

  After a bot response arrives, check for the action bar below the bubble:
  - "Copy" button should appear. Click it — verify it says "Copied!" briefly and the content is on clipboard.
  - If no table data: only "Copy" shows (no View Table / Visualize).

- [ ] **Step 6: Verify inline table + header buttons**

  Ask: `"List all employees"` or `"Show open purchase orders"` — these return array data.
  - Verify the inline table renders with the new `InlineTableHeader` bar at the top.
  - Bar shows record count (e.g., "5 records").
  - "View Larger" button opens `DataViewModal` on the Table tab.
  - "Visualize" button opens `DataViewModal` on the Chart tab.
  - In the action bar below the bubble, "View Table" and "Visualize" buttons also appear and open the modal correctly.

- [ ] **Step 7: Verify visualization auto-open**

  Ask: `"Visualize the budget vs actual for all cost centers"` or `"Show me a chart of open invoices"`.
  - Response should stream normally.
  - On completion, `DataViewModal` should open automatically on the Chart tab if the tool returned array data.
  - If the tool returns no data (text-only response): modal should NOT open.

- [ ] **Step 8: Verify dark mode**

  Toggle dark mode (if the theme toggle exists in the UI). Verify:
  - Bot avatar background is dark blue, not white.
  - `btn-ghost` hover uses the dark hover color.
  - `inline-table-bar` background is the dark subtle variant.

- [ ] **Step 9: Commit verification note**

  ```bash
  git tag v-ui-redesign-verified
  ```

---

## Self-Review Checklist

| Spec requirement | Covered in task |
|---|---|
| Backend: `_VIZ_KEYWORDS` set | Task 1, Step 1 |
| Backend: `_show_viz` flag computed | Task 1, Step 1 |
| Backend: ABAP code gen done yield | Task 1, Step 2 |
| Backend: ABAP syntax check done yield | Task 1, Step 3 |
| Backend: Report agent done yield | Task 1, Step 4 |
| Backend: Main-agent done intercepted + rebuilt | Task 1, Step 5 |
| Backend test: keyword detection | Task 2 |
| CSS: new classes | Task 3 |
| `InlineTableHeader` component | Task 4 |
| `MessageRow`: Clavis icon avatar | Task 5, Step 2 |
| `MessageRow`: step track (collapsed details) | Task 5, Step 2 |
| `MessageRow`: action bar (Copy, View Table, Visualize) | Task 5, Step 2 |
| `MessageRow`: `InlineTableHeader` replaces raw DataTable | Task 5, Step 2 |
| `StreamingMessageRow`: Clavis icon avatar | Task 6, Step 1 |
| `StreamingMessageRow`: animated step track | Task 6, Step 1 |
| `StreamingMessageRow`: `InlineTableHeader` | Task 6, Step 1 |
| `sendMessage`: `userQuery` in `finalMsg` | Task 7, Step 1 |
| `sendMessage`: auto-open chart modal on `show_visualization` | Task 7, Step 1 |
| History messages: action bar works via `_extractTableData` | Covered — `_extractTableData` already runs; `userQuery` absent so title falls back to `'Data'` — acceptable |
| Dark mode compatibility | Task 3 CSS uses vars; Task 8, Step 8 |
