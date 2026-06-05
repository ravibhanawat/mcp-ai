# SAP AI Agent Chat UI Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Overhaul the sap_ai_agent chat interface from a monolithic App.jsx (172KB) into modular components with Zustand state, typed SSE events, a resizable side data panel, animated phase stepper, and clarification loop — modeled on sap_warn patterns.

**Architecture:** Incremental extraction (Option B) — existing features stay working at every step. Zustand store + SSE libs are created first as a foundation layer, then the backend is updated to emit typed events, then App.jsx is wired to the store, then components are extracted one by one, and finally App.jsx is slimmed to a thin orchestrator.

**Tech Stack:** React 19 + Vite + Zustand 5, FastAPI + Python, plain JSX (no TypeScript), no new UI library.

---

## File Map

**Create:**
- `frontend/src/stores/chat-store.js` — Zustand store (all chat state)
- `frontend/src/lib/sse-parser.js` — raw SSE stream → typed event objects
- `frontend/src/lib/ask-stream.js` — POST /chat/stream, dispatch events to store
- `frontend/src/lib/api.js` — REST calls: conversations, history
- `frontend/src/components/chat/PhaseStepper.jsx` — animated pipeline phase track
- `frontend/src/components/chat/MessageRow.jsx` — completed message bubble
- `frontend/src/components/chat/StreamingMessageRow.jsx` — in-flight message
- `frontend/src/components/chat/ClarificationSheet.jsx` — pause/resume clarification modal
- `frontend/src/components/data/DataPanel.jsx` — resizable side panel container
- `frontend/src/components/data/DataTable.jsx` — paginated sortable table (extracted)
- `frontend/src/components/data/DataVisualizer.jsx` — bar/pie charts (extracted)
- `frontend/src/components/layout/Sidebar.jsx` — conversation history
- `frontend/src/components/layout/Header.jsx` — title + model label + live dot

**Modify:**
- `frontend/package.json` — add zustand
- `frontend/src/App.jsx` — wire store, remove extracted code, slim to ~200 lines
- `api/server.py` — typed SSE events, clarification_answer field, rows summary event
- `agent/sap_agent.py` — rename text_delta→answer, standardize phases, add intent + clarify events

---

## Task 1: Install Zustand + Create Chat Store

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/src/stores/chat-store.js`

- [ ] **Step 1: Install zustand**

```bash
cd frontend && npm install zustand
```

Expected output: `added 1 package` (zustand has zero dependencies)

- [ ] **Step 2: Create the store file**

Create `frontend/src/stores/chat-store.js`:

```js
import { create } from 'zustand'

const useChatStore = create((set, get) => ({
  // ── Conversation list ──────────────────────────────────────────────────────
  conversations: [],
  currentConversationId: null,

  // ── Message history ────────────────────────────────────────────────────────
  // Each message: { id, role: 'user'|'assistant', content, phases, rows, done, error }
  messages: [],

  // ── Active stream state (reset on each new send) ───────────────────────────
  isRunning: false,
  currentPhase: null,       // 'routing_query' | 'calling_tool' | 'processing' | 'streaming_answer'
  streamingAnswer: '',      // accumulated answer delta text
  currentRows: null,        // { columns, rows, row_count, truncated } when rows event arrives
  clarification: null,      // { question, options[] } when clarify event arrives
  intentInfo: null,         // { modules, confidence }
  lastDone: null,           // { tokens, model, duration_ms, conversation_id }
  streamError: null,

  // ── Side data panel ────────────────────────────────────────────────────────
  dataPanel: null,          // null=hidden | { mode: 'data'|'chart', rows, title }

  // ── Primitive setters ──────────────────────────────────────────────────────
  setIsRunning: (v) => set({ isRunning: v }),
  setCurrentPhase: (phase) => set({ currentPhase: phase }),
  appendAnswer: (delta) => set((s) => ({ streamingAnswer: s.streamingAnswer + delta })),
  setCurrentRows: (rows) => set({ currentRows: rows }),
  setClarification: (clarification) => set({ clarification }),
  setIntentInfo: (intentInfo) => set({ intentInfo }),
  setLastDone: (done) => set({ lastDone: done }),
  setStreamError: (error) => set({ streamError: error }),
  setDataPanel: (panel) => set({ dataPanel: panel }),
  setMessages: (messages) => set({ messages }),
  setConversations: (conversations) => set({ conversations }),
  setCurrentConversationId: (id) => set({ currentConversationId: id }),

  // ── resetStreamState ───────────────────────────────────────────────────────
  // Call before each new sendMessage to clear previous turn's state.
  resetStreamState: () => set({
    isRunning: false,
    currentPhase: null,
    streamingAnswer: '',
    currentRows: null,
    clarification: null,
    intentInfo: null,
    lastDone: null,
    streamError: null,
  }),

  // ── addMessage ─────────────────────────────────────────────────────────────
  addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),

  // ── finalizeTurn ───────────────────────────────────────────────────────────
  // Called on 'done' event. Moves streaming state into a permanent message object.
  finalizeTurn: () => {
    const s = get()
    const assistantMsg = {
      id: `asst-${Date.now()}`,
      role: 'assistant',
      content: s.streamingAnswer,
      rows: s.currentRows || null,
      done: s.lastDone || null,
      phases: [],
    }
    set((prev) => ({ messages: [...prev.messages, assistantMsg] }))
  },
}))

export default useChatStore
```

- [ ] **Step 3: Verify the store imports cleanly**

In `frontend/src/main.jsx`, add a temporary import at the top to verify no syntax errors:
```js
import useChatStore from './stores/chat-store.js'
console.log('store keys:', Object.keys(useChatStore.getState()))
```

Run `npm run dev` in `/frontend`. Open browser console — you should see `store keys: [conversations, currentConversationId, messages, ...]`. Remove the console.log after verifying.

- [ ] **Step 4: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/stores/chat-store.js
git commit -m "feat: add Zustand chat store foundation"
```

---

## Task 2: Create SSE Parser + Ask-Stream Library

**Files:**
- Create: `frontend/src/lib/sse-parser.js`
- Create: `frontend/src/lib/ask-stream.js`

- [ ] **Step 1: Create the SSE parser**

Create `frontend/src/lib/sse-parser.js`:

```js
/**
 * Async generator that reads a fetch() Response.body stream and yields
 * typed event objects: { type: string, payload: object }
 *
 * Handles SSE frame format:
 *   event: <type>\n
 *   data: <json>\n
 *   \n
 */
export async function* parseSSE(response) {
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    // Frames are separated by double newline
    const frames = buffer.split('\n\n')
    buffer = frames.pop() // last element may be an incomplete frame

    for (const frame of frames) {
      if (!frame.trim()) continue
      let eventType = 'message'
      let data = ''
      for (const line of frame.split('\n')) {
        if (line.startsWith('event: ')) eventType = line.slice(7).trim()
        else if (line.startsWith('data: ')) data = line.slice(6).trim()
      }
      if (!data) continue
      try {
        yield { type: eventType, payload: JSON.parse(data) }
      } catch {
        // skip malformed frame silently
      }
    }
  }
}
```

- [ ] **Step 2: Create ask-stream.js**

Create `frontend/src/lib/ask-stream.js`:

```js
import { parseSSE } from './sse-parser.js'
import useChatStore from '../stores/chat-store.js'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

/**
 * Sends a message to /chat/stream, dispatches typed SSE events to the
 * Zustand chat store, and handles token refresh on 401.
 *
 * Options:
 *   token              - current JWT access token
 *   refreshToken       - refresh token (passed to onTokenRefresh if 401)
 *   onTokenRefresh     - async fn() → new token string | null
 *   sessionId          - chat session identifier (default: 'default')
 *   clarificationAnswer - string | null, set when resuming after clarify event
 */
export async function sendMessage(
  text,
  { token, refreshToken, onTokenRefresh, sessionId = 'default', clarificationAnswer = null } = {}
) {
  const store = useChatStore.getState()
  store.resetStreamState()
  store.setIsRunning(true)

  // Add user message to history immediately (optimistic)
  store.addMessage({ id: `user-${Date.now()}`, role: 'user', content: text })

  const body = { message: text, model: 'llama3.2', session_id: sessionId }
  if (clarificationAnswer) body.clarification_answer = clarificationAnswer

  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }

  let res = await fetch(`${API}/chat/stream`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  })

  // Token refresh on 401
  if (res.status === 401 && onTokenRefresh) {
    const newToken = await onTokenRefresh()
    if (!newToken) {
      store.setIsRunning(false)
      return
    }
    res = await fetch(`${API}/chat/stream`, {
      method: 'POST',
      headers: { ...headers, Authorization: `Bearer ${newToken}` },
      body: JSON.stringify(body),
    })
  }

  if (!res.ok) {
    store.setStreamError(`Request failed (${res.status}). Please try again.`)
    store.setIsRunning(false)
    return
  }

  try {
    for await (const { type, payload } of parseSSE(res)) {
      switch (type) {
        case 'status':
          store.setCurrentPhase(payload.phase)
          break

        case 'intent':
          store.setIntentInfo({ modules: payload.modules, confidence: payload.confidence })
          break

        case 'answer':
          store.appendAnswer(payload.delta)
          break

        case 'rows':
          store.setCurrentRows(payload)
          store.setDataPanel({ mode: 'data', rows: payload, title: payload.tool || 'Query Results' })
          break

        case 'clarify':
          store.setClarification({ question: payload.question, options: payload.options })
          // Stream ends here; ClarificationSheet will be shown by App.jsx
          store.setIsRunning(false)
          return

        case 'done':
          store.setLastDone(payload)
          store.finalizeTurn()
          store.resetStreamState()
          break

        case 'error':
          store.setStreamError(payload.message)
          break

        // Legacy event names — kept for backward compat during transition
        case 'text_delta':
          store.appendAnswer(payload.delta)
          break
        case 'table_end':
          // rows event will follow; table_start/table_rows handled by StreamingMessageRow
          break
      }
    }
  } catch (err) {
    store.setStreamError('Connection lost. Please try again.')
  } finally {
    store.setIsRunning(false)
  }
}
```

- [ ] **Step 3: Verify no import errors**

Add temporary import to `frontend/src/main.jsx`:
```js
import { sendMessage } from './lib/ask-stream.js'
console.log('ask-stream loaded:', typeof sendMessage)
```

Run `npm run dev`. Browser console should show `ask-stream loaded: function`. Remove console.log.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/sse-parser.js frontend/src/lib/ask-stream.js
git commit -m "feat: add SSE parser and ask-stream library"
```

---

## Task 3: Update Backend — Typed SSE Events + Clarification Support

**Files:**
- Modify: `api/server.py` — add clarification_answer to ChatRequest, emit `rows` summary event, standardize phase names, rename text_delta→answer
- Modify: `agent/sap_agent.py` — rename text_delta→answer, standardize phases, add intent event, add clarify support

- [ ] **Step 1: Add clarification_answer to ChatRequest in server.py**

Find `class ChatRequest(BaseModel):` at line ~355 in `api/server.py` and add one field:

```python
class ChatRequest(BaseModel):
    message: str
    model: str = "llama3.2"
    session_id: str = "default"
    clarification_answer: str | None = None   # ← ADD THIS LINE
```

- [ ] **Step 2: Pass clarification_answer to agent.chat_stream in server.py**

Find the line `async for event_str in agent.chat_stream(body.message, allowed_tools=allowed_tools):` (around line 961 in server.py) and update it:

```python
async for event_str in agent.chat_stream(
    body.message,
    allowed_tools=allowed_tools,
    clarification_answer=body.clarification_answer,
):
```

- [ ] **Step 3: Add _streamed_columns tracking in server.py**

Find `_streamed_rows = []` (around line 846 in server.py) and add a columns tracker beside it:

```python
_streamed_rows     = []
_streamed_columns  = []    # ← ADD THIS LINE
```

Find the `elif event_str.startswith("event: table_rows"):` block and, just above it, add handling for `table_start`:

```python
elif event_str.startswith("event: table_start"):
    try:
        data_line = next(l for l in event_str.split("\n") if l.startswith("data:"))
        _streamed_columns = json.loads(data_line[5:]).get("columns", [])
    except Exception:
        pass
elif event_str.startswith("event: table_rows"):
    try:
        data_line = next(l for l in event_str.split("\n") if l.startswith("data:"))
        _streamed_rows.extend(json.loads(data_line[5:]).get("rows", []))
    except Exception:
        pass
```

Find `elif event_str.startswith("event: table_end"):` — add a `rows` summary event emission after it passes through:

```python
elif event_str.startswith("event: table_end"):
    yield event_str   # pass through table_end as before
    # Also emit a typed 'rows' summary for the new frontend
    if _streamed_columns or _streamed_rows:
        yield _sse("rows", {
            "columns": _streamed_columns,
            "rows": _streamed_rows,
            "row_count": len(_streamed_rows),
            "truncated": False,
        })
    continue  # skip the default yield event_str at the bottom
```

- [ ] **Step 4: Rename text_delta → answer in server.py**

In `server.py`, do a global replace of `_sse("text_delta",` with `_sse("answer",`:

```bash
sed -i '' 's/_sse("text_delta",/_sse("answer",/g' api/server.py
```

Verify: `grep -n 'text_delta' api/server.py` should return zero results.

- [ ] **Step 5: Standardize phase names in server.py**

In server.py, replace the existing phase string values:

```bash
sed -i '' 's/"phase": "tool_call"/"phase": "calling_tool"/g' api/server.py
sed -i '' 's/"phase": "routing"/"phase": "routing_query"/g' api/server.py
sed -i '' 's/"phase": "llm_routing"/"phase": "routing_query"/g' api/server.py
sed -i '' 's/"phase": "formatting"/"phase": "processing"/g' api/server.py
sed -i '' 's/"phase": "conversational"/"phase": "streaming_answer"/g' api/server.py
```

- [ ] **Step 6: Update done payload in server.py to include duration_ms and model**

Find every `yield _sse("done", {` block in server.py that computes the done payload (around line ~1025-1050). Add `duration_ms` and `model` to each done payload. They already have `t_start`. Example of the main done payload block (search for `t_start` near yield _sse("done")):

```python
yield _sse("done", {
    "tool_called":   tool_called,
    "tool_result":   tool_result,
    "sap_source":    sap_source,
    "report":        report_payload,
    "abap_check":    abap_check_payload,
    "abap_code":     abap_code_payload,
    "show_visualization": _show_viz,
    "duration_ms":   int((time.monotonic() - t_start) * 1000),  # ← ADD
    "model":         body.model,                                  # ← ADD
})
```

There are several done yields in server.py (for ABAP, report, and main path). Add `duration_ms` and `model` to all of them using the same pattern.

- [ ] **Step 7: Update sap_agent.py — rename text_delta → answer and standardize phases**

```bash
sed -i '' 's/_sse("text_delta",/_sse("answer",/g' agent/sap_agent.py
sed -i '' 's/"phase": "tool_call"/"phase": "calling_tool"/g' agent/sap_agent.py
sed -i '' 's/"phase": "routing"/"phase": "routing_query"/g' agent/sap_agent.py
sed -i '' 's/"phase": "llm_routing"/"phase": "routing_query"/g' agent/sap_agent.py
sed -i '' 's/"phase": "formatting"/"phase": "processing"/g' agent/sap_agent.py
sed -i '' 's/"phase": "conversational"/"phase": "streaming_answer"/g' agent/sap_agent.py
```

Verify: `grep -n 'text_delta' agent/sap_agent.py` should return zero results.

- [ ] **Step 8: Add intent event in sap_agent.py**

In `chat_stream`, after the line `yield _sse("status", {"step": "Routing query via SAP pattern matcher...", "phase": "routing_query"})` (around line 1116), add:

```python
yield _sse("status", {"step": "Routing query via SAP pattern matcher...", "phase": "routing_query"})
# Emit intent event so the frontend can show detected SAP module
yield _sse("intent", {"modules": [], "confidence": 0.9, "routing": "pattern_match"})
```

After the LLM routing status event (around line 1167, after `yield _sse("status", {"step": "Sending to LLM for intent classification...", ...})`), add:

```python
yield _sse("intent", {"modules": [], "confidence": 0.7, "routing": "llm_classification"})
```

When a specific SAP tool is identified (after `tool_name` is determined from the pattern match or LLM call), update the intent event to include the detected module. Find lines like `yield _sse("status", {"step": f"Calling SAP tool: {tool_name}", "phase": "calling_tool"})` and add before each one:

```python
_sap_module = tool_name.split("_")[0].upper() if "_" in tool_name else tool_name.upper()
yield _sse("intent", {"modules": [_sap_module], "confidence": 1.0, "routing": "confirmed"})
yield _sse("status", {"step": f"Calling SAP tool: {tool_name}", "phase": "calling_tool"})
```

- [ ] **Step 9: Add clarification_answer parameter to chat_stream in sap_agent.py**

Find `async def chat_stream(self, user_message: str, allowed_tools: set | None = None):` and add the new parameter:

```python
async def chat_stream(
    self,
    user_message: str,
    allowed_tools: set | None = None,
    clarification_answer: str | None = None,
):
```

At the top of the function body, after the `_sse` local def, add:

```python
# If a clarification answer was provided, inject it into the message
if clarification_answer:
    user_message = f"{user_message}\n[Clarification: {clarification_answer}]"
```

- [ ] **Step 10: Add basic clarify event support in sap_agent.py**

Add a helper function inside `chat_stream` (after the `_sse` local def) that detects when a query needs clarification:

```python
def _needs_clarification(msg: str) -> dict | None:
    """
    Returns a clarify payload if the query is clearly ambiguous.
    Returns None if no clarification needed.
    """
    msg_lower = msg.lower()
    # Queries about invoices/payments without a date range need one
    if any(kw in msg_lower for kw in ("invoice", "payment", "purchase order", "vendor bill")) \
            and not any(kw in msg_lower for kw in ("today", "this week", "this month", "last", "since", "from", "between", "year", "quarter")):
        return {
            "question": "Which time period should I search?",
            "options": ["This month", "Last 3 months", "This year", "All time"],
        }
    # Queries about a specific customer/vendor without a name
    if any(kw in msg_lower for kw in ("customer detail", "vendor detail", "customer profile")) \
            and not any(c.isupper() for c in msg):
        return {
            "question": "Which customer or vendor are you looking for?",
            "options": None,  # None means free-text input
        }
    return None
```

Then, at the start of the main routing logic in `chat_stream` (before the autonomous agent check, or right before the pattern matcher), add:

```python
# Skip clarification check if the caller already provided an answer
if not clarification_answer:
    _clarify = _needs_clarification(user_message)
    if _clarify:
        yield _sse("clarify", _clarify)
        return  # stream ends; frontend will re-POST with clarification_answer
```

- [ ] **Step 11: Test the backend changes**

Start the backend: `uvicorn api.server:app --reload --port 8000`

Test with curl:
```bash
# Test basic stream (should now emit 'answer' not 'text_delta')
curl -s -N -X POST http://localhost:8000/chat/stream \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer TEST" \
  -d '{"message": "hello", "session_id": "test"}' | head -20

# Test clarification trigger
curl -s -N -X POST http://localhost:8000/chat/stream \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer TEST" \
  -d '{"message": "show me invoices", "session_id": "test"}' | head -10
# Expected: event: clarify\ndata: {"question": "Which time period..."}
```

- [ ] **Step 12: Commit backend changes**

```bash
git add api/server.py agent/sap_agent.py
git commit -m "feat: typed SSE events, clarification support, rows summary event"
```

---

## Task 4: Wire App.jsx to Zustand Store + Ask-Stream

**Files:**
- Modify: `frontend/src/App.jsx` — replace inline sendMessage with ask-stream, read state from store

- [ ] **Step 1: Add imports to App.jsx**

At the top of `frontend/src/App.jsx`, find the existing imports section and add:

```js
import useChatStore from './stores/chat-store.js'
import { sendMessage as streamSend } from './lib/ask-stream.js'
```

- [ ] **Step 2: Replace sendMessage in App.jsx**

Find the `const sendMessage = useCallback(async (text) => {` function (around line 3060) and replace the entire body with a call to the store-based version. The new function should preserve the existing auth token handling:

```js
const sendMessage = useCallback(async (text) => {
  if (!text.trim() || loading) return
  setLoading(true)

  // Clear view state
  setViewMode('chat')
  setInput('')

  await streamSend(text, {
    token:            authToken,
    refreshToken:     refreshTokenVal,
    onTokenRefresh:   async () => {
      const newToken = await doRefresh()
      return newToken
    },
    sessionId: currentSessionId || 'default',
  })

  setLoading(false)
}, [authToken, refreshTokenVal, loading, currentSessionId])
```

- [ ] **Step 3: Read streaming state from store in App.jsx**

Find the block where `streamingMsg` is rendered (around line 3440:
`{streamingMsg && (<StreamingMessageRow ...`). The store provides the same data. Add a store read near the top of the main component:

```js
const {
  isRunning,
  streamingAnswer,
  currentPhase,
  currentRows,
  streamError,
  messages: storeMessages,
  dataPanel,
  setDataPanel,
} = useChatStore()
```

Replace `streamingMsg` references with store state:
- `streamingMsg` → read `streamingAnswer` + `currentPhase` + `currentRows` from store
- `{streamingMsg && (<StreamingMessageRow msg={streamingMsg} ...` → `{isRunning && (<StreamingMessageRow ...`

Pass the store values as props: `<StreamingMessageRow answer={streamingAnswer} phase={currentPhase} rows={currentRows} />`

- [ ] **Step 4: Verify chat still works end-to-end**

Run `npm run dev` in frontend and `uvicorn api.server:app --reload` in backend.

Send a test message. Verify:
- User message appears immediately
- Streaming text shows up
- No console errors
- Done event finalizes the message

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.jsx
git commit -m "feat: wire App.jsx to Zustand store and ask-stream"
```

---

## Task 5: Extract PhaseStepper Component

**Files:**
- Create: `frontend/src/components/chat/PhaseStepper.jsx`

- [ ] **Step 1: Create component directory**

```bash
mkdir -p frontend/src/components/chat
```

- [ ] **Step 2: Create PhaseStepper.jsx**

Create `frontend/src/components/chat/PhaseStepper.jsx`:

```jsx
/**
 * PhaseStepper — animated pipeline phase track.
 *
 * Props:
 *   currentPhase: string | null  — active phase name from store
 *   done: boolean                — true when turn is complete; collapses to summary
 *   durationMs: number | null    — from done event, shown in collapsed state
 */

const PHASES = [
  { key: 'routing_query',    label: 'Understanding' },
  { key: 'calling_tool',     label: 'Retrieving' },
  { key: 'fetching_data',    label: 'Fetching' },
  { key: 'processing',       label: 'Processing' },
  { key: 'streaming_answer', label: 'Generating' },
]

export default function PhaseStepper({ currentPhase, done, durationMs }) {
  if (done && durationMs != null) {
    return (
      <div className="phase-stepper phase-stepper--done">
        <span className="phase-step-icon phase-step-icon--complete">✓</span>
        <span className="phase-stepper-summary">Done in {(durationMs / 1000).toFixed(1)}s</span>
      </div>
    )
  }

  const activeIdx = PHASES.findIndex((p) => p.key === currentPhase)

  return (
    <div className="phase-stepper">
      {PHASES.map((phase, idx) => {
        const isComplete = activeIdx > idx
        const isActive   = activeIdx === idx
        const isPending  = activeIdx < idx
        return (
          <div key={phase.key} className={`phase-step ${isActive ? 'phase-step--active' : ''} ${isComplete ? 'phase-step--complete' : ''} ${isPending ? 'phase-step--pending' : ''}`}>
            <span className="phase-step-icon">
              {isComplete ? '✓' : isActive ? '●' : '○'}
            </span>
            <span className="phase-step-label">{phase.label}</span>
            {idx < PHASES.length - 1 && <span className="phase-step-connector" />}
          </div>
        )
      })}
    </div>
  )
}
```

- [ ] **Step 3: Add PhaseStepper CSS to App.css**

Append to `frontend/src/App.css`:

```css
/* ── PhaseStepper ─────────────────────────────────────────────────────────── */
.phase-stepper {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px 0 12px;
  flex-wrap: wrap;
}
.phase-stepper--done {
  gap: 6px;
}
.phase-stepper-summary {
  font-size: 12px;
  color: var(--text-muted, #888);
}
.phase-step {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--text-muted, #aaa);
  transition: color 0.2s;
}
.phase-step--active {
  color: var(--accent, #2563eb);
  font-weight: 600;
}
.phase-step--complete {
  color: var(--success, #16a34a);
}
.phase-step-icon {
  font-size: 11px;
  width: 14px;
  text-align: center;
}
.phase-step--active .phase-step-icon {
  animation: phase-pulse 1s ease-in-out infinite;
}
.phase-step-connector {
  display: inline-block;
  width: 16px;
  height: 1px;
  background: currentColor;
  opacity: 0.3;
  margin: 0 2px;
}
@keyframes phase-pulse {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.3; }
}
```

- [ ] **Step 4: Replace existing status_steps rendering in StreamingMessageRow with PhaseStepper**

In `App.jsx`, find the `StreamingMessageRow` component function (around line 1708). Find where it renders `status_steps` (the `msg.status_steps.map(...)` loop, around line 1719) and replace it with:

```jsx
import PhaseStepper from './components/chat/PhaseStepper.jsx'

// Inside StreamingMessageRow render, replace the status_steps section:
<PhaseStepper currentPhase={msg.phase || currentPhase} done={false} />
```

- [ ] **Step 5: Verify PhaseStepper renders during a stream**

Start the dev server and send a message. The phase stepper should appear above the streaming text and animate as phases change.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/chat/PhaseStepper.jsx frontend/src/App.css frontend/src/App.jsx
git commit -m "feat: add PhaseStepper component with animated phase track"
```

---

## Task 6: Extract MessageRow Component

**Files:**
- Create: `frontend/src/components/chat/MessageRow.jsx`

- [ ] **Step 1: Create MessageRow.jsx**

The `MessageRow` function is currently defined inside App.jsx (around line 1118). Extract it into its own file.

Create `frontend/src/components/chat/MessageRow.jsx`:

```jsx
/**
 * MessageRow — renders a single completed message bubble.
 *
 * For user messages: plain text bubble.
 * For assistant messages: markdown content, SAP badges, table preview,
 *   view-data/visualize buttons, reasoning steps.
 *
 * Props mirror the message objects stored in chat-store:
 *   msg: { id, role, content, rows, done, phases }
 *   onViewData: fn(rows) — called when "View Data" is clicked
 *   onVisualize: fn(rows) — called when "Visualize" is clicked
 */
import MarkdownRenderer from '../ui/MarkdownRenderer.jsx'

export default function MessageRow({ msg, onViewData, onVisualize }) {
  const isUser = msg.role === 'user'

  if (isUser) {
    return (
      <div className="message-row message-row--user">
        <div className="message-bubble message-bubble--user">
          {msg.content}
        </div>
      </div>
    )
  }

  return (
    <div className="message-row message-row--assistant">
      <div className="message-bubble message-bubble--assistant">
        {msg.content && <MarkdownRenderer content={msg.content} />}

        {msg.rows && (
          <div className="message-table-preview">
            <span className="message-table-label">
              {msg.rows.row_count} rows · {msg.rows.columns?.length} columns
            </span>
            <div className="message-table-actions">
              <button className="btn-ghost btn-sm" onClick={() => onViewData?.(msg.rows)}>
                View Data
              </button>
              <button className="btn-ghost btn-sm" onClick={() => onVisualize?.(msg.rows)}>
                Visualize
              </button>
            </div>
          </div>
        )}

        {msg.done && (
          <div className="message-meta">
            <span className="message-meta-model">{msg.done.model}</span>
            {msg.done.duration_ms && (
              <span className="message-meta-duration">{(msg.done.duration_ms / 1000).toFixed(1)}s</span>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Create MarkdownRenderer component directory and file**

```bash
mkdir -p frontend/src/components/ui
```

Move the `MarkdownRenderer` function from App.jsx (around line 331) to a new file:

Create `frontend/src/components/ui/MarkdownRenderer.jsx`:

```jsx
/**
 * Zero-dependency markdown renderer supporting headings, lists,
 * tables, code blocks, and blockquotes.
 * Extracted from App.jsx.
 */
export default function MarkdownRenderer({ content }) {
  // Copy the MarkdownRenderer implementation verbatim from App.jsx lines ~331-386
  // (the function body is already written — just move it here and export it)
}
```

Open `frontend/src/App.jsx` and cut the `function MarkdownRenderer({ content })` definition (lines ~331-386), paste it into the new file, and add `export default` in front of `function`.

Then in App.jsx, replace the cut block with:
```js
import MarkdownRenderer from './components/ui/MarkdownRenderer.jsx'
```

- [ ] **Step 3: Use MessageRow in App.jsx**

In App.jsx, find where messages are rendered in the message list (the `.map((msg, idx) => ...)` over `messages`, around line 3400). Replace the inline JSX with:

```jsx
import MessageRow from './components/chat/MessageRow.jsx'

// In render:
{messages.map((msg) => (
  <MessageRow
    key={msg.id}
    msg={msg}
    onViewData={(rows) => setDataPanel({ mode: 'data', rows, title: 'Query Results' })}
    onVisualize={(rows) => setDataPanel({ mode: 'chart', rows, title: 'Visualization' })}
  />
))}
```

- [ ] **Step 4: Verify messages still render correctly**

Send a test message and confirm the assistant response renders markdown, that old messages still display, and no console errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/chat/MessageRow.jsx frontend/src/components/ui/MarkdownRenderer.jsx frontend/src/App.jsx
git commit -m "feat: extract MessageRow and MarkdownRenderer components"
```

---

## Task 7: Extract StreamingMessageRow Component

**Files:**
- Create: `frontend/src/components/chat/StreamingMessageRow.jsx`

- [ ] **Step 1: Create StreamingMessageRow.jsx**

Create `frontend/src/components/chat/StreamingMessageRow.jsx`:

```jsx
/**
 * StreamingMessageRow — live message bubble during active streaming.
 *
 * Subscribes to the Zustand chat store directly for performance
 * (avoids prop-drilling high-frequency streaming state).
 *
 * Shows: PhaseStepper → streaming text → live rows indicator
 */
import useChatStore from '../../stores/chat-store.js'
import PhaseStepper from './PhaseStepper.jsx'
import MarkdownRenderer from '../ui/MarkdownRenderer.jsx'

export default function StreamingMessageRow() {
  const { streamingAnswer, currentPhase, currentRows, isRunning, lastDone } = useChatStore()

  return (
    <div className="message-row message-row--assistant message-row--streaming">
      <div className="message-bubble message-bubble--assistant">
        <PhaseStepper
          currentPhase={currentPhase}
          done={!!lastDone && !isRunning}
          durationMs={lastDone?.duration_ms ?? null}
        />

        {streamingAnswer && (
          <div className="streaming-answer">
            <MarkdownRenderer content={streamingAnswer} />
            {isRunning && <span className="streaming-cursor" aria-hidden="true" />}
          </div>
        )}

        {currentRows && (
          <div className="streaming-rows-indicator">
            <span className="streaming-rows-icon">📊</span>
            <span>
              {currentRows.row_count} rows loaded
              {currentRows.truncated ? ' (truncated)' : ''}
            </span>
          </div>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Add streaming cursor CSS to App.css**

Append to `frontend/src/App.css`:

```css
/* ── Streaming cursor ─────────────────────────────────────────────────────── */
.streaming-cursor {
  display: inline-block;
  width: 2px;
  height: 1em;
  background: currentColor;
  margin-left: 2px;
  vertical-align: text-bottom;
  animation: cursor-blink 0.8s step-end infinite;
}
@keyframes cursor-blink {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0; }
}
.streaming-rows-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 0;
  font-size: 13px;
  color: var(--text-muted, #888);
}
```

- [ ] **Step 3: Replace StreamingMessageRow in App.jsx**

In App.jsx, find `{isRunning && (<StreamingMessageRow ...` and replace the entire inline component render with:

```jsx
import StreamingMessageRow from './components/chat/StreamingMessageRow.jsx'

// In render:
{isRunning && <StreamingMessageRow />}
```

Remove the now-unused inline `function StreamingMessageRow(...)` definition from App.jsx.

- [ ] **Step 4: Verify streaming still works**

Send a message. The stepper and streaming text should animate. The cursor blinks while `isRunning`. After `done`, stepper collapses to "Done in Xs".

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/chat/StreamingMessageRow.jsx frontend/src/App.css frontend/src/App.jsx
git commit -m "feat: extract StreamingMessageRow with store subscription"
```

---

## Task 8: Side Data Panel (Replaces DataViewModal)

**Files:**
- Create: `frontend/src/components/data/DataPanel.jsx`
- Create: `frontend/src/components/data/DataTable.jsx`
- Create: `frontend/src/components/data/DataVisualizer.jsx`

- [ ] **Step 1: Create data component directory**

```bash
mkdir -p frontend/src/components/data
```

- [ ] **Step 2: Extract DataTable.jsx**

The `DataTable` function exists in App.jsx (around line 403). Cut it from App.jsx and create `frontend/src/components/data/DataTable.jsx`:

Open `frontend/src/App.jsx` and find `function DataTable(` (around line 403). Cut the entire function block (through its closing `}`) out of App.jsx and paste it into `frontend/src/components/data/DataTable.jsx`, prefixing it with:

```jsx
import { useState } from 'react'

export default
```

So the file starts with:
```jsx
import { useState } from 'react'

export default function DataTable({ columns = [], rows = [], pageSize = 50 }) {
  // ... (pasted verbatim from App.jsx)
}
```

- [ ] **Step 3: Extract DataVisualizer.jsx**

The `DataVisualizer` function exists in App.jsx (around line 567). Cut it and create `frontend/src/components/data/DataVisualizer.jsx`:

Open `frontend/src/App.jsx` and find `function DataVisualizer(` (around line 567). Cut the entire function block out of App.jsx and paste it into `frontend/src/components/data/DataVisualizer.jsx`, prefixing with:

```jsx
import { useState } from 'react'

export default function DataVisualizer({ columns = [], rows = [] }) {
  // ... (pasted verbatim from App.jsx)
}
```

- [ ] **Step 4: Create DataPanel.jsx**

Create `frontend/src/components/data/DataPanel.jsx`:

```jsx
/**
 * DataPanel — resizable right-side panel showing table or chart data.
 *
 * Replaces DataViewModal popup. Opens when dataPanel != null in store.
 * Width is draggable; default 420px.
 *
 * Props:
 *   panel: { mode: 'data'|'chart', rows: { columns, rows, row_count }, title }
 *   onClose: fn()
 *   onModeChange: fn(mode)
 */
import { useState, useRef, useCallback } from 'react'
import DataTable from './DataTable.jsx'
import DataVisualizer from './DataVisualizer.jsx'

export default function DataPanel({ panel, onClose, onModeChange }) {
  const [width, setWidth] = useState(420)
  const dragRef = useRef(null)

  const startDrag = useCallback((e) => {
    e.preventDefault()
    const startX = e.clientX
    const startW = width

    const onMove = (ev) => {
      const delta = startX - ev.clientX
      setWidth(Math.max(280, Math.min(800, startW + delta)))
    }
    const onUp = () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }, [width])

  if (!panel) return null

  const { columns = [], rows = [] } = panel.rows || {}

  return (
    <div className="data-panel" style={{ width }}>
      <div
        className="data-panel-drag-handle"
        ref={dragRef}
        onMouseDown={startDrag}
        title="Drag to resize"
      />
      <div className="data-panel-head">
        <span className="data-panel-title">{panel.title || 'Results'}</span>
        <div className="data-panel-tabs">
          <button
            className={`data-panel-tab ${panel.mode === 'data' ? 'active' : ''}`}
            onClick={() => onModeChange('data')}
          >
            Table
          </button>
          <button
            className={`data-panel-tab ${panel.mode === 'chart' ? 'active' : ''}`}
            onClick={() => onModeChange('chart')}
          >
            Chart
          </button>
        </div>
        <button className="data-panel-close" onClick={onClose} aria-label="Close panel">
          ✕
        </button>
      </div>

      <div className="data-panel-body">
        {panel.mode === 'data' && <DataTable columns={columns} rows={rows} />}
        {panel.mode === 'chart' && <DataVisualizer columns={columns} rows={rows} />}
      </div>
    </div>
  )
}
```

- [ ] **Step 5: Add DataPanel CSS to App.css**

Append to `frontend/src/App.css`:

```css
/* ── DataPanel ────────────────────────────────────────────────────────────── */
.app-layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
}
.app-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.data-panel {
  display: flex;
  flex-direction: column;
  border-left: 1px solid var(--border, #e5e7eb);
  background: var(--bg, #fff);
  position: relative;
  flex-shrink: 0;
  transition: width 0.05s;
}
.data-panel-drag-handle {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
  cursor: ew-resize;
  background: transparent;
}
.data-panel-drag-handle:hover {
  background: var(--accent, #2563eb);
  opacity: 0.3;
}
.data-panel-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border, #e5e7eb);
  flex-shrink: 0;
}
.data-panel-title {
  font-weight: 600;
  font-size: 14px;
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.data-panel-tabs {
  display: flex;
  gap: 2px;
}
.data-panel-tab {
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 12px;
  border: none;
  background: transparent;
  cursor: pointer;
  color: var(--text-muted, #888);
}
.data-panel-tab.active {
  background: var(--accent-soft, #eff6ff);
  color: var(--accent, #2563eb);
  font-weight: 600;
}
.data-panel-close {
  width: 24px;
  height: 24px;
  border: none;
  background: transparent;
  cursor: pointer;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted, #888);
  font-size: 12px;
}
.data-panel-close:hover {
  background: var(--bg-hover, #f3f4f6);
}
.data-panel-body {
  flex: 1;
  overflow: auto;
  padding: 16px;
}
```

- [ ] **Step 6: Mount DataPanel in App.jsx**

In App.jsx, remove the `DataViewModal` popup render and replace with the `DataPanel`:

```jsx
import DataPanel from './components/data/DataPanel.jsx'

// In the top-level return JSX, wrap the layout:
<div className="app-layout">
  {/* existing sidebar */}
  <div className="app-main">
    {/* existing chat content */}
  </div>
  <DataPanel
    panel={dataPanel}
    onClose={() => setDataPanel(null)}
    onModeChange={(mode) => setDataPanel(prev => prev ? { ...prev, mode } : null)}
  />
</div>
```

Also update `setDataPanel` calls in App.jsx to come from the store:
```js
const { dataPanel, setDataPanel } = useChatStore()
```

- [ ] **Step 7: Verify data panel opens on rows event**

Send a query that returns table data (e.g., "show me all vendors"). The data panel should slide in from the right automatically. Dragging the handle should resize it. The Table/Chart tabs should switch views.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/data/ frontend/src/App.css frontend/src/App.jsx
git commit -m "feat: side data panel replaces DataViewModal popup"
```

---

## Task 9: Clarification Sheet

**Files:**
- Create: `frontend/src/components/chat/ClarificationSheet.jsx`

- [ ] **Step 1: Create ClarificationSheet.jsx**

Create `frontend/src/components/chat/ClarificationSheet.jsx`:

```jsx
/**
 * ClarificationSheet — bottom sheet shown when a 'clarify' SSE event arrives.
 *
 * The stream has paused; user picks an option or types an answer.
 * On submit, re-calls sendMessage with clarification_answer.
 *
 * Props:
 *   clarification: { question: string, options: string[] | null }
 *   originalMessage: string — the user's original message text
 *   onAnswer: fn(clarificationAnswer: string) — called on submit
 *   onDismiss: fn() — called on cancel/Escape
 */
import { useState, useEffect } from 'react'

export default function ClarificationSheet({ clarification, originalMessage, onAnswer, onDismiss }) {
  const [selected, setSelected] = useState(null)
  const [freeText, setFreeText] = useState('')

  useEffect(() => {
    const handleKey = (e) => { if (e.key === 'Escape') onDismiss?.() }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [onDismiss])

  if (!clarification) return null

  const hasOptions = clarification.options && clarification.options.length > 0
  const canSubmit  = hasOptions ? selected !== null : freeText.trim().length > 0

  const handleSubmit = () => {
    if (!canSubmit) return
    onAnswer?.(hasOptions ? selected : freeText.trim())
  }

  return (
    <>
      <div className="clarify-backdrop" onClick={onDismiss} />
      <div className="clarify-sheet" role="dialog" aria-modal="true">
        <div className="clarify-head">
          <span className="clarify-icon">💬</span>
          <div className="clarify-titles">
            <p className="clarify-original">Re: "{originalMessage}"</p>
            <p className="clarify-question">{clarification.question}</p>
          </div>
        </div>

        <div className="clarify-body">
          {hasOptions ? (
            <div className="clarify-options">
              {clarification.options.map((opt) => (
                <button
                  key={opt}
                  className={`clarify-option ${selected === opt ? 'clarify-option--selected' : ''}`}
                  onClick={() => setSelected(opt)}
                >
                  {opt}
                </button>
              ))}
            </div>
          ) : (
            <input
              className="clarify-input"
              type="text"
              placeholder="Type your answer..."
              value={freeText}
              onChange={(e) => setFreeText(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleSubmit() }}
              autoFocus
            />
          )}
        </div>

        <div className="clarify-foot">
          <button className="btn-ghost" onClick={onDismiss}>Cancel</button>
          <button className="btn-primary" onClick={handleSubmit} disabled={!canSubmit}>
            Continue
          </button>
        </div>
      </div>
    </>
  )
}
```

- [ ] **Step 2: Add ClarificationSheet CSS to App.css**

Append to `frontend/src/App.css`:

```css
/* ── ClarificationSheet ───────────────────────────────────────────────────── */
.clarify-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.2);
  z-index: 200;
}
.clarify-sheet {
  position: fixed;
  bottom: 0;
  left: 50%;
  transform: translateX(-50%);
  width: min(560px, 100vw);
  background: var(--bg, #fff);
  border-radius: 16px 16px 0 0;
  box-shadow: 0 -4px 32px rgba(0,0,0,0.12);
  z-index: 201;
  display: flex;
  flex-direction: column;
  animation: slide-up 0.25s ease;
}
@keyframes slide-up {
  from { transform: translateX(-50%) translateY(100%); }
  to   { transform: translateX(-50%) translateY(0); }
}
.clarify-head {
  display: flex;
  gap: 12px;
  padding: 20px 20px 0;
}
.clarify-icon { font-size: 20px; flex-shrink: 0; }
.clarify-titles { display: flex; flex-direction: column; gap: 4px; }
.clarify-original {
  font-size: 12px;
  color: var(--text-muted, #888);
  margin: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 420px;
}
.clarify-question {
  font-size: 15px;
  font-weight: 600;
  margin: 0;
}
.clarify-body { padding: 16px 20px; }
.clarify-options {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.clarify-option {
  padding: 8px 16px;
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 20px;
  font-size: 13px;
  cursor: pointer;
  background: var(--bg, #fff);
  transition: all 0.15s;
}
.clarify-option:hover { border-color: var(--accent, #2563eb); color: var(--accent, #2563eb); }
.clarify-option--selected {
  background: var(--accent, #2563eb);
  color: #fff;
  border-color: var(--accent, #2563eb);
}
.clarify-input {
  width: 100%;
  padding: 10px 14px;
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 8px;
  font-size: 14px;
  outline: none;
  box-sizing: border-box;
}
.clarify-input:focus { border-color: var(--accent, #2563eb); }
.clarify-foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 0 20px 20px;
}
```

- [ ] **Step 3: Mount ClarificationSheet in App.jsx**

In App.jsx, add imports and mount the sheet:

```jsx
import ClarificationSheet from './components/chat/ClarificationSheet.jsx'
import { sendMessage as streamSend } from './lib/ask-stream.js'

// Read clarification state from store
const { clarification, setClarification, messages } = useChatStore()

// Get the original user message (last user message)
const lastUserMessage = [...messages].reverse().find(m => m.role === 'user')?.content || ''

// Handler: user answers the clarification
const handleClarificationAnswer = async (answer) => {
  setClarification(null)
  await streamSend(lastUserMessage, {
    token: authToken,
    refreshToken: refreshTokenVal,
    onTokenRefresh: async () => doRefresh(),
    sessionId: currentSessionId || 'default',
    clarificationAnswer: answer,
  })
}

// In JSX (just before closing </div> of the app root):
<ClarificationSheet
  clarification={clarification}
  originalMessage={lastUserMessage}
  onAnswer={handleClarificationAnswer}
  onDismiss={() => setClarification(null)}
/>
```

- [ ] **Step 4: Test the clarification flow end-to-end**

Send a message that triggers clarification: `"show me invoices"` (the backend's `_needs_clarification` check will fire).

Expected flow:
1. Stream starts → clarify event arrives → ClarificationSheet slides up
2. User picks a time period option
3. Sheet closes, new stream starts with clarification_answer appended
4. Full results return

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/chat/ClarificationSheet.jsx frontend/src/App.css frontend/src/App.jsx
git commit -m "feat: clarification sheet for pause/resume streaming"
```

---

## Task 10: Sidebar + Header + api.js + Slim App.jsx

**Files:**
- Create: `frontend/src/components/layout/Sidebar.jsx`
- Create: `frontend/src/components/layout/Header.jsx`
- Create: `frontend/src/lib/api.js`

- [ ] **Step 1: Create layout directory**

```bash
mkdir -p frontend/src/components/layout
```

- [ ] **Step 2: Create api.js**

Create `frontend/src/lib/api.js`:

```js
const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

async function authFetch(path, options = {}, token) {
  const res = await fetch(`${API}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  })
  if (!res.ok) throw new Error(`API ${res.status}: ${path}`)
  return res.json()
}

export const api = {
  getConversations: (token) =>
    authFetch('/conversations', {}, token),

  getConversation: (id, token) =>
    authFetch(`/conversations/${id}`, {}, token),
}
```

- [ ] **Step 3: Create Header.jsx**

Create `frontend/src/components/layout/Header.jsx`:

```jsx
/**
 * Header — app title bar with model label and live activity dot.
 *
 * Props:
 *   title: string
 *   model: string | null  — e.g. "llama3.2"
 *   isLive: boolean       — true while stream is in progress
 */
export default function Header({ title = 'SAP AI Agent', model, isLive }) {
  return (
    <header className="app-header">
      <span className="app-header-title">{title}</span>
      <div className="app-header-right">
        {model && <span className="app-header-model">{model}</span>}
        {isLive && <span className="app-header-live" title="Streaming" />}
      </div>
    </header>
  )
}
```

Append to `frontend/src/App.css`:

```css
/* ── Header ───────────────────────────────────────────────────────────────── */
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  height: 52px;
  border-bottom: 1px solid var(--border, #e5e7eb);
  flex-shrink: 0;
}
.app-header-title { font-weight: 700; font-size: 15px; }
.app-header-right { display: flex; align-items: center; gap: 10px; }
.app-header-model {
  font-size: 12px;
  color: var(--text-muted, #888);
  background: var(--bg-muted, #f3f4f6);
  padding: 2px 8px;
  border-radius: 10px;
}
.app-header-live {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--success, #16a34a);
  animation: phase-pulse 1s ease-in-out infinite;
}
```

- [ ] **Step 4: Create Sidebar.jsx**

Extract the existing sidebar JSX from App.jsx (the conversation list panel, around line 2606) into a new file:

Create `frontend/src/components/layout/Sidebar.jsx`:

```jsx
/**
 * Sidebar — conversation history list with search and new-chat button.
 *
 * Props:
 *   conversations: [{ id, title, created_at }]
 *   currentId: string | null
 *   onSelect: fn(id)
 *   onNew: fn()
 */
import { useState } from 'react'

export default function Sidebar({ conversations = [], currentId, onSelect, onNew }) {
  const [search, setSearch] = useState('')

  const filtered = conversations.filter(c =>
    c.title?.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <aside className="sidebar">
      <div className="sidebar-head">
        <button className="btn-primary btn-sm sidebar-new-btn" onClick={onNew}>
          + New Chat
        </button>
      </div>

      <div className="sidebar-search">
        <input
          type="text"
          placeholder="Search conversations..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="sidebar-search-input"
        />
      </div>

      <nav className="sidebar-list">
        {filtered.length === 0 && (
          <p className="sidebar-empty">No conversations yet.</p>
        )}
        {filtered.map((conv) => (
          <button
            key={conv.id}
            className={`sidebar-item ${conv.id === currentId ? 'sidebar-item--active' : ''}`}
            onClick={() => onSelect(conv.id)}
          >
            <span className="sidebar-item-title">{conv.title || 'Untitled'}</span>
            <span className="sidebar-item-date">
              {conv.created_at ? new Date(conv.created_at).toLocaleDateString() : ''}
            </span>
          </button>
        ))}
      </nav>
    </aside>
  )
}
```

Append to `frontend/src/App.css`:

```css
/* ── Sidebar ──────────────────────────────────────────────────────────────── */
.sidebar {
  width: 260px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border, #e5e7eb);
  background: var(--bg-sidebar, #f9fafb);
  overflow: hidden;
}
.sidebar-head { padding: 12px; }
.sidebar-new-btn { width: 100%; }
.sidebar-search { padding: 0 12px 8px; }
.sidebar-search-input {
  width: 100%;
  padding: 6px 10px;
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 6px;
  font-size: 13px;
  outline: none;
  box-sizing: border-box;
  background: var(--bg, #fff);
}
.sidebar-list { flex: 1; overflow-y: auto; }
.sidebar-empty { padding: 16px 12px; font-size: 13px; color: var(--text-muted, #888); }
.sidebar-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 100%;
  text-align: left;
  padding: 10px 14px;
  border: none;
  background: transparent;
  cursor: pointer;
  border-radius: 0;
}
.sidebar-item:hover { background: var(--bg-hover, #f3f4f6); }
.sidebar-item--active { background: var(--accent-soft, #eff6ff); }
.sidebar-item-title {
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sidebar-item-date { font-size: 11px; color: var(--text-muted, #888); }
```

- [ ] **Step 5: Mount Sidebar + Header in App.jsx and slim to orchestrator**

In `App.jsx`, replace the existing layout wrapper with:

```jsx
import Header from './components/layout/Header.jsx'
import Sidebar from './components/layout/Sidebar.jsx'

// In render — top-level structure:
return (
  <div className="app-layout">
    <Sidebar
      conversations={conversations}
      currentId={currentConversationId}
      onSelect={(id) => { /* load conversation */ }}
      onNew={() => { setMessages([]); setCurrentConversationId(null) }}
    />

    <div className="app-main">
      <Header title="SAP AI Agent" model={lastDone?.model} isLive={isRunning} />

      <div className="message-list">
        {messages.map((msg) => (
          <MessageRow
            key={msg.id}
            msg={msg}
            onViewData={(rows) => setDataPanel({ mode: 'data', rows, title: 'Results' })}
            onVisualize={(rows) => setDataPanel({ mode: 'chart', rows, title: 'Visualization' })}
          />
        ))}
        {isRunning && <StreamingMessageRow />}
        {streamError && (
          <div className="stream-error">
            ⚠ {streamError}
            <button className="btn-ghost btn-sm" onClick={() => setStreamError(null)}>Dismiss</button>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input area — keep existing prompt-box JSX from App.jsx */}
      {/* Settings modal, ABAP widget, receipt widget, report widget — keep as-is */}
    </div>

    <DataPanel
      panel={dataPanel}
      onClose={() => setDataPanel(null)}
      onModeChange={(mode) => setDataPanel(prev => prev ? { ...prev, mode } : null)}
    />

    <ClarificationSheet
      clarification={clarification}
      originalMessage={[...messages].reverse().find(m => m.role === 'user')?.content || ''}
      onAnswer={handleClarificationAnswer}
      onDismiss={() => setClarification(null)}
    />
  </div>
)
```

Remove all code that was extracted into components. Target: App.jsx under 300 lines.

- [ ] **Step 6: Final verification against success criteria**

Start frontend and backend:
```bash
# Terminal 1
cd /Users/ravibhanawat/Documents/sap_ai_agent
uvicorn api.server:app --reload --port 8000

# Terminal 2
cd /Users/ravibhanawat/Documents/sap_ai_agent/frontend
npm run dev
```

Verify each success criterion:
- [ ] App.jsx is under 300 lines (`wc -l frontend/src/App.jsx`)
- [ ] All 7 SSE event types handled (status, intent, answer, rows, clarify, done, error)
- [ ] Clarification loop: send "show me invoices" → sheet appears → pick option → results load
- [ ] Data panel: send query returning rows → panel slides in → tabs switch → drag handle resizes
- [ ] Phase stepper: animates through phases → collapses on done
- [ ] Conversation history: sidebar shows conversations list
- [ ] Existing features: ABAP widget, settings modal, auth still work

- [ ] **Step 7: Final commit**

```bash
git add frontend/src/components/ frontend/src/lib/api.js frontend/src/App.jsx frontend/src/App.css
git commit -m "feat: complete chat UI overhaul — sidebar, header, data panel, clarification"
```

---

## Summary

| Task | Deliverable | Risk |
|------|-------------|------|
| 1 | Zustand store | Low |
| 2 | SSE parser + ask-stream | Low |
| 3 | Backend typed events + clarify | Medium (server.py changes) |
| 4 | Wire App.jsx to store | Medium (replacing sendMessage) |
| 5 | PhaseStepper | Low |
| 6 | MessageRow + MarkdownRenderer | Low |
| 7 | StreamingMessageRow | Low |
| 8 | DataPanel (side panel) | Medium (layout changes) |
| 9 | ClarificationSheet | Low |
| 10 | Sidebar + Header + slim App.jsx | Medium (orchestration wiring) |

Each task produces a working, testable change. Tasks 3 and 4 must be done together (deploy backend and frontend in sync on event rename). All other tasks are independent.
