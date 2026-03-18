import { useState, useEffect, useRef, useCallback } from 'react'
import './App.css'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { PrismLight as SyntaxHighlighter } from 'react-syntax-highlighter'
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism'
import abap from 'react-syntax-highlighter/dist/esm/languages/prism/abap'
import sql from 'react-syntax-highlighter/dist/esm/languages/prism/sql'
import javascript from 'react-syntax-highlighter/dist/esm/languages/prism/javascript'
import python from 'react-syntax-highlighter/dist/esm/languages/prism/python'
import jsonLang from 'react-syntax-highlighter/dist/esm/languages/prism/json'

SyntaxHighlighter.registerLanguage('abap', abap)
SyntaxHighlighter.registerLanguage('sql', sql)
SyntaxHighlighter.registerLanguage('javascript', javascript)
SyntaxHighlighter.registerLanguage('python', python)
SyntaxHighlighter.registerLanguage('json', jsonLang)

const API = '/api'

// ─── Auth helper ──────────────────────────────────────────────────────────────
// Reads token from localStorage so it's always current
function apiFetch(path, options = {}) {
  const token = localStorage.getItem('sap_agent_token')
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) }
  if (token) headers['Authorization'] = `Bearer ${token}`
  return fetch(`${API}${path}`, { ...options, headers })
}

// ─── Module definitions ───────────────────────────────────────────────────────
const MODULES = [
  {
    id: 'all', name: 'All Modules', icon: '🏢', desc: 'All SAP tools',
    color: '#0070D2', bg: '#EAF4FF', moduleKey: null,
    examples: ['Show me open purchase orders', 'List all employees in HR department', 'What is the budget for cost center CC100?', 'Get customer info for C001'],
  },
  {
    id: 'FI/CO', name: 'FI/CO', icon: '💰', desc: 'Finance & Controlling',
    color: '#16A34A', bg: '#F0FDF4', moduleKey: 'fi_co',
    examples: ['Get vendor info for V001', 'Show status of invoice INV1001', 'List all open invoices', 'What is the budget vs actual for CC200?', 'Show all cost centers'],
  },
  {
    id: 'MM', name: 'MM', icon: '📦', desc: 'Materials Management',
    color: '#D97706', bg: '#FFFBEB', moduleKey: 'mm',
    examples: ['Get material info for MAT001', 'Check stock level for MAT002 at plant 1000', 'Show purchase order PO2001', 'List all open purchase orders', 'Which materials need reordering?'],
  },
  {
    id: 'SD', name: 'SD', icon: '🛒', desc: 'Sales & Distribution',
    color: '#7C3AED', bg: '#F5F3FF', moduleKey: 'sd',
    examples: ['Get customer info for C002', 'Show sales order SO5001', 'List all orders for customer C001', 'Create a sales order for Wipro - 10 laptops', 'Show all open sales orders'],
  },
  {
    id: 'HR', name: 'HR', icon: '👥', desc: 'Human Resources',
    color: '#DB2777', bg: '#FDF2F8', moduleKey: 'hr',
    examples: ['Get employee info for EMP001', 'What is the leave balance for EMP002?', 'Show payslip for EMP001', 'Apply leave for EMP003 - 3 days annual', 'List all employees in IT department'],
  },
  {
    id: 'PP', name: 'PP', icon: '🏭', desc: 'Production Planning',
    color: '#0891B2', bg: '#F0F9FF', moduleKey: 'pp',
    examples: ['Get production order PRD7001', 'Show bill of materials for MAT001', 'Create a production order for 50 units of MAT002', 'List all active production orders', 'What is the capacity utilization?'],
  },
  {
    id: 'ABAP', name: 'ABAP', icon: '💻', desc: 'Development & Basis',
    color: '#64748B', bg: '#F8FAFC', moduleKey: 'abap',
    examples: ['Show me program ZREP_VENDOR_LIST', 'Get function module Z_GET_VENDOR_MASTER details', 'What is the status of transport DEVK900123?', 'List all ABAP programs in package ZFICO', 'Analyze this ABAP code: SELECT * FROM MARA INTO TABLE lt_mat.'],
  },
]

const MODELS = ['llama3.2', 'llama3.1', 'mistral', 'gemma2', 'codellama']
const AUTH_TYPES = [
  { value: 'basic',  label: 'Basic Auth' },
  { value: 'oauth2', label: 'OAuth 2.0' },
  { value: 'x509',   label: 'X.509 Certificate' },
]
const ROLE_LABELS = {
  admin:          'Administrator',
  fi_co_analyst:  'FI/CO Analyst',
  mm_analyst:     'MM Analyst',
  sd_analyst:     'SD Analyst',
  hr_manager:     'HR Manager',
  pp_planner:     'PP Planner',
  abap_developer: 'ABAP Developer',
  read_only:      'Read Only',
}
const ROLE_COLORS = {
  admin:          '#0070D2',
  fi_co_analyst:  '#16A34A',
  mm_analyst:     '#D97706',
  sd_analyst:     '#7C3AED',
  hr_manager:     '#DB2777',
  pp_planner:     '#0891B2',
  abap_developer: '#64748B',
  read_only:      '#94A3B8',
}

// ─── Markdown Renderer ────────────────────────────────────────────────────────
// Renders markdown with GFM tables and ABAP/SQL/JSON syntax highlighting.
const MD_COMPONENTS = {
  code({ node, inline, className, children, ...props }) {
    const lang = (className || '').replace('language-', '').toLowerCase() || 'abap'
    const code = String(children).replace(/\n$/, '')
    if (inline) {
      return <code className="inline-code" {...props}>{children}</code>
    }
    return (
      <div className="code-block-wrap">
        <div className="code-block-header">
          <span className="code-lang-badge">{lang.toUpperCase()}</span>
          <button
            className="code-copy-btn"
            onClick={() => navigator.clipboard.writeText(code)}
            title="Copy to clipboard"
          >Copy</button>
        </div>
        <SyntaxHighlighter
          style={vscDarkPlus}
          language={lang}
          PreTag="div"
          customStyle={{ margin: 0, borderRadius: '0 0 8px 8px', fontSize: 12, lineHeight: 1.5 }}
          {...props}
        >
          {code}
        </SyntaxHighlighter>
      </div>
    )
  },
  table({ children }) {
    return (
      <div className="md-table-wrap">
        <table className="md-table">{children}</table>
      </div>
    )
  },
  th({ children }) { return <th className="md-th">{children}</th> },
  td({ children, ...props }) {
    const val = String(children)
    return <td className={`md-td ${statusClass(val)}`}>{children}</td>
  },
  a({ href, children }) {
    return <a href={href} target="_blank" rel="noreferrer" className="md-link">{children}</a>
  },
  blockquote({ children }) {
    return <blockquote className="md-blockquote">{children}</blockquote>
  },
}

function MarkdownMessage({ content, className = '' }) {
  return (
    <div className={`markdown-body ${className}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD_COMPONENTS}>
        {content}
      </ReactMarkdown>
    </div>
  )
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function formatValue(val) {
  if (val === null || val === undefined) return '—'
  if (typeof val === 'boolean') return val ? 'Yes' : 'No'
  if (typeof val === 'object') return JSON.stringify(val)
  return String(val)
}
function statusClass(val) {
  const s = String(val).toLowerCase()
  if (['ok', 'open', 'active', 'paid', 'delivered', 'success', 'released'].includes(s)) return 'success'
  if (['blocked', 'error', 'cancelled', 'failed', 'poor'].includes(s)) return 'error'
  if (['pending', 'partial', 'in_progress', 'in_transit', 'modifiable', 'needs_review'].includes(s)) return 'warning'
  return ''
}

// ─── Login Screen ─────────────────────────────────────────────────────────────
function LoginScreen({ onLogin }) {
  const [userId, setUserId]     = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true); setError('')
    try {
      const res  = await fetch(`${API}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, password }),
      })
      const data = await res.json()
      if (!res.ok) { setError(data.detail || 'Invalid credentials'); return }
      onLogin(data)
    } catch {
      setError('Cannot connect to server. Is the API running on port 8000?')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-screen">
      <div className="login-card">
        <div className="login-logo-wrap">
          <div className="login-logo">SAP</div>
        </div>
        <h2 className="login-title">SAP AI Agent</h2>
        <p className="login-subtitle">Natural Language ERP Interface</p>
        <form onSubmit={handleSubmit} className="login-form">
          <div className="form-group">
            <label className="form-label">User ID</label>
            <input
              className="form-input" value={userId}
              onChange={e => setUserId(e.target.value)}
              placeholder="admin" autoFocus autoComplete="username"
            />
          </div>
          <div className="form-group">
            <label className="form-label">Password</label>
            <input
              className="form-input" type="password" value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="••••••••" autoComplete="current-password"
            />
          </div>
          {error && <div className="login-error">⚠ {error}</div>}
          <button className="btn-primary login-btn" type="submit" disabled={!userId || !password || loading}>
            {loading ? 'Signing in…' : 'Sign In →'}
          </button>
        </form>
        <div className="login-demo-hint">
          <span>Demo accounts:</span>
          <code>admin / Admin@123</code>
          <code>fi_user / Finance@123</code>
          <code>hr_user / HR@123</code>
          <code>demo / demo</code>
        </div>
      </div>
    </div>
  )
}

// ─── Dev Secret Warning ───────────────────────────────────────────────────────
function DevWarningBanner() {
  const [visible, setVisible] = useState(true)
  if (!visible) return null
  return (
    <div className="dev-warning-bar">
      <span>⚠ Dev mode: JWT secret key is insecure. Set <code>JWT_SECRET_KEY</code> env var before production deployment.</span>
      <button onClick={() => setVisible(false)}>✕</button>
    </div>
  )
}

// ─── SAP Source Badge ─────────────────────────────────────────────────────────
function SapSourceBadge({ source }) {
  if (!source) return null
  return (
    <div className="sap-source-badge">
      <span className="sap-source-icon">🔗</span>
      <span>Verify in SAP:</span>
      <strong>{source.tcode}</strong>
      {source.bapi && source.bapi !== 'N/A' && (
        <><span className="sap-source-sep">·</span><span className="sap-source-detail">BAPI: {source.bapi}</span></>
      )}
      {source.table && source.table !== 'N/A' && (
        <><span className="sap-source-sep">·</span><span className="sap-source-detail">Table: {source.table}</span></>
      )}
    </div>
  )
}

// ─── Tool Result Renderer ─────────────────────────────────────────────────────
function ToolResult({ result }) {
  if (!result || typeof result !== 'object') return null
  // Strip metadata fields from display
  const display = Object.fromEntries(
    Object.entries(result).filter(([k]) => !['sap_source', 'status'].includes(k))
  )
  const isArray = Array.isArray(display)
  const isArrayOfObjects = isArray && display.length > 0 && typeof display[0] === 'object'

  if (isArrayOfObjects) {
    const keys = Object.keys(display[0])
    return (
      <div className="tool-result-card">
        <div className="tool-result-header">📋 Result ({display.length} items)</div>
        <div className="tool-result-body">
          <table className="result-table">
            <thead><tr>{keys.map(k => <th key={k}>{k.replace(/_/g,' ').toUpperCase()}</th>)}</tr></thead>
            <tbody>
              {display.map((row, i) => (
                <tr key={i}>{keys.map(k => <td key={k} className={statusClass(row[k])}>{formatValue(row[k])}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    )
  }

  const entries = Object.entries(display).filter(([, v]) => typeof v !== 'object' || v === null)
  const nested  = Object.entries(display).filter(([, v]) => typeof v === 'object' && v !== null)

  return (
    <div className="tool-result-card">
      <div className="tool-result-header">📋 Tool Data</div>
      <div className="tool-result-body">
        {entries.length > 0 && (
          <div className="result-kv" style={{ marginBottom: nested.length ? 10 : 0 }}>
            {entries.map(([k, v]) => (
              <span key={k}>
                <span className="kv-key">{k.replace(/_/g,' ')}:</span>
                <span className={`kv-val ${statusClass(v)}`}>{formatValue(v)}</span>
              </span>
            ))}
          </div>
        )}
        {nested.map(([k, v]) => (
          <div key={k} style={{ marginTop: 8 }}>
            <div style={{ fontSize:11, fontWeight:600, color:'var(--text-secondary)', marginBottom:4, textTransform:'uppercase', letterSpacing:'0.5px' }}>{k.replace(/_/g,' ')}</div>
            {Array.isArray(v) ? (
              <div style={{ fontSize: 12 }}>{v.join(', ')}</div>
            ) : (
              <div className="result-kv">
                {Object.entries(v || {}).map(([kk, vv]) => (
                  <span key={kk}>
                    <span className="kv-key">{kk.replace(/_/g,' ')}:</span>
                    <span className={`kv-val ${statusClass(vv)}`}>{formatValue(vv)}</span>
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Research Report Display ───────────────────────────────────────────────────
function AnomalyPanel({ anomalies }) {
  if (!anomalies || anomalies.length === 0) return null
  const icon = { HIGH: '🔴', MEDIUM: '🟠', LOW: '🟡' }
  const bg   = { HIGH: '#FEE2E2', MEDIUM: '#FFF7ED', LOW: '#FEFCE8' }
  const border = { HIGH: '#FCA5A5', MEDIUM: '#FED7AA', LOW: '#FEF08A' }
  return (
    <div className="anomaly-panel">
      <div className="anomaly-header">Anomalies & Alerts ({anomalies.length})</div>
      {anomalies.map((a, i) => (
        <div key={i} className="anomaly-item" style={{ background: bg[a.severity], borderLeft: `3px solid ${border[a.severity]}` }}>
          <span className="anomaly-icon">{icon[a.severity] || '⚪'}</span>
          <span className="anomaly-severity" style={{ color: a.severity === 'HIGH' ? '#DC2626' : a.severity === 'MEDIUM' ? '#D97706' : '#CA8A04' }}>
            {a.severity}
          </span>
          <span className="anomaly-msg">{a.message}</span>
        </div>
      ))}
    </div>
  )
}

function ResearchReport({ result }) {
  const [expanded, setExpanded] = useState(true)
  if (!result || !result.formatted_report) return null
  return (
    <div className="research-report-card">
      <div className="research-report-header" onClick={() => setExpanded(e => !e)}>
        <span>Research Report</span>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {result.entity_id && <span className="entity-badge">{result.entity_id}</span>}
          {result.tools_run && result.tools_run.length > 0 && (
            <span className="tools-count-badge">{result.tools_run.length} tools</span>
          )}
          <span>{expanded ? '▲' : '▼'}</span>
        </div>
      </div>
      {expanded && (
        <div className="research-report-body">
          <AnomalyPanel anomalies={result.anomalies} />
          <div className="research-tools-used">
            {(result.tools_run || []).map(t => (
              <span key={t} className="tool-badge" style={{ fontSize: 10 }}>⚡ {t}</span>
            ))}
          </div>
          <MarkdownMessage content={result.formatted_report} className="research-markdown-body" />
          {result.sources_used && result.sources_used.length > 0 && (
            <div className="research-sources">
              <span>SAP Sources: </span>
              {result.sources_used.map((s, i) => <span key={i} className="sap-src-chip">{s}</span>)}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Message Bubble ───────────────────────────────────────────────────────────
function MessageRow({ msg }) {
  const isUser = msg.role === 'user'
  return (
    <div className={`message-row ${isUser ? 'user' : 'bot'}`}>
      <div className={`avatar ${isUser ? 'user-av' : 'bot-av'}`}>{isUser ? 'U' : msg.research_mode ? '🔬' : '🤖'}</div>
      <div className="message-content">
        {msg.research_mode
          ? <ResearchReport result={msg.research_result} />
          : msg.role === 'user'
            ? <div className="message-bubble">{msg.content}</div>
            : <div className="message-bubble bot-bubble"><MarkdownMessage content={msg.content} /></div>
        }
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', marginTop: 4 }}>
          {msg.tool_called && !msg.research_mode && <span className="tool-badge">⚡ {msg.tool_called}</span>}
          {msg.research_mode && <span className="research-mode-badge">AUTO RESEARCH</span>}
          {msg.request_id && <span className="req-id-badge">ID: {msg.request_id.slice(0,8)}</span>}
        </div>
        {!msg.research_mode && msg.tool_result && <ToolResult result={msg.tool_result} />}
        {!msg.research_mode && msg.sap_source  && <SapSourceBadge source={msg.sap_source} />}
      </div>
    </div>
  )
}

function TypingIndicator() {
  return (
    <div className="typing-row">
      <div className="avatar bot-av">🤖</div>
      <div className="typing-bubble">
        <div className="typing-dot" /><div className="typing-dot" /><div className="typing-dot" />
      </div>
    </div>
  )
}

// ─── Settings Modal ───────────────────────────────────────────────────────────
function SettingsModal({ onClose, currentUser }) {
  const isAdmin = currentUser?.roles?.includes('admin')
  const [tab, setTab] = useState('sap')
  const [cfg, setCfg] = useState(null)
  const [mcpServers, setMcpServers] = useState([])
  const [testResult, setTestResult] = useState(null)
  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveStatus, setSaveStatus] = useState(null)
  const [newServer, setNewServer] = useState({ name: '', url: '', transport: 'sse', enabled: true })
  const [mcpTestResult, setMcpTestResult] = useState(null)
  const [mcpTesting, setMcpTesting] = useState(false)
  // Admin tabs state
  const [auditLogs, setAuditLogs] = useState([])
  const [auditLoading, setAuditLoading] = useState(false)
  const [users, setUsers] = useState([])
  const [usersLoading, setUsersLoading] = useState(false)
  const [newUser, setNewUser] = useState({ user_id: '', password: '', full_name: '', email: '', roles: ['read_only'] })
  const [createStatus, setCreateStatus] = useState(null)

  useEffect(() => {
    apiFetch('/config').then(r => r.json()).then(d => setCfg(d)).catch(() => {})
    apiFetch('/config/mcp-servers').then(r => r.json()).then(d => setMcpServers(d.servers || [])).catch(() => {})
  }, [])

  useEffect(() => {
    if (tab === 'audit' && isAdmin) {
      setAuditLoading(true)
      apiFetch('/audit/logs?limit=50').then(r => r.json()).then(d => setAuditLogs(d.logs || [])).catch(() => {}).finally(() => setAuditLoading(false))
    }
    if (tab === 'users' && isAdmin) {
      setUsersLoading(true)
      apiFetch('/auth/users').then(r => r.json()).then(d => setUsers(d.users || [])).catch(() => {}).finally(() => setUsersLoading(false))
    }
  }, [tab, isAdmin])

  const setSap    = (key, val) => setCfg(c => ({ ...c, sap: { ...c.sap, [key]: val } }))
  const setMcp    = (key, val) => setCfg(c => ({ ...c, mcp: { ...c.mcp, [key]: val } }))
  const setOllama = (key, val) => setCfg(c => ({ ...c, ollama: { ...c.ollama, [key]: val } }))

  const handleSave = async () => {
    setSaving(true); setSaveStatus(null)
    try {
      const res = await apiFetch('/config', { method: 'POST', body: JSON.stringify(cfg) })
      setSaveStatus(res.ok ? 'saved' : 'error')
    } catch { setSaveStatus('error') }
    finally { setSaving(false); setTimeout(() => setSaveStatus(null), 3000) }
  }

  const handleTestSap = async () => {
    setTesting(true); setTestResult(null)
    try {
      const res = await apiFetch('/config/test-sap', { method: 'POST' })
      setTestResult(await res.json())
    } catch { setTestResult({ success: false, message: 'Could not reach API server' }) }
    finally { setTesting(false) }
  }

  const handleAddMcpServer = async () => {
    if (!newServer.name || !newServer.url) return
    const res = await apiFetch('/config/mcp-servers', { method: 'POST', body: JSON.stringify(newServer) })
    if (res.ok) {
      const data = await apiFetch('/config/mcp-servers').then(r => r.json())
      setMcpServers(data.servers || [])
      setNewServer({ name: '', url: '', transport: 'sse', enabled: true })
    }
  }

  const handleRemoveMcpServer = async (name) => {
    await apiFetch(`/config/mcp-servers/${encodeURIComponent(name)}`, { method: 'DELETE' })
    setMcpServers(s => s.filter(x => x.name !== name))
  }

  const handleTestMcp = async () => {
    if (!newServer.url) return
    setMcpTesting(true); setMcpTestResult(null)
    try {
      const res = await apiFetch('/config/test-mcp', { method: 'POST', body: JSON.stringify(newServer) })
      setMcpTestResult(await res.json())
    } catch { setMcpTestResult({ success: false, message: 'Could not reach API server' }) }
    finally { setMcpTesting(false) }
  }

  const handleCreateUser = async () => {
    setCreateStatus(null)
    try {
      const res = await apiFetch('/auth/users', { method: 'POST', body: JSON.stringify(newUser) })
      const data = await res.json()
      if (!res.ok) { setCreateStatus({ ok: false, msg: data.detail }); return }
      setUsers(prev => [...prev, data.user])
      setNewUser({ user_id: '', password: '', full_name: '', email: '', roles: ['read_only'] })
      setCreateStatus({ ok: true, msg: `User '${data.user.user_id}' created` })
    } catch { setCreateStatus({ ok: false, msg: 'Request failed' }) }
    setTimeout(() => setCreateStatus(null), 4000)
  }

  const handleDeactivate = async (uid) => {
    await apiFetch(`/auth/users/${uid}/deactivate`, { method: 'PATCH' })
    setUsers(prev => prev.map(u => u.user_id === uid ? { ...u, active: false } : u))
  }

  if (!cfg) return (
    <div className="modal-overlay">
      <div className="modal-box" style={{ alignItems: 'center', justifyContent: 'center', minHeight: 200 }}>
        <p style={{ color: 'var(--text-muted)', fontSize: 14 }}>Loading configuration…</p>
      </div>
    </div>
  )

  const connType = cfg.sap?.connection_type || 'mock'
  const authType = cfg.sap?.auth_type || 'basic'
  const allRoles = ['admin','fi_co_analyst','mm_analyst','sd_analyst','hr_manager','pp_planner','abap_developer','read_only']

  const tabs = [
    { id: 'sap',    label: '🔗 SAP Connection' },
    { id: 'mcp',    label: '🔌 MCP Servers' },
    { id: 'ollama', label: '🤖 Ollama / LLM' },
    ...(isAdmin ? [{ id: 'users', label: '👥 Users & Roles' }, { id: 'audit', label: '📋 Audit Logs' }] : []),
  ]

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal-box">
        <div className="modal-header">
          <span className="modal-title">⚙️ Configuration</span>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>

        <div className="modal-tabs">
          {tabs.map(t => (
            <button key={t.id} className={`modal-tab ${tab === t.id ? 'active' : ''}`} onClick={() => setTab(t.id)}>
              {t.label}
            </button>
          ))}
        </div>

        <div className="modal-body">

          {/* ── SAP Connection Tab ─────────── */}
          {tab === 'sap' && (
            <>
              <div>
                <div className="form-section-title">Connection Type</div>
                <div className="conn-type-group" style={{ marginTop: 12 }}>
                  {[
                    { value: 'mock',       icon: '🎭', label: 'Mock / Demo', sub: 'Simulated data, no SAP needed' },
                    { value: 'cloud',      icon: '☁️', label: 'SAP Cloud',   sub: 'BTP, S/4HANA Cloud, Rise' },
                    { value: 'on_premise', icon: '🏢', label: 'On-Premise',  sub: 'SAP ECC, S/4HANA On-Prem' },
                  ].map(opt => (
                    <button key={opt.value} className={`conn-type-btn ${connType === opt.value ? 'active' : ''}`} onClick={() => setSap('connection_type', opt.value)}>
                      <div className="conn-type-icon">{opt.icon}</div>
                      <div className="conn-type-label">{opt.label}</div>
                      <div className="conn-type-sub">{opt.sub}</div>
                    </button>
                  ))}
                </div>
              </div>

              {connType !== 'mock' && (
                <>
                  <div className="form-section-title" style={{ marginTop: 4 }}>System Details</div>
                  <div className="form-group">
                    <label className="form-label">System URL *</label>
                    <input className="form-input mono" value={cfg.sap.system_url || ''} onChange={e => setSap('system_url', e.target.value)} placeholder={connType === 'cloud' ? 'https://myXXXXXX.s4hana.ondemand.com' : 'https://sap-host:44300'} />
                  </div>
                  <div className="form-row">
                    <div className="form-group">
                      <label className="form-label">Client</label>
                      <input className="form-input" value={cfg.sap.client || ''} onChange={e => setSap('client', e.target.value)} placeholder="100" maxLength={3} />
                    </div>
                    <div className="form-group">
                      <label className="form-label">Authentication</label>
                      <select className="form-select" value={authType} onChange={e => setSap('auth_type', e.target.value)}>
                        {AUTH_TYPES.map(a => <option key={a.value} value={a.value}>{a.label}</option>)}
                      </select>
                    </div>
                  </div>
                  {authType === 'basic' && (
                    <div className="form-row">
                      <div className="form-group">
                        <label className="form-label">Username</label>
                        <input className="form-input" value={cfg.sap.username || ''} onChange={e => setSap('username', e.target.value)} placeholder="RFC_USER" autoComplete="username" />
                      </div>
                      <div className="form-group">
                        <label className="form-label">Password</label>
                        <input className="form-input" type="password" value={cfg.sap.password || ''} onChange={e => setSap('password', e.target.value)} placeholder="••••••••" autoComplete="current-password" />
                      </div>
                    </div>
                  )}
                  {authType === 'oauth2' && (
                    <>
                      <div className="form-group">
                        <label className="form-label">Token URL</label>
                        <input className="form-input mono" value={cfg.sap.oauth_token_url || ''} onChange={e => setSap('oauth_token_url', e.target.value)} placeholder="https://myXXXXXX.authentication.eu10.hana.ondemand.com/oauth/token" />
                      </div>
                      <div className="form-row">
                        <div className="form-group">
                          <label className="form-label">Client ID</label>
                          <input className="form-input" value={cfg.sap.oauth_client_id || ''} onChange={e => setSap('oauth_client_id', e.target.value)} placeholder="sb-xxxxx" />
                        </div>
                        <div className="form-group">
                          <label className="form-label">Client Secret</label>
                          <input className="form-input" type="password" value={cfg.sap.oauth_client_secret || ''} onChange={e => setSap('oauth_client_secret', e.target.value)} placeholder="••••••••" />
                        </div>
                      </div>
                    </>
                  )}
                  {authType === 'x509' && (
                    <div className="form-group">
                      <label className="form-label">Certificate Path</label>
                      <input className="form-input mono" value={cfg.sap.x509_cert_path || ''} onChange={e => setSap('x509_cert_path', e.target.value)} placeholder="/path/to/client.pem" />
                    </div>
                  )}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <button className="btn-secondary" onClick={handleTestSap} disabled={testing}>{testing ? 'Testing…' : '🔍 Test Connection'}</button>
                    {testResult && (
                      <div className={`test-result ${testResult.success ? 'success' : 'error'}`}>
                        {testResult.success ? '✅' : '❌'} {testResult.message}
                      </div>
                    )}
                  </div>
                </>
              )}
              {connType === 'mock' && (
                <div className="test-result success">🎭 Mock mode active — all 30 tools use built-in simulated SAP data. No credentials needed.</div>
              )}
            </>
          )}

          {/* ── MCP Servers Tab ─────────────── */}
          {tab === 'mcp' && (
            <>
              <div>
                <div className="form-section-title">Built-in MCP Server</div>
                <div style={{ marginTop: 12, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600 }}>SAP Tools — stdio transport</div>
                    <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>All 30 SAP tools (FI/CO, MM, SD, HR, PP, ABAP) via <code style={{ fontSize: 11 }}>python mcp_server.py</code></div>
                  </div>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                    <input type="checkbox" checked={cfg.mcp?.builtin_enabled ?? true} onChange={e => setMcp('builtin_enabled', e.target.checked)} />
                    <span style={{ fontSize: 13 }}>Enabled</span>
                  </label>
                </div>
              </div>
              <div>
                <div className="form-section-title">Custom External MCP Servers</div>
                <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {mcpServers.filter(s => s.type === 'custom').length === 0 && <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>No custom servers configured yet.</p>}
                  {mcpServers.filter(s => s.type === 'custom').map(s => (
                    <div className="mcp-server-item" key={s.name}>
                      <div className="mcp-server-info">
                        <span className="mcp-server-name">{s.name}</span>
                        <span className="mcp-server-url">{s.url}</span>
                        <div style={{ display: 'flex', gap: 4, marginTop: 4 }}>
                          <span className="mcp-badge custom">{s.transport}</span>
                          <span className={`mcp-badge ${s.enabled ? 'enabled' : 'disabled'}`}>{s.enabled ? 'enabled' : 'disabled'}</span>
                        </div>
                      </div>
                      <div className="mcp-server-actions">
                        <button className="btn-danger" onClick={() => handleRemoveMcpServer(s.name)}>Remove</button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <div className="form-section-title">Add New MCP Server</div>
                <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
                  <div className="form-row">
                    <div className="form-group">
                      <label className="form-label">Server Name *</label>
                      <input className="form-input" value={newServer.name} onChange={e => setNewServer(s => ({ ...s, name: e.target.value }))} placeholder="My SAP MCP Server" />
                    </div>
                    <div className="form-group">
                      <label className="form-label">Transport</label>
                      <select className="form-select" value={newServer.transport} onChange={e => setNewServer(s => ({ ...s, transport: e.target.value }))}>
                        <option value="sse">SSE (HTTP)</option>
                        <option value="stdio">stdio (local process)</option>
                      </select>
                    </div>
                  </div>
                  <div className="form-group">
                    <label className="form-label">Server URL *</label>
                    <input className="form-input mono" value={newServer.url} onChange={e => setNewServer(s => ({ ...s, url: e.target.value }))} placeholder="http://localhost:8001/sse" />
                  </div>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <button className="btn-primary" onClick={handleAddMcpServer} disabled={!newServer.name || !newServer.url}>Add Server</button>
                    <button className="btn-secondary" onClick={handleTestMcp} disabled={!newServer.url || mcpTesting}>{mcpTesting ? 'Testing…' : '🔍 Test'}</button>
                    {mcpTestResult && (
                      <div className={`test-result ${mcpTestResult.success ? 'success' : 'error'}`} style={{ padding: '6px 12px' }}>
                        {mcpTestResult.success ? '✅' : '❌'} {mcpTestResult.message}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </>
          )}

          {/* ── Ollama Tab ───────────────────── */}
          {tab === 'ollama' && (
            <>
              <div className="form-group">
                <label className="form-label">Ollama Server URL</label>
                <input className="form-input mono" value={cfg.ollama?.url || ''} onChange={e => setOllama('url', e.target.value)} placeholder="http://localhost:11434" />
                <span className="form-hint">Ollama must be bound to <code>127.0.0.1</code> only — never expose publicly. See <code>docs/SECURITY.md</code>.</span>
              </div>
              <div className="form-group">
                <label className="form-label">Default Model</label>
                <select className="form-select" value={cfg.ollama?.default_model || 'llama3.2'} onChange={e => setOllama('default_model', e.target.value)}>
                  {MODELS.map(m => <option key={m} value={m}>{m}</option>)}
                </select>
                <span className="form-hint">Pull before use: <code>ollama pull llama3.2</code>. See <code>docs/BENCHMARKS.md</code> for accuracy per module.</span>
              </div>
              <div style={{ padding: '12px 14px', background: '#F7F9FC', borderRadius: 8, fontSize: 12 }}>
                <div style={{ fontWeight: 700, marginBottom: 6, fontSize: 13 }}>Accuracy by module (llama3.2:8b)</div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '4px 16px', color: 'var(--text-secondary)' }}>
                  <span>FI/CO: <b style={{ color: '#16A34A' }}>88%</b></span>
                  <span>MM: <b style={{ color: '#16A34A' }}>85%</b></span>
                  <span>SD: <b style={{ color: '#16A34A' }}>87%</b></span>
                  <span>HR: <b style={{ color: '#D97706' }}>84%</b></span>
                  <span>PP: <b style={{ color: '#D97706' }}>82%</b></span>
                  <span>ABAP: <b style={{ color: '#D97706' }}>80%</b></span>
                </div>
                <div style={{ marginTop: 8, color: 'var(--text-muted)' }}>Full benchmarks: <code>docs/BENCHMARKS.md</code></div>
              </div>
            </>
          )}

          {/* ── Users & Roles Tab (admin) ──── */}
          {tab === 'users' && isAdmin && (
            <>
              <div>
                <div className="form-section-title">User Accounts</div>
                {usersLoading ? (
                  <p style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 12 }}>Loading users…</p>
                ) : (
                  <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {users.map(u => (
                      <div key={u.user_id} className="user-mgmt-row">
                        <div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <span style={{ fontWeight: 600, fontSize: 13 }}>{u.user_id}</span>
                            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{u.full_name}</span>
                            {!u.active && <span className="role-tag" style={{ background: '#FEF2F2', color: '#DC2626' }}>inactive</span>}
                          </div>
                          <div style={{ display: 'flex', gap: 4, marginTop: 4, flexWrap: 'wrap' }}>
                            {(u.roles || []).map(r => (
                              <span key={r} className="role-tag" style={{ background: ROLE_COLORS[r] + '20', color: ROLE_COLORS[r] }}>
                                {ROLE_LABELS[r] || r}
                              </span>
                            ))}
                          </div>
                        </div>
                        <div>
                          {u.active && u.user_id !== currentUser?.user_id && (
                            <button className="btn-danger" style={{ fontSize: 11 }} onClick={() => handleDeactivate(u.user_id)}>Deactivate</button>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div>
                <div className="form-section-title">Create User</div>
                <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
                  <div className="form-row">
                    <div className="form-group">
                      <label className="form-label">User ID *</label>
                      <input className="form-input" value={newUser.user_id} onChange={e => setNewUser(u => ({ ...u, user_id: e.target.value }))} placeholder="jsmith" autoComplete="off" />
                    </div>
                    <div className="form-group">
                      <label className="form-label">Password *</label>
                      <input className="form-input" type="password" value={newUser.password} onChange={e => setNewUser(u => ({ ...u, password: e.target.value }))} placeholder="••••••••" autoComplete="new-password" />
                    </div>
                  </div>
                  <div className="form-row">
                    <div className="form-group">
                      <label className="form-label">Full Name</label>
                      <input className="form-input" value={newUser.full_name} onChange={e => setNewUser(u => ({ ...u, full_name: e.target.value }))} placeholder="John Smith" />
                    </div>
                    <div className="form-group">
                      <label className="form-label">Email</label>
                      <input className="form-input" value={newUser.email} onChange={e => setNewUser(u => ({ ...u, email: e.target.value }))} placeholder="jsmith@company.com" />
                    </div>
                  </div>
                  <div className="form-group">
                    <label className="form-label">Role</label>
                    <select className="form-select" value={newUser.roles[0]} onChange={e => setNewUser(u => ({ ...u, roles: [e.target.value] }))}>
                      {allRoles.map(r => <option key={r} value={r}>{ROLE_LABELS[r] || r}</option>)}
                    </select>
                    <span className="form-hint">Roles control which SAP modules the user can access. HR salary data is restricted to hr_manager only.</span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <button className="btn-primary" onClick={handleCreateUser} disabled={!newUser.user_id || !newUser.password}>Create User</button>
                    {createStatus && (
                      <span style={{ fontSize: 12, color: createStatus.ok ? 'var(--success)' : 'var(--error)', fontWeight: 600 }}>
                        {createStatus.ok ? '✓' : '✗'} {createStatus.msg}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </>
          )}

          {/* ── Audit Logs Tab (admin) ────── */}
          {tab === 'audit' && isAdmin && (
            <>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div className="form-section-title">Recent Audit Log (SOX/GDPR)</div>
                <button className="btn-secondary" style={{ fontSize: 12, padding: '5px 12px' }}
                  onClick={() => { setAuditLoading(true); apiFetch('/audit/logs?limit=50').then(r => r.json()).then(d => setAuditLogs(d.logs || [])).finally(() => setAuditLoading(false)) }}>
                  ↻ Refresh
                </button>
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: -8 }}>
                Full logs written to <code>logs/audit_YYYY-MM-DD.jsonl</code> · Retain 7 years for SOX compliance
              </div>
              {auditLoading ? (
                <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>Loading audit logs…</p>
              ) : auditLogs.length === 0 ? (
                <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>No audit records yet. Records appear after the first /chat call.</p>
              ) : (
                <div style={{ overflowX: 'auto' }}>
                  <table className="result-table audit-table">
                    <thead>
                      <tr>
                        <th>Time</th><th>User</th><th>Role</th><th>Tool</th><th>Query</th><th>ms</th>
                      </tr>
                    </thead>
                    <tbody>
                      {auditLogs.map((log, i) => (
                        <tr key={i}>
                          <td style={{ whiteSpace: 'nowrap', fontSize: 11 }}>{new Date(log.timestamp).toLocaleTimeString()}</td>
                          <td style={{ fontWeight: 600 }}>{log.user_id}</td>
                          <td>{(log.user_roles || []).join(', ')}</td>
                          <td style={{ fontFamily: 'monospace', fontSize: 11 }}>{log.tool_called || '—'}</td>
                          <td style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={log.query}>{log.query}</td>
                          <td>{log.duration_ms}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>

        <div className="modal-footer">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            {saveStatus === 'saved' && <span className="save-status">✓ Saved successfully</span>}
            {saveStatus === 'error'  && <span className="save-status error-text">✗ Save failed</span>}
            {['sap', 'mcp', 'ollama'].includes(tab) && (
              <button className="btn-primary" onClick={handleSave} disabled={saving || !isAdmin}>
                {saving ? 'Saving…' : isAdmin ? 'Save Configuration' : 'Admin only'}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Sidebar ──────────────────────────────────────────────────────────────────
function Sidebar({ activeModule, onModuleClick, onReset, sapMode, allowedModules }) {
  const visibleModules = MODULES.filter(m =>
    m.id === 'all' || allowedModules === null || allowedModules.includes(m.moduleKey)
  )
  return (
    <div className="sidebar">
      <div className="sidebar-header">SAP Modules</div>
      <div className="sidebar-modules">
        {visibleModules.map(mod => (
          <div className="module-item" key={mod.id}>
            <button className={`module-btn ${activeModule === mod.id ? 'active' : ''}`} onClick={() => onModuleClick(mod.id)}>
              <div className="module-icon" style={{ background: mod.bg }}>{mod.icon}</div>
              <div className="module-label">
                <span className="module-name">{mod.name}</span>
                <span className="module-desc">{mod.desc}</span>
              </div>
            </button>
          </div>
        ))}
      </div>
      <div className="sidebar-footer">
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8, textAlign: 'center' }}>
          {sapMode === 'mock' ? '🎭 Mock mode' : sapMode === 'cloud' ? '☁️ SAP Cloud' : '🏢 On-Premise'}
        </div>
        <button className="reset-btn" onClick={onReset}>🗑 Clear Conversation</button>
      </div>
    </div>
  )
}

// ─── Right Panel ──────────────────────────────────────────────────────────────
function RightPanel({ tools, activeModule }) {
  const filtered = activeModule === 'all' ? tools : tools.filter(t => t.module === activeModule)
  return (
    <div className="right-panel">
      <div className="panel-header">Available Tools ({filtered.length})</div>
      <div className="panel-body">
        {filtered.map(tool => (
          <div className="tool-list-item" key={tool.name}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
              <div className="tool-fn">{tool.name}</div>
              {tool.sap_source?.tcode && (
                <span className="tool-tcode-badge">{tool.sap_source.tcode}</span>
              )}
            </div>
            <div className="tool-desc">{tool.description}</div>
          </div>
        ))}
        {filtered.length === 0 && <p style={{ fontSize: 13, color: 'var(--text-muted)', padding: '8px 0' }}>No accessible tools for this module.</p>}
      </div>
    </div>
  )
}

// ─── Main App ─────────────────────────────────────────────────────────────────
export default function App() {
  const [messages, setMessages]           = useState([])
  const [input, setInput]                 = useState('')
  const [loading, setLoading]             = useState(false)
  const [model, setModel]                 = useState('llama3.2')
  const [activeModule, setActiveModule]   = useState('all')
  const [ollamaStatus, setOllamaStatus]   = useState('checking')
  const [sapMode, setSapMode]             = useState('mock')
  const [tools, setTools]                 = useState([])
  const [showSettings, setShowSettings]   = useState(false)
  const [researchMode, setResearchMode]   = useState(false)

  // Auth state
  const [authToken, setAuthToken]         = useState(() => localStorage.getItem('sap_agent_token'))
  const [currentUser, setCurrentUser]     = useState(() => {
    try { return JSON.parse(localStorage.getItem('sap_agent_user') || 'null') } catch { return null }
  })
  const [authEnabled, setAuthEnabled]     = useState(true)
  const [devSecretWarn, setDevSecretWarn] = useState(false)
  const [allowedModules, setAllowedModules] = useState(null)  // null = all (admin/auth disabled)

  const bottomRef = useRef(null)
  const inputRef  = useRef(null)

  // Determine if we should show the login screen
  const needsLogin = authEnabled && !authToken

  const handleLogin = useCallback((data) => {
    localStorage.setItem('sap_agent_token', data.access_token)
    localStorage.setItem('sap_agent_user', JSON.stringify({ user_id: data.user_id, roles: data.roles, full_name: data.full_name }))
    setAuthToken(data.access_token)
    setCurrentUser({ user_id: data.user_id, roles: data.roles, full_name: data.full_name })
    if (data.warning) setDevSecretWarn(true)
  }, [])

  const handleLogout = useCallback(() => {
    localStorage.removeItem('sap_agent_token')
    localStorage.removeItem('sap_agent_user')
    setAuthToken(null)
    setCurrentUser(null)
    setMessages([])
    setAllowedModules(null)
  }, [])

  // Health check — also reveals auth_enabled and dev_secret
  useEffect(() => {
    const check = async () => {
      try {
        const res  = await apiFetch('/health')
        if (res.status === 401) { handleLogout(); return }
        const data = await res.json()
        setOllamaStatus(data.llm_connected ? 'connected' : 'disconnected')
        if (data.model)    setModel(data.model)
        if (data.sap_mode) setSapMode(data.sap_mode)
        if (data.auth_enabled === false) setAuthEnabled(false)
        if (data.dev_secret) setDevSecretWarn(true)
      } catch { setOllamaStatus('disconnected') }
    }
    check()
    const id = setInterval(check, 30000)
    return () => clearInterval(id)
  }, [authToken, handleLogout])

  // Fetch current user's allowed modules after login
  useEffect(() => {
    if (!authToken) return
    apiFetch('/auth/me').then(r => {
      if (r.status === 401) { handleLogout(); return }
      return r.json()
    }).then(data => {
      if (!data) return
      if (data.roles?.includes('admin')) {
        setAllowedModules(null)  // admin sees all
      } else {
        setAllowedModules(data.allowed_modules || [])
        // Auto-select first accessible module for non-admin
        if (data.allowed_modules?.length === 1) {
          const mod = MODULES.find(m => m.moduleKey === data.allowed_modules[0])
          if (mod) setActiveModule(mod.id)
        }
      }
    }).catch(() => {})
  }, [authToken, handleLogout])

  // Load role-filtered tools
  useEffect(() => {
    if (needsLogin) return
    apiFetch('/tools').then(r => {
      if (r.status === 401) { handleLogout(); return }
      return r.json()
    }).then(d => d && setTools(d.tools || [])).catch(() => {})
  }, [authToken, needsLogin, handleLogout])

  // Auto-scroll
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, loading])

  const handleSettingsClose = () => {
    setShowSettings(false)
    apiFetch('/health').then(r => r.json()).then(d => {
      if (d.model)    setModel(d.model)
      if (d.sap_mode) setSapMode(d.sap_mode)
      setOllamaStatus(d.llm_connected ? 'connected' : 'disconnected')
    }).catch(() => {})
  }

  const sendResearch = useCallback(async (text) => {
    const msg = text.trim()
    if (!msg || loading) return
    setMessages(prev => [...prev, { role: 'user', content: msg }])
    setInput('')
    setLoading(true)
    try {
      const res = await apiFetch('/research', {
        method: 'POST',
        body: JSON.stringify({ query: msg }),
      })
      if (res.status === 401) { handleLogout(); return }
      const data = await res.json()
      if (!res.ok) {
        setMessages(prev => [...prev, { role: 'bot', content: `Error: ${data.detail || 'Unknown error'}`, research_mode: false }])
        return
      }
      setMessages(prev => [...prev, {
        role: 'bot',
        content: data.report,
        research_mode: true,
        research_result: {
          formatted_report: data.report,
          anomalies: data.anomalies || [],
          tools_run: data.tools_used || [],
          sources_used: data.sap_sources || [],
          entity_type: data.entity_type,
          entity_id: data.entity_id,
        },
        request_id: data.request_id,
      }])
    } catch {
      setMessages(prev => [...prev, { role: 'bot', content: 'Error: Could not reach the SAP AI Agent API. Make sure the server is running on port 8000.' }])
    } finally {
      setLoading(false)
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [loading, handleLogout])

  const sendMessage = useCallback(async (text) => {
    if (researchMode) return sendResearch(text)
    const msg = text.trim()
    if (!msg || loading) return
    setMessages(prev => [...prev, { role: 'user', content: msg }])
    setInput('')
    setLoading(true)
    try {
      const res  = await apiFetch('/chat', {
        method: 'POST',
        body: JSON.stringify({ message: msg, model }),
      })
      if (res.status === 401) { handleLogout(); return }
      const data = await res.json()
      if (!res.ok) {
        setMessages(prev => [...prev, { role: 'bot', content: `Error: ${data.detail || 'Unknown error'}`, tool_called: null, tool_result: null }])
        return
      }
      setMessages(prev => [...prev, {
        role: 'bot',
        content:     data.response,
        tool_called: data.tool_called,
        tool_result: data.tool_result,
        sap_source:  data.sap_source,
        request_id:  data.request_id,
      }])
    } catch {
      setMessages(prev => [...prev, { role: 'bot', content: 'Error: Could not reach the SAP AI Agent API. Make sure the server is running on port 8000.' }])
    } finally {
      setLoading(false)
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [loading, model, handleLogout, researchMode, sendResearch])

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(input) }
  }

  const handleReset = async () => {
    setMessages([])
    try { await apiFetch('/reset', { method: 'POST' }) } catch {}
  }

  const currentModule = MODULES.find(m => m.id === activeModule) || MODULES[0]
  const showExamples  = messages.length === 0
  const statusLabel   = { checking: 'Checking…', connected: 'LLM Connected', disconnected: 'LLM Offline' }[ollamaStatus]
  const primaryRole   = currentUser?.roles?.[0]

  // Show login screen if auth is required and no token
  if (needsLogin) {
    return <LoginScreen onLogin={handleLogin} />
  }

  return (
    <div className="app-shell">
      {showSettings && <SettingsModal onClose={handleSettingsClose} currentUser={currentUser} />}

      {devSecretWarn && <DevWarningBanner />}

      {/* Top Bar */}
      <header className="topbar">
        <div className="topbar-brand">
          <div className="topbar-logo">SAP</div>
          <div>
            <div className="topbar-title">SAP AI Agent</div>
            <div className="topbar-subtitle">Natural Language ERP Interface</div>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div className="topbar-status">
            <div className={`status-dot ${ollamaStatus}`} />
            <span>{statusLabel}</span>
          </div>
          {currentUser && (
            <div className="user-chip">
              <div className="user-chip-avatar">{(currentUser.full_name || currentUser.user_id)[0].toUpperCase()}</div>
              <div className="user-chip-info">
                <span className="user-chip-name">{currentUser.full_name || currentUser.user_id}</span>
                {primaryRole && (
                  <span className="role-tag" style={{ background: (ROLE_COLORS[primaryRole] || '#888') + '30', color: ROLE_COLORS[primaryRole] || '#888', fontSize: 10 }}>
                    {ROLE_LABELS[primaryRole] || primaryRole}
                  </span>
                )}
              </div>
              <button className="logout-btn" onClick={handleLogout} title="Sign out">⏏</button>
            </div>
          )}
          <button className="settings-btn" onClick={() => setShowSettings(true)} title="Configuration">⚙️</button>
        </div>
      </header>

      <div className="body-row">
        <Sidebar
          activeModule={activeModule}
          onModuleClick={setActiveModule}
          onReset={handleReset}
          sapMode={sapMode}
          allowedModules={allowedModules}
        />

        {/* Chat */}
        <div className="chat-area">
          {showExamples ? (
            <div className="examples-panel">
              <div className="examples-hero">
                <div style={{ fontSize: 48, marginBottom: 12 }}>{currentModule.icon}</div>
                <h2>Ask anything about {currentModule.name}</h2>
                <p>{currentModule.desc} — try one of these examples or type your own query</p>
              </div>
              <div className="examples-grid">
                {currentModule.examples.map((ex, i) => (
                  <button key={i} className="example-chip" onClick={() => sendMessage(ex)}>{ex}</button>
                ))}
              </div>
            </div>
          ) : (
            <div className="messages-list">
              {messages.map((msg, i) => <MessageRow key={i} msg={msg} />)}
              {loading && <TypingIndicator />}
              <div ref={bottomRef} />
            </div>
          )}

          <div className="input-bar">
            <select className="model-select" value={model} onChange={e => setModel(e.target.value)} title="Select Ollama model" disabled={researchMode}>
              {MODELS.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
            <button
              className={`research-toggle-btn ${researchMode ? 'active' : ''}`}
              onClick={() => setResearchMode(r => !r)}
              title="Toggle Auto Research mode — chains multiple SAP tools automatically"
            >
              🔬 {researchMode ? 'Research ON' : 'Research'}
            </button>
            <div className="input-wrapper">
              <textarea
                ref={inputRef} className="chat-input" rows={1}
                value={input} onChange={e => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={researchMode
                  ? 'Research any SAP entity — e.g. "research vendor V001" or "deep dive on MAT002"'
                  : `Ask about ${currentModule.name}… (Enter to send, Shift+Enter for newline)`
                }
                disabled={loading}
                style={researchMode ? { borderColor: '#7C3AED', boxShadow: '0 0 0 2px #7C3AED22' } : {}}
              />
              <button className="send-btn" onClick={() => sendMessage(input)} disabled={!input.trim() || loading} title="Send"
                style={researchMode ? { background: '#7C3AED' } : {}}
              >
                {loading ? <div className="spinner" /> : researchMode ? '🔬' : '↑'}
              </button>
            </div>
          </div>
        </div>

        <RightPanel tools={tools} activeModule={activeModule} />
      </div>
    </div>
  )
}
