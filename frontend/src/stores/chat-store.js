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
  statusSteps: [],          // accumulated human-readable step labels from 'status' events
  streamingAnswer: '',      // accumulated answer delta text
  currentRows: null,        // { columns, rows, row_count, truncated } when rows event arrives
  clarification: null,      // { question, options[] } when clarify event arrives
  intentInfo: null,         // { modules, confidence }
  lastDone: null,           // { tokens, model, duration_ms, conversation_id }
  streamError: null,

  // ── Side data panel ────────────────────────────────────────────────────────
  dataPanel: null,          // null=hidden | { mode: 'data'|'chart', rows, title }
  chatVisible: true,        // false = DataPanel is in full-screen mode (chat hidden)

  // ── Primitive setters ──────────────────────────────────────────────────────
  setIsRunning: (v) => set({ isRunning: v }),
  setCurrentPhase: (phase) => set({ currentPhase: phase }),
  appendStatusStep: (step, phase) => set((s) => ({
    currentPhase: phase,
    statusSteps: [...s.statusSteps, step],
  })),
  appendAnswer: (delta) => set((s) => ({ streamingAnswer: s.streamingAnswer + delta })),
  setCurrentRows: (rows) => set({ currentRows: rows }),
  setClarification: (clarification) => set({ clarification }),
  setIntentInfo: (intentInfo) => set({ intentInfo }),
  setLastDone: (done) => set({ lastDone: done }),
  setStreamError: (error) => set({ streamError: error }),
  setDataPanel: (panel) => set({ dataPanel: panel, ...(panel === null ? { chatVisible: true } : {}) }),
  setChatVisible: (v) => set({ chatVisible: v }),
  setMessages: (messages) => set({ messages }),
  setConversations: (conversations) => set({ conversations }),
  setCurrentConversationId: (id) => set({ currentConversationId: id }),

  // ── resetStreamState ───────────────────────────────────────────────────────
  resetStreamState: () => set({
    isRunning: false,
    currentPhase: null,
    statusSteps: [],
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
  //
  // The widget payloads (report, abap_check, abap_code) only ever arrive on the
  // 'done' event, and MessageRow reads them off the message — not off msg.done.
  // Leaving them behind here meant a chart request rendered its "Here is the …"
  // text with no chart under it, and only appeared after reloading the
  // conversation from history. Field names match the history loader in App.jsx
  // so a live turn and a reloaded one render identically.
  finalizeTurn: () => set((prev) => {
    const done = prev.lastDone || null
    const assistantMsg = {
      id: `asst-${Date.now()}`,
      role: 'assistant',
      content: prev.streamingAnswer,
      status_steps: prev.statusSteps,
      rows: prev.currentRows || null,
      done,
      tool_called: done?.tool_called || null,
      tool_result: done?.tool_result || null,
      sap_source:  done?.sap_source  || null,
      report:      done?.report      || null,
      abap_check:  done?.abap_check  || null,
      abap_code:   done?.abap_code   || null,
    }
    return { messages: [...prev.messages, assistantMsg] }
  }),
}))

export default useChatStore
