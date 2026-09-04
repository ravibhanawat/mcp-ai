import { parseSSE } from './sse-parser.js'
import useChatStore from '../stores/chat-store.js'
import { API } from './api.js'

/**
 * Sends a message to /chat/stream, dispatches typed SSE events to the
 * Zustand chat store, and handles token refresh on 401.
 *
 * Options:
 *   token              - current JWT access token
 *   refreshToken       - refresh token (passed to onTokenRefresh if 401)
 *   onTokenRefresh     - async fn() -> new token string | null
 *   sessionId          - chat session identifier (default: 'default')
 *   clarificationAnswer - string | null, set when resuming after clarify event
 */
export async function sendMessage(
  text,
  { token, onTokenRefresh, sessionId = 'default', clarificationAnswer = null, model = 'kutty', userInitial = 'U' } = {}
) {
  const store = useChatStore.getState()
  store.resetStreamState()
  store.setIsRunning(true)

  // Add user message to history immediately (optimistic)
  store.addMessage({ id: `user-${Date.now()}`, role: 'user', content: text, userInitial })

  const body = { message: text, model, session_id: sessionId }
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
          store.appendStatusStep(payload.step || payload.phase, payload.phase)
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
    console.error('Stream processing error:', err)
    store.setStreamError('Connection lost. Please try again.')
  } finally {
    store.setIsRunning(false)
  }
}
