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
  finalizeTurn: () => set((prev) => {
    const assistantMsg = {
      id: `asst-${Date.now()}`,
      role: 'assistant',
      content: prev.streamingAnswer,
      rows: prev.currentRows || null,
      done: prev.lastDone || null,
      phases: [],
    }
    return { messages: [...prev.messages, assistantMsg] }
  }),
}))

export default useChatStore
