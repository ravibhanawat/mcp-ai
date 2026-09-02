let rawAPI = import.meta.env.VITE_API_URL || '/api'
if (rawAPI && rawAPI !== '/api' && !rawAPI.startsWith('http://') && !rawAPI.startsWith('https://') && !rawAPI.startsWith('/')) {
  rawAPI = (rawAPI.includes('localhost') || rawAPI.includes('127.0.0.1')) ? `http://${rawAPI}` : `https://${rawAPI}`
}
export const API = rawAPI.replace(/\/$/, '')

// ─── Auth helpers ─────────────────────────────────────────────────────────────

async function refreshAccessToken() {
  const refresh = localStorage.getItem('sap_agent_refresh_token')
  if (!refresh) return false
  try {
    const res = await fetch(`${API}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refresh }),
    })
    if (!res.ok) return false
    const data = await res.json()
    localStorage.setItem('sap_agent_token', data.access_token)
    if (data.refresh_token) localStorage.setItem('sap_agent_refresh_token', data.refresh_token)
    return true
  } catch { return false }
}

let _onSessionExpired = null

export async function apiFetch(path, options = {}) {
  const token = localStorage.getItem('sap_agent_token')
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) }
  if (token) headers['Authorization'] = `Bearer ${token}`
  let res = await fetch(`${API}${path}`, { ...options, headers })
  if (res.status === 401) {
    const refreshed = await refreshAccessToken()
    if (refreshed) {
      headers['Authorization'] = `Bearer ${localStorage.getItem('sap_agent_token')}`
      res = await fetch(`${API}${path}`, { ...options, headers })
    } else {
      localStorage.removeItem('sap_agent_token')
      localStorage.removeItem('sap_agent_refresh_token')
      if (_onSessionExpired) _onSessionExpired()
    }
  }
  return res
}

// Convenience wrapper: the admin screens all want parsed JSON plus a usable
// error message, and repeating that in every handler is how inconsistent error
// display creeps in.
export async function apiJson(path, options = {}) {
  const res = await apiFetch(path, options)
  const text = await res.text()
  let body = null
  try { body = text ? JSON.parse(text) : null } catch { body = { detail: text } }
  if (!res.ok) {
    const detail = body?.detail
    const message = typeof detail === 'string'
      ? detail
      : detail?.message || `Request failed (${res.status})`
    const error = new Error(message)
    error.status = res.status
    error.body = body
    throw error
  }
  return body
}

export function setSessionExpiredHandler(fn) { _onSessionExpired = fn }
