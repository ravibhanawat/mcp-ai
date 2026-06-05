# SAP AI Agent — Chat UI Overhaul Design

**Date:** 2026-06-05  
**Scope:** Full overhaul of the chat interface in `sap_ai_agent`, modeled on `sap_warn` patterns  
**Approach:** Option B — Incremental Extraction (existing App.jsx extracted progressively into modular components)

---

## Goals

- Replace the monolithic `App.jsx` (172KB) with modular, single-responsibility components
- Add Zustand state store for conversations, messages, and stream state
- Update backend SSE events to typed schema (matching sap_warn patterns)
- Add side data panel (replacing DataViewModal popup)
- Add phase stepper for streaming progress visualization
- Add clarification loop (backend pauses, user picks option, stream resumes)
- Preserve all existing working features (ABAP widget, receipt widget, report widget, auth, settings)

---

## Reference Projects

| | sap_ai_agent (current) | sap_warn (reference) |
|---|---|---|
| Framework | React 19 + Vite + JSX | Next.js 16 + TypeScript |
| State | React useState/useRef | Zustand |
| SSE Events | `event_delta`, `status`, `table_start/rows/end`, `done`, `error` | Typed enum: Status, Retrieval, Intent, Answer, Rows, Clarify, Done, Error |
| Data display | DataViewModal popup | Resizable side panel |
| Phase display | Inline step list | Animated PhaseStepper |
| Clarification | Not implemented | ClarificationSheet + re-POST |
| Backend | FastAPI + Python | Rust + Salvo |

---

## Architecture

### New File Structure

```
frontend/src/
├── stores/
│   └── chat-store.js              # Zustand store
├── lib/
│   ├── sse-parser.js              # SSE frame → typed event objects
│   ├── ask-stream.js              # Fetch /chat/stream, dispatch to store
│   └── api.js                     # REST: conversations, history
├── components/
│   ├── chat/
│   │   ├── MessageRow.jsx         # Completed message bubble
│   │   ├── StreamingMessageRow.jsx # In-flight message with live updates
│   │   ├── PhaseStepper.jsx       # Animated pipeline phase track
│   │   └── ClarificationSheet.jsx # Pause/resume clarification modal
│   ├── data/
│   │   ├── DataPanel.jsx          # Resizable side panel container
│   │   ├── DataTable.jsx          # Paginated sortable table
│   │   └── DataVisualizer.jsx     # Bar/pie charts (custom, extracted from App.jsx)
│   └── layout/
│       ├── Sidebar.jsx            # Conversation history list + search
│       └── Header.jsx             # Title, model label, live indicator
└── App.jsx                        # Thin orchestrator (~200 lines after cleanup)
```

---

## Implementation Phases

### Phase 1 — Zustand Store + SSE Library Layer
**Goal:** Foundation layer with no visible UI changes.

- Install `zustand` as a dependency
- Create `stores/chat-store.js` with full state shape
- Create `lib/sse-parser.js` to parse raw SSE frames into typed objects
- Create `lib/ask-stream.js` to replace the inline `sendMessage` logic
- Wire App.jsx to use the store (read/write via `useChatStore`)
- All existing features continue working unchanged

### Phase 2 — Backend: Typed SSE Events + Clarification Support
**Goal:** Update `api/server.py` and `agent/sap_agent.py` to emit clean typed events.

Backend changes:
- `server.py`: update SSE yielding to use typed event names
- `sap_agent.py`: map internal step callbacks to typed events; add `clarify` event support

Event schema:

| Event | Payload | Source |
|-------|---------|--------|
| `status` | `{ phase: string }` | Each pipeline step |
| `intent` | `{ modules: string[], confidence: float }` | After routing |
| `answer` | `{ delta: string }` | Streaming LLM output |
| `rows` | `{ columns: [], rows: [], row_count: int, truncated: bool }` | Tool result table |
| `clarify` | `{ question: string, options: string[] }` | Agent disambiguation |
| `done` | `{ tokens: int, model: string, duration_ms: int, conversation_id: string }` | Turn complete |
| `error` | `{ message: string }` | Any failure |

Phase values for `status.phase`:
- `routing_query` — classifying user intent
- `calling_tool` — executing SAP module tool
- `fetching_data` — retrieving data from SAP
- `processing` — processing/formatting results
- `streaming_answer` — LLM generating response
- `done` — complete

Clarification loop:
1. Agent detects ambiguity (e.g., multiple matching customers, unclear date range)
2. Yields `clarify` event with question + options array
3. Stream ends (SSE closes)
4. Frontend shows `ClarificationSheet`
5. User selects option
6. Frontend re-POSTs to `/chat/stream` with `clarification_answer` field + same `session_id`
7. Agent resumes from the clarification point

### Phase 3 — Extract Chat Components
**Goal:** Pull MessageRow, StreamingMessageRow, and PhaseStepper out of App.jsx.

- `MessageRow.jsx`: static completed message; renders markdown, code blocks, SAP badges, table headers
- `StreamingMessageRow.jsx`: live message; subscribes to store stream state; renders `PhaseStepper` + streaming text + live rows
- `PhaseStepper.jsx`: receives `phases[]` array from store; renders animated step track

Phase stepper UI:
```
● Understanding  ✓ Retrieving  ✓ Analyzing  ● Generating  ○ Done
```
- `○` = pending (grey)
- `●` = active (blue, pulsing animation)
- `✓` = complete (green filled)
- Collapses to single "Done in 3.2s" line after `done` event

### Phase 4 — Side Data Panel (Replaces DataViewModal)
**Goal:** Show table/chart data in a resizable side panel, not a popup modal.

`DataPanel.jsx`:
- Fixed right column, slides in when `rows` event arrives or user clicks "View Data"
- Width: 420px default, resizable via `mousedown` drag handle
- Tabs: **Table** | **Chart**
- Close button (X) collapses panel; chat area flexes to fill space
- `DataTable.jsx` (moved from App.jsx): paginated, sortable, searchable
- `DataVisualizer.jsx` (moved from App.jsx): bar/pie with column selectors

State: `dataPanel` in chat store — `null` = hidden, `{ mode, rows, title }` = visible.

### Phase 5 — Clarification Sheet + Conversation Sidebar
**Goal:** Add clarification UX and persistent conversation history.

`ClarificationSheet.jsx`:
- Slides up from bottom when `clarification !== null` in store
- Shows: original question (read-only) + clarification question + option buttons
- On submit: calls `ask-stream.js` with `clarification_answer + conversation_id`
- Clears `clarification` in store, reuses same message bubble (in-place update)
- Escape key / Cancel dismisses without answering

`Sidebar.jsx` (extraction from existing App.jsx sidebar):
- Left fixed panel, 260px
- Conversation list with timestamps, truncated title
- Search input (client-side filter on title)
- "New Chat" button at top
- Clicking a conversation loads history via `api.js`

### Phase 6 — App.jsx Cleanup
**Goal:** Reduce App.jsx to thin orchestrator.

- Remove all extracted logic
- App.jsx only: layout shell (sidebar + main + data panel), route to widgets (ABAP, receipt, report)
- Target: under 200 lines

---

## Zustand Store Shape

```js
// stores/chat-store.js
{
  // Conversations
  conversations: [],              // [{ id, title, created_at }]
  currentConversationId: null,
  messages: [],                   // [{ id, role, content, phases, rows, done, error, clarification }]

  // Active stream state (reset via resetStreamState() on each new send)
  isRunning: false,
  currentPhase: null,
  streamingAnswer: '',
  currentRows: null,              // { columns, rows, row_count, truncated }
  clarification: null,            // { question, options[] }
  intentInfo: null,               // { modules, confidence }
  lastDone: null,                 // { tokens, model, duration_ms }
  streamError: null,

  // Side data panel
  dataPanel: null,                // null | { mode: 'data'|'chart', rows, title }

  // Actions
  sendMessage(text, clarificationAnswer),
  resetStreamState(),
  setDataPanel(panel),
  loadConversations(),
  loadConversation(id),
}
```

---

## Data Flow

```
User types → sendMessage() in ask-stream.js
  → POST /chat/stream (with session_id, optional clarification_answer)
  → sse-parser.js reads response.body TextDecoder stream
  → typed events dispatched to chat-store:
      status   → store.currentPhase = phase
      intent   → store.intentInfo = { modules, confidence }
      answer   → store.streamingAnswer += delta
      rows     → store.currentRows = { columns, rows, ... }
                  store.dataPanel = { mode: 'data', ... }  (auto-open panel)
      clarify  → store.clarification = { question, options }
                  (stream ends; ClarificationSheet becomes visible)
      done     → store.lastDone = metadata; finalize message in store.messages
      error    → store.streamError = message
```

---

## Error Handling

- **Stream drop / network error**: catch in `ask-stream.js`, dispatch `error` event to store, show inline error in message bubble with retry button
- **Backend 4xx / 5xx before stream**: catch HTTP status, show toast + inline error
- **Clarification timeout**: no timeout on clarification (user can take as long as needed)
- **Tool execution errors**: backend yields `error` event, frontend marks message as failed

---

## Constraints & Non-Goals

- **No TypeScript migration** — stay with plain JSX/JS
- **No new UI library** — keep zero-dependency custom components
- **No voice/TTS** — not in scope for this overhaul
- **No i18n** — existing English-only behavior preserved
- **Preserve existing widgets** — ABAP, receipt, and report widgets remain unchanged
- **No auth changes** — JWT/OAuth flow untouched

---

## Success Criteria

1. App.jsx under 200 lines after Phase 6
2. All 6 SSE event types handled correctly in frontend
3. Clarification loop works end-to-end (backend → sheet → resume)
4. Side data panel opens automatically on `rows` event, resizes correctly
5. Phase stepper animates through all phases and collapses on `done`
6. Conversation history loads and switches correctly
7. All existing features (ABAP widget, settings, auth) still work
