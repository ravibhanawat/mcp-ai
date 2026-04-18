import { useState, useEffect, useRef, useCallback } from 'react'
import './App.css'
import ReportWidget from './ReportWidget'
import { AbapReviewWidget, AbapCodeWidget } from './AbapWidget'
import ReceiptWidget from './ReceiptWidget'

const API = '/api'

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

async function apiFetch(path, options = {}) {
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

// ─── Constants ───────────────────────────────────────────────────────────────

const MODULES = [
  {
    id: 'all', name: 'All Modules', iconId: 'grid', desc: 'All SAP tools', moduleKey: null, color: '#0070D2',
    examples: ['Show me open purchase orders', 'List all employees', 'What is the budget for CC100?', 'Get customer info for C001']
  },
  {
    id: 'FI/CO', name: 'FI/CO', iconId: 'dollar', desc: 'Finance & Controlling', moduleKey: 'fi_co', color: '#16A34A',
    examples: ['Get vendor info for V001', 'Show invoice INV1001 status', 'List all open invoices', 'Budget vs actual for CC200']
  },
  {
    id: 'MM', name: 'MM', iconId: 'package', desc: 'Materials Management', moduleKey: 'mm', color: '#D97706',
    examples: ['Get material info for MAT001', 'Check stock for MAT002 at plant 1000', 'Show PO2001', 'Which materials need reordering?']
  },
  {
    id: 'SD', name: 'SD', iconId: 'cart', desc: 'Sales & Distribution', moduleKey: 'sd', color: '#7C3AED',
    examples: ['Get customer info for C002', 'Show sales order SO5001', 'Create a sales order for Wipro — 10 laptops']
  },
  {
    id: 'HR', name: 'HR', iconId: 'users', desc: 'Human Resources', moduleKey: 'hr', color: '#DB2777',
    examples: ['Get employee info for EMP001', 'Leave balance for EMP002', 'Show payslip for EMP001', 'Apply 3 days leave for EMP003']
  },
  {
    id: 'PP', name: 'PP', iconId: 'factory', desc: 'Production Planning', moduleKey: 'pp', color: '#0891B2',
    examples: ['Get production order PRD7001', 'Bill of materials for MAT001', 'Capacity utilization report']
  },
  {
    id: 'ABAP', name: 'ABAP', iconId: 'code', desc: 'Development & Basis', moduleKey: 'abap', color: '#64748B',
    examples: ['Show program ZREP_VENDOR_LIST', 'Transport DEVK900123 status', 'List ABAP programs in package ZFICO']
  },
  {
    id: 'RE', name: 'Real Estate', iconId: 'building', desc: 'Parivartan — Receipt & Docs', moduleKey: 're_analyst', color: '#B45309',
    examples: [
      'Show outstanding for customer ALEC001 unit T1-304',
      'Park a cheque of 5 lakhs for ALEC001 T1-304, cheque 891234',
      'Post receipt PRK00000001',
      'Check e-invoice for billing doc 9000010001',
      'Show broker payout status for BR001',
      'Get sales deed data for ALEC001 unit T1-304',
    ]
  },
]

const MODELS = ['llama3.2', 'llama3.1', 'mistral', 'gemma2', 'codellama']
const AUTH_TYPES = [
  { value: 'basic', label: 'Basic Auth' },
  { value: 'oauth2', label: 'OAuth 2.0' },
  { value: 'x509', label: 'X.509 Certificate' },
]
const ROLE_LABELS = {
  admin: 'Administrator', fi_co_analyst: 'FI/CO Analyst', mm_analyst: 'MM Analyst',
  sd_analyst: 'SD Analyst', hr_manager: 'HR Manager', pp_planner: 'PP Planner',
  abap_developer: 'ABAP Developer', re_analyst: 'RE Analyst', read_only: 'Read Only',
}
const ROLE_COLORS = {
  admin: '#0070D2', fi_co_analyst: '#16A34A', mm_analyst: '#D97706',
  sd_analyst: '#7C3AED', hr_manager: '#DB2777', pp_planner: '#0891B2',
  abap_developer: '#64748B', re_analyst: '#B45309', read_only: '#94A3B8',
}
const ALL_ROLES = ['admin', 'fi_co_analyst', 'mm_analyst', 'sd_analyst', 'hr_manager', 'pp_planner', 'abap_developer', 're_analyst', 'read_only']

// ─── SVG Icons ────────────────────────────────────────────────────────────────
// Zero-dependency icon library — pure inline SVG paths (Lucide-style strokes)

function Svg({ size = 16, children, className = '', style }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
      className={className} style={style}>
      {children}
    </svg>
  )
}

const Icons = {
  grid: () => <Svg><rect width="7" height="7" x="3" y="3" rx="1" /><rect width="7" height="7" x="14" y="3" rx="1" /><rect width="7" height="7" x="14" y="14" rx="1" /><rect width="7" height="7" x="3" y="14" rx="1" /></Svg>,
  dollar: () => <Svg><line x1="12" y1="2" x2="12" y2="22" /><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" /></Svg>,
  package: () => <Svg><path d="m7.5 4.27 9 5.15" /><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z" /><path d="m3.3 7 8.7 5 8.7-5" /><path d="M12 22V12" /></Svg>,
  cart: () => <Svg><circle cx="8" cy="21" r="1" /><circle cx="19" cy="21" r="1" /><path d="M2.05 2.05h2l2.66 12.42a2 2 0 0 0 2 1.58h9.78a2 2 0 0 0 1.95-1.57l1.65-7.43H5.12" /></Svg>,
  users: () => <Svg><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M22 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" /></Svg>,
  factory: () => <Svg><path d="M2 20a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8l-7 5V8l-7 5V4a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2Z" /><path d="M17 18h1" /><path d="M12 18h1" /><path d="M7 18h1" /></Svg>,
  code: () => <Svg><polyline points="16 18 22 12 16 6" /><polyline points="8 6 2 12 8 18" /></Svg>,
  settings: () => <Svg><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" /><circle cx="12" cy="12" r="3" /></Svg>,
  logout: () => <Svg><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><polyline points="16 17 21 12 16 7" /><line x1="21" y1="12" x2="9" y2="12" /></Svg>,
  x: () => <Svg size={14}><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></Svg>,
  send: () => <Svg size={15}><line x1="22" y1="2" x2="11" y2="13" /><polygon points="22 2 15 22 11 13 2 9 22 2" /></Svg>,
  trash: () => <Svg size={14}><polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" /></Svg>,
  copy: () => <Svg size={13}><rect width="14" height="14" x="8" y="8" rx="2" ry="2" /><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" /></Svg>,
  beaker: () => <Svg><path d="M4.5 3h15" /><path d="M6 3v16a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V3" /><path d="M6 14h12" /></Svg>,
  chevDown: () => <Svg size={14}><polyline points="6 9 12 15 18 9" /></Svg>,
  chevUp: () => <Svg size={14}><polyline points="18 15 12 9 6 15" /></Svg>,
  alert: () => <Svg size={14}><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" /><line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" /></Svg>,
  check: () => <Svg size={14}><polyline points="20 6 9 17 4 12" /></Svg>,
  terminal: () => <Svg size={14}><polyline points="4 17 10 11 4 5" /><line x1="12" y1="19" x2="20" y2="19" /></Svg>,
  refresh: () => <Svg size={14}><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" /><path d="M21 3v5h-5" /><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" /><path d="M8 16H3v5" /></Svg>,
  wifi: () => <Svg size={14}><path d="M5 12.55a11 11 0 0 1 14.08 0" /><path d="M1.42 9a16 16 0 0 1 21.16 0" /><path d="M8.53 16.11a6 6 0 0 1 6.95 0" /><line x1="12" y1="20" x2="12.01" y2="20" /></Svg>,
  wifiOff: () => <Svg size={14}><line x1="1" y1="1" x2="23" y2="23" /><path d="M16.72 11.06A10.94 10.94 0 0 1 19 12.55" /><path d="M5 12.55a10.94 10.94 0 0 1 5.17-2.39" /><path d="M10.71 5.05A16 16 0 0 1 22.56 9" /><path d="M1.42 9a15.91 15.91 0 0 1 4.7-2.88" /><path d="M8.53 16.11a6 6 0 0 1 6.95 0" /><line x1="12" y1="20" x2="12.01" y2="20" /></Svg>,
  panel: () => <Svg size={16}><rect width="18" height="18" x="3" y="3" rx="2" ry="2" /><line x1="9" y1="3" x2="9" y2="21" /></Svg>,
  building: () => <Svg><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><polyline points="9 22 9 12 15 12 15 22" /></Svg>,
}

function ModuleIcon({ iconId, color, size = 14 }) {
  const I = Icons[iconId] || Icons.grid
  return <span style={{ color, display: 'flex', alignItems: 'center' }}><I size={size} /></span>
}

// ─── Syntax Highlighter ───────────────────────────────────────────────────────
// Zero-dependency tokenizer. Returns an array of React span nodes.

const KW = {
  abap: new Set('DATA,TYPES,CLASS,METHOD,ENDMETHOD,IF,ELSE,ELSEIF,ENDIF,LOOP,AT,ENDAT,ENDLOOP,SELECT,FROM,INTO,WHERE,AND,OR,NOT,IS,MOVE,CLEAR,APPEND,READ,WRITE,FORM,ENDFORM,PERFORM,CALL,FUNCTION,TABLE,OF,TYPE,LIKE,IMPORTING,EXPORTING,CHANGING,EXCEPTIONS,BEGIN,END,REPORT,TABLES,PARAMETERS,CHECK,RETURN,RAISE,EXIT,CONTINUE,SORT,MODIFY,DELETE,INSERT,UPDATE,COMMIT,WHEN,CASE,ENDCASE,CREATE,OBJECT,FINAL,REFERENCE,USING,RESULT,LET,WHILE,ENDWHILE,DO,ENDDO,TRY,CATCH,ENDTRY,CONCATENATE,SPLIT,CONDENSE,FIND,REPLACE,TRANSLATE,GET,SET,COLLECT,NEW,FIELD-SYMBOLS,ASSIGN,COMPONENT,STRUCTURE,IMPLEMENTATION,DEFINITION,SECTION,PUBLIC,PRIVATE,PROTECTED,METHODS,ATTRIBUTES,CONSTANTS,VALUE,INITIAL'.split(',')),
  sql: new Set('SELECT,FROM,WHERE,AND,OR,NOT,IN,LIKE,BETWEEN,IS,NULL,INSERT,INTO,VALUES,UPDATE,SET,DELETE,CREATE,TABLE,ALTER,DROP,INDEX,JOIN,INNER,LEFT,RIGHT,OUTER,FULL,ON,GROUP,BY,HAVING,ORDER,ASC,DESC,LIMIT,OFFSET,DISTINCT,AS,UNION,ALL,EXISTS,COUNT,SUM,AVG,MIN,MAX,CASE,WHEN,THEN,ELSE,END,WITH,TOP,PRIMARY,KEY,FOREIGN,REFERENCES,CONSTRAINT,DEFAULT,UNIQUE'.split(',')),
  javascript: new Set('const,let,var,function,return,if,else,for,while,do,switch,case,break,continue,class,extends,import,export,default,from,async,await,new,this,super,try,catch,finally,throw,typeof,instanceof,null,undefined,true,false,of,in,delete,void,yield,static,get,set,constructor,NaN,Infinity'.split(',')),
  python: new Set('def,class,return,if,elif,else,for,while,import,from,as,in,not,and,or,is,None,True,False,try,except,finally,raise,with,pass,break,continue,lambda,yield,global,nonlocal,del,assert,self,super,print,len,range,type'.split(',')),
}

function tokenizeJSON(code) {
  const out = []; let i = 0; let k = 0
  const s = (cls, text) => <span key={k++} className={`tok-${cls}`}>{text}</span>
  while (i < code.length) {
    const ch = code[i]
    if (ch === '"') {
      let j = i + 1
      while (j < code.length && code[j] !== '"') { if (code[j] === '\\') j++; j++ }
      j++
      const str = code.slice(i, j)
      let nk = j; while (nk < code.length && /\s/.test(code[nk])) nk++
      out.push(code[nk] === ':' ? s('json-key', str) : s('string', str))
      i = j; continue
    }
    if (/[-0-9]/.test(ch) && (ch !== '-' || /[0-9]/.test(code[i + 1]))) {
      let j = i + 1; while (j < code.length && /[0-9.eE+\-]/.test(code[j])) j++
      out.push(s('number', code.slice(i, j))); i = j; continue
    }
    if (code.startsWith('true', i)) { out.push(s('boolean', 'true')); i += 4; continue }
    if (code.startsWith('false', i)) { out.push(s('boolean', 'false')); i += 5; continue }
    if (code.startsWith('null', i)) { out.push(s('null', 'null')); i += 4; continue }
    if (/[{}\[\]:,]/.test(ch)) { out.push(s('op', ch)); i++; continue }
    out.push(<span key={k++}>{ch}</span>); i++
  }
  return out
}

function tokenizeCode(code, lang) {
  const l = (lang || '').toLowerCase()
  if (l === 'json') return tokenizeJSON(code)
  const kw = KW[l] || KW.javascript
  const out = []; let i = 0; let k = 0
  const s = (cls, text) => <span key={k++} className={`tok-${cls}`}>{text}</span>

  while (i < code.length) {
    const ch = code[i]
    // Line comments
    if ((l === 'abap' && ch === '*' && (i === 0 || code[i - 1] === '\n')) ||
      (l === 'python' && ch === '#') ||
      (l === 'sql' && ch === '-' && code[i + 1] === '-') ||
      (l === 'javascript' && ch === '/' && code[i + 1] === '/')) {
      let j = code.indexOf('\n', i); if (j === -1) j = code.length
      out.push(s('comment', code.slice(i, j))); i = j; continue
    }
    // ABAP inline comment
    if (l === 'abap' && ch === '"') {
      let j = code.indexOf('\n', i); if (j === -1) j = code.length
      out.push(s('comment', code.slice(i, j))); i = j; continue
    }
    // Block comment /* */
    if (l === 'javascript' && ch === '/' && code[i + 1] === '*') {
      let j = code.indexOf('*/', i + 2); if (j === -1) j = code.length - 2
      out.push(s('comment', code.slice(i, j + 2))); i = j + 2; continue
    }
    // Strings
    if (ch === '"' || ch === "'") {
      const q = ch; let j = i + 1
      while (j < code.length && code[j] !== q) { if (code[j] === '\\') j++; j++ }
      out.push(s('string', code.slice(i, j + 1))); i = j + 1; continue
    }
    // Template literals
    if (l === 'javascript' && ch === '`') {
      let j = i + 1
      while (j < code.length && code[j] !== '`') { if (code[j] === '\\') j++; j++ }
      out.push(s('string', code.slice(i, j + 1))); i = j + 1; continue
    }
    // Numbers
    if (/[0-9]/.test(ch)) {
      let j = i + 1; while (j < code.length && /[0-9.eE_]/.test(code[j])) j++
      out.push(s('number', code.slice(i, j))); i = j; continue
    }
    // Identifiers / keywords
    if (/[a-zA-Z_$]/.test(ch)) {
      let j = i + 1; while (j < code.length && /[a-zA-Z0-9_$\-]/.test(code[j])) j++
      const word = code.slice(i, j)
      const isKw = kw.has(word) || kw.has(word.toUpperCase())
      out.push(isKw ? s('keyword', word) : <span key={k++}>{word}</span>)
      i = j; continue
    }
    // Operators
    if (/[{}[\]().,;:=<>!&|^~%@+\-*/]/.test(ch)) { out.push(s('op', ch)); i++; continue }
    out.push(<span key={k++}>{ch}</span>); i++
  }
  return out
}

// ─── Code Block ───────────────────────────────────────────────────────────────

function CodeBlock({ code, lang }) {
  const [copied, setCopied] = useState(false)
  const doCopy = () => {
    navigator.clipboard.writeText(code)
    setCopied(true); setTimeout(() => setCopied(false), 1800)
  }
  const tokens = tokenizeCode(code, lang)
  return (
    <div className="code-block">
      <div className="code-head">
        <span className="code-lang">{lang || 'text'}</span>
        <button className={`code-copy-btn ${copied ? 'copied' : ''}`} onClick={doCopy}>
          {copied ? 'Copied!' : 'Copy'}
        </button>
      </div>
      <pre className="code-content">{tokens}</pre>
    </div>
  )
}

// ─── Markdown Renderer ────────────────────────────────────────────────────────
// Parses a markdown string into React nodes — no external dependencies.

function parseInline(text, baseKey = 0) {
  const out = []; let i = 0; let k = baseKey
  while (i < text.length) {
    // Bold **
    if (text[i] === '*' && text[i + 1] === '*') {
      const end = text.indexOf('**', i + 2)
      if (end !== -1) { out.push(<strong key={k++}>{text.slice(i + 2, end)}</strong>); i = end + 2; continue }
    }
    // Italic *
    if (text[i] === '*') {
      const end = text.indexOf('*', i + 1)
      if (end !== -1) { out.push(<em key={k++}>{text.slice(i + 1, end)}</em>); i = end + 1; continue }
    }
    // Inline code `
    if (text[i] === '`') {
      const end = text.indexOf('`', i + 1)
      if (end !== -1) { out.push(<code key={k++} className="inline-code">{text.slice(i + 1, end)}</code>); i = end + 1; continue }
    }
    // Link [label](url)
    if (text[i] === '[') {
      const te = text.indexOf(']', i + 1)
      if (te !== -1 && text[te + 1] === '(') {
        const ue = text.indexOf(')', te + 2)
        if (ue !== -1) {
          out.push(<a key={k++} href={text.slice(te + 2, ue)} target="_blank" rel="noreferrer" className="md-link">{text.slice(i + 1, te)}</a>)
          i = ue + 1; continue
        }
      }
    }
    // Plain chars
    let next = text.slice(i).search(/[*`\[]/)
    if (next <= 0) { out.push(text[i]); i++ }
    else { out.push(text.slice(i, i + next)); i += next }
  }
  return out
}

function statusClass(val) {
  const s = String(val).toLowerCase()
  if (['ok', 'open', 'active', 'paid', 'delivered', 'success', 'released'].includes(s)) return 'st-success'
  if (['blocked', 'error', 'cancelled', 'failed', 'poor'].includes(s)) return 'st-error'
  if (['pending', 'partial', 'in_progress', 'in_transit', 'modifiable', 'needs_review'].includes(s)) return 'st-warning'
  return ''
}

function MarkdownRenderer({ content, className = '' }) {
  const blocks = []; const lines = content.split('\n'); let i = 0; let bk = 0
  while (i < lines.length) {
    const line = lines[i]
    // Fenced code block
    if (line.startsWith('```')) {
      const lang = line.slice(3).trim() || 'text'; const codeLines = []; i++
      while (i < lines.length && !lines[i].startsWith('```')) { codeLines.push(lines[i]); i++ }
      i++; blocks.push(<CodeBlock key={bk++} code={codeLines.join('\n')} lang={lang} />); continue
    }
    // Headings
    if (line.startsWith('### ')) { blocks.push(<h3 key={bk++} className="md-h3">{parseInline(line.slice(4))}</h3>); i++; continue }
    if (line.startsWith('## ')) { blocks.push(<h2 key={bk++} className="md-h2">{parseInline(line.slice(3))}</h2>); i++; continue }
    if (line.startsWith('# ')) { blocks.push(<h1 key={bk++} className="md-h1">{parseInline(line.slice(2))}</h1>); i++; continue }
    // HR
    if (/^[-*_]{3,}$/.test(line.trim())) { blocks.push(<hr key={bk++} className="md-hr" />); i++; continue }
    // Blockquote
    if (line.startsWith('> ')) {
      const ql = []; while (i < lines.length && lines[i].startsWith('> ')) { ql.push(lines[i].slice(2)); i++ }
      blocks.push(<blockquote key={bk++} className="md-blockquote">{parseInline(ql.join(' '))}</blockquote>); continue
    }
    // GFM Table
    if (line.includes('|') && i + 1 < lines.length && /^[\s|:-]+$/.test(lines[i + 1])) {
      const parseCells = (r) => r.split('|').filter((_, idx, a) => idx > 0 && idx < a.length - 1).map(c => c.trim())
      const headers = parseCells(line); i += 2; const rows = []
      while (i < lines.length && lines[i].includes('|')) { rows.push(parseCells(lines[i])); i++ }
      blocks.push(
        <div key={bk++} className="md-table-wrap">
          <table className="md-table">
            <thead><tr>{headers.map((h, ci) => <th key={ci} className="md-th">{parseInline(h)}</th>)}</tr></thead>
            <tbody>{rows.map((row, ri) => <tr key={ri}>{row.map((c, ci) => <td key={ci} className={`md-td ${statusClass(c)}`}>{parseInline(c)}</td>)}</tr>)}</tbody>
          </table>
        </div>
      ); continue
    }
    // Unordered list
    if (/^[-*+]\s/.test(line)) {
      const items = []; while (i < lines.length && /^[-*+]\s/.test(lines[i])) { items.push(lines[i].replace(/^[-*+]\s/, '')); i++ }
      blocks.push(<ul key={bk++} className="md-ul">{items.map((it, idx) => <li key={idx} className="md-li">{parseInline(it)}</li>)}</ul>); continue
    }
    // Ordered list
    if (/^\d+\.\s/.test(line)) {
      const items = []; while (i < lines.length && /^\d+\.\s/.test(lines[i])) { items.push(lines[i].replace(/^\d+\.\s/, '')); i++ }
      blocks.push(<ol key={bk++} className="md-ol">{items.map((it, idx) => <li key={idx} className="md-li">{parseInline(it)}</li>)}</ol>); continue
    }
    // Empty line
    if (line.trim() === '') { i++; continue }
    // Paragraph (greedy)
    const pl = []
    while (i < lines.length && lines[i].trim() !== '' && !lines[i].startsWith('```') && !lines[i].startsWith('#') && !lines[i].startsWith('> ') && !/^[-*+]\s/.test(lines[i]) && !/^\d+\.\s/.test(lines[i]) && !/^[-*_]{3,}$/.test(lines[i].trim()) && !lines[i].includes('|')) {
      pl.push(lines[i]); i++
    }
    if (pl.length) blocks.push(<p key={bk++} className="md-p">{pl.map((l2, pi) => <span key={pi}>{parseInline(l2)}{pi < pl.length - 1 && <br />}</span>)}</p>)
  }
  return <div className={`md-body ${className}`}>{blocks}</div>
}

// ─── Helper ────────────────────────────────────────────────────────────────────

function formatValue(val) {
  if (val === null || val === undefined) return '—'
  if (typeof val === 'boolean') return val ? 'Yes' : 'No'
  if (typeof val === 'object') return JSON.stringify(val)
  return String(val)
}

// ─── DataTable ───────────────────────────────────────────────────────────────
// Renders a paginated table from streamed rows. Works for both streaming
// (live updates) and finalised messages. No external dependencies.

const PAGE_SIZE = 50

function DataTable({ columns, rows, total, loading }) {
  const [page, setPage] = useState(0)
  const [search, setSearch] = useState('')
  const [sortCol, setSortCol] = useState(null)
  const [sortAsc, setSortAsc] = useState(true)

  const filtered = search
    ? rows.filter(r => Object.values(r).some(v => String(v ?? '').toLowerCase().includes(search.toLowerCase())))
    : rows

  const sorted = sortCol
    ? [...filtered].sort((a, b) => {
      const av = a[sortCol] ?? '', bv = b[sortCol] ?? ''
      return sortAsc ? String(av).localeCompare(String(bv), undefined, { numeric: true }) : String(bv).localeCompare(String(av), undefined, { numeric: true })
    })
    : filtered

  const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE))
  const pageRows = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)

  const handleSort = (col) => {
    if (sortCol === col) setSortAsc(a => !a)
    else { setSortCol(col); setSortAsc(true) }
    setPage(0)
  }

  const handleSearch = (e) => { setSearch(e.target.value); setPage(0) }

  if (!columns || columns.length === 0) return null

  return (
    <div className="dt-wrap">
      <div className="dt-toolbar">
        <span className="dt-count">
          {loading ? `Loading… ${rows.length} / ${total ?? '?'} rows` : `${sorted.length} of ${total ?? rows.length} records`}
          {search && ` — filtered`}
        </span>
        <input
          className="dt-search"
          placeholder="Search…"
          value={search}
          onChange={handleSearch}
        />
      </div>
      <div className="dt-scroll">
        <table className="dt-table">
          <thead>
            <tr>
              {columns.map(col => (
                <th key={col} className="dt-th" onClick={() => handleSort(col)}>
                  {col.replace(/_/g, ' ').toUpperCase()}
                  {sortCol === col ? (sortAsc ? ' ▲' : ' ▼') : ''}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pageRows.map((row, ri) => (
              <tr key={ri} className={ri % 2 === 0 ? 'dt-row-even' : 'dt-row-odd'}>
                {columns.map(col => (
                  <td key={col} className="dt-td">{formatValue(row[col])}</td>
                ))}
              </tr>
            ))}
            {pageRows.length === 0 && (
              <tr><td colSpan={columns.length} className="dt-empty">No matching records</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {totalPages > 1 && (
        <div className="dt-pagination">
          <button className="dt-page-btn" onClick={() => setPage(0)} disabled={page === 0}>«</button>
          <button className="dt-page-btn" onClick={() => setPage(p => p - 1)} disabled={page === 0}>‹</button>
          <span className="dt-page-info">Page {page + 1} / {totalPages}</span>
          <button className="dt-page-btn" onClick={() => setPage(p => p + 1)} disabled={page >= totalPages - 1}>›</button>
          <button className="dt-page-btn" onClick={() => setPage(totalPages - 1)} disabled={page >= totalPages - 1}>»</button>
        </div>
      )}
    </div>
  )
}

// ─── SapSourceBadge ──────────────────────────────────────────────────────────

function SapSourceBadge({ source }) {
  if (!source) return null
  return (
    <div className="sap-src">
      <Icons.terminal />
      <span>Verify in SAP:</span>
      <strong>{source.tcode}</strong>
      {source.bapi && source.bapi !== 'N/A' && <><span className="sap-src-sep">·</span><span>BAPI: {source.bapi}</span></>}
      {source.table && source.table !== 'N/A' && <><span className="sap-src-sep">·</span><span>Table: {source.table}</span></>}
    </div>
  )
}

// ─── ToolResult ───────────────────────────────────────────────────────────────

function ToolResult({ result }) {
  if (!result || typeof result !== 'object') return null
  const display = Object.fromEntries(Object.entries(result).filter(([k]) => !['sap_source', 'status'].includes(k)))
  const isArr = Array.isArray(display)
  const isArrOfObj = isArr && display.length > 0 && typeof display[0] === 'object'

  if (isArrOfObj) {
    const keys = Object.keys(display[0])
    return (
      <div className="tool-card">
        <div className="tool-card-head"><Icons.terminal /> Result — {display.length} records</div>
        <div className="tool-card-body">
          <table className="result-tbl">
            <thead><tr>{keys.map(k => <th key={k}>{k.replace(/_/g, ' ').toUpperCase()}</th>)}</tr></thead>
            <tbody>{display.map((row, i) => <tr key={i}>{keys.map(k => <td key={k} className={statusClass(row[k])}>{formatValue(row[k])}</td>)}</tr>)}</tbody>
          </table>
        </div>
      </div>
    )
  }
  const entries = Object.entries(display).filter(([, v]) => typeof v !== 'object' || v === null)
  const nested = Object.entries(display).filter(([, v]) => typeof v === 'object' && v !== null)
  return (
    <div className="tool-card">
      <div className="tool-card-head"><Icons.terminal /> Tool Data</div>
      <div className="tool-card-body">
        {entries.length > 0 && (
          <div className="kv-grid" style={{ marginBottom: nested.length ? 10 : 0 }}>
            {entries.map(([k, v]) => (
              <span key={k} style={{ display: 'contents' }}>
                <span className="kv-key">{k.replace(/_/g, ' ')}:</span>
                <span className={`kv-val ${statusClass(v)}`}>{formatValue(v)}</span>
              </span>
            ))}
          </div>
        )}
        {nested.map(([k, v]) => (
          <div key={k} style={{ marginTop: 8 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 4 }}>{k.replace(/_/g, ' ')}</div>
            {Array.isArray(v) ? (
              <div style={{ fontSize: 12 }}>{v.join(', ')}</div>
            ) : (
              <div className="kv-grid">
                {Object.entries(v || {}).map(([kk, vv]) => (
                  <span key={kk} style={{ display: 'contents' }}>
                    <span className="kv-key">{kk.replace(/_/g, ' ')}:</span>
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

// ─── AnomalyPanel ────────────────────────────────────────────────────────────

function AnomalyPanel({ anomalies }) {
  if (!anomalies?.length) return null
  const sevColor = { HIGH: '#dc2626', MEDIUM: '#d97706', LOW: '#ca8a04' }
  return (
    <div className="anomaly-panel">
      <div className="anomaly-head">Anomalies & Alerts ({anomalies.length})</div>
      {anomalies.map((a, i) => (
        <div key={i} className="anomaly-item" style={{ background: a.severity === 'HIGH' ? '#fef2f2' : a.severity === 'MEDIUM' ? '#fffbeb' : '#fefce8' }}>
          <Icons.alert />
          <span className="anomaly-sev" style={{ color: sevColor[a.severity] }}>{a.severity}</span>
          <span style={{ fontSize: 12, color: 'var(--text-primary)' }}>{a.message}</span>
        </div>
      ))}
    </div>
  )
}

// ─── ResearchReport ──────────────────────────────────────────────────────────

function ResearchReport({ result }) {
  const [open, setOpen] = useState(true)
  if (!result?.formatted_report) return null
  return (
    <div className="research-card">
      <div className="research-head" onClick={() => setOpen(o => !o)}>
        <span>Research Report</span>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {result.entity_id && <span className="entity-badge">{result.entity_id}</span>}
          {result.tools_run?.length > 0 && <span className="tools-badge">{result.tools_run.length} tools</span>}
          {open ? <Icons.chevUp /> : <Icons.chevDown />}
        </div>
      </div>
      {open && (
        <div className="research-body">
          <AnomalyPanel anomalies={result.anomalies} />
          <MarkdownRenderer content={result.formatted_report} className="" />
          {result.sources_used?.length > 0 && (
            <div className="research-sources">
              <span>SAP Sources:</span>
              {result.sources_used.map((s, i) => <span key={i} className="src-chip">{s}</span>)}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── MessageRow ───────────────────────────────────────────────────────────────

function MessageRow({ msg }) {
  const isUser = msg.role === 'user'
  return (
    <div className={`msg-row ${isUser ? 'user' : 'bot'}`}>
      <div className={`msg-avatar ${isUser ? 'user-av' : 'bot-av'}`}>
        {isUser ? (msg.userInitial || 'U') : msg.research_mode ? <Icons.beaker /> : 'AI'}
      </div>
      <div className="msg-body">
        {msg.status_steps?.length > 0 && (
          <details className="stream-steps-collapsed">
            <summary>Reasoning steps ({msg.status_steps.length})</summary>
            {msg.status_steps.map((s, i) => <div key={i} className="stream-step done"><span className="step-dot" />{s}</div>)}
          </details>
        )}
        {msg.research_mode ? (
          <ResearchReport result={msg.research_result} />
        ) : isUser ? (
          <div className="msg-bubble">{msg.content}</div>
        ) : (
          <div className="msg-bubble md-bubble">
            <MarkdownRenderer content={msg.content} />
          </div>
        )}
        <div className="msg-meta">
          {msg.research_mode && <span className="badge badge-research">AUTO RESEARCH</span>}
        </div>
        {!msg.research_mode && msg.sap_source && <SapSourceBadge source={msg.sap_source} />}
        {msg.tableData && (
          <DataTable
            columns={msg.tableData.columns}
            rows={msg.tableData.rows}
            total={msg.tableData.total}
            loading={false}
          />
        )}
        {msg.report && <ReportWidget report={msg.report} />}
        {msg.abap_check && <AbapReviewWidget abap_check={msg.abap_check} />}
        {msg.abap_code && <AbapCodeWidget abap_code={msg.abap_code} />}
        {msg.tool_result && (msg.tool_result.outstanding_items || msg.tool_result.park_reference) && (
          <ReceiptWidget initialData={msg.tool_result.outstanding_items ? msg.tool_result : null} />
        )}
      </div>
    </div>
  )
}

// ─── TypingIndicator ──────────────────────────────────────────────────────────

function TypingIndicator() {
  return (
    <div className="typing-row">
      <div className="msg-avatar bot-av">AI</div>
      <div className="typing-bubble">
        <div className="typing-dot" /><div className="typing-dot" /><div className="typing-dot" />
      </div>
    </div>
  )
}

// ─── StreamingMessageRow ─────────────────────────────────────────────────────

function StreamingMessageRow({ msg }) {
  return (
    <div className="msg-row bot">
      <div className="msg-avatar bot-av">AI</div>
      <div className="msg-body">
        {msg.status_steps.length > 0 && (
          <div className="stream-steps">
            {msg.status_steps.map((step, i) => (
              <div key={i} className={`stream-step ${i === msg.status_steps.length - 1 ? 'active' : 'done'}`}>
                <span className="step-dot" />{step}
              </div>
            ))}
          </div>
        )}
        {msg.content ? (
          <div className="msg-bubble" style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
            {msg.content}
          </div>
        ) : (
          <div className="stream-thinking">
            <div className="typing-dot" /><div className="typing-dot" /><div className="typing-dot" />
          </div>
        )}
        {msg.tableData && (
          <DataTable
            columns={msg.tableData.columns}
            rows={msg.tableData.rows}
            total={msg.tableData.total}
            loading={msg.tableData.loading}
          />
        )}
      </div>
    </div>
  )
}

// ─── DevWarningBanner ────────────────────────────────────────────────────────

function DevWarningBanner() {
  const [vis, setVis] = useState(true)
  if (!vis) return null
  return (
    <div className="dev-warning">
      <span><Icons.alert /> Dev mode: JWT secret is insecure. Set <code>JWT_SECRET_KEY</code> before deploying to production.</span>
      <button onClick={() => setVis(false)}><Icons.x /></button>
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
  const [auditLogs, setAuditLogs] = useState([])
  const [auditLoading, setAuditLoading] = useState(false)
  const [users, setUsers] = useState([])
  const [usersLoading, setUsersLoading] = useState(false)
  const [newUser, setNewUser] = useState({ user_id: '', password: '', full_name: '', email: '', roles: ['read_only'] })
  const [createStatus, setCreateStatus] = useState(null)
  const [setupData, setSetupData] = useState(null)   // {user_id, mcp_key, claude_desktop_config}
  const [setupLoading, setSetupLoading] = useState(null)   // user_id being fetched
  const [mySetup, setMySetup] = useState(null)
  const [mySetupLoading, setMySetupLoading] = useState(false)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    apiFetch('/config').then(r => r.json()).then(d => setCfg(d)).catch(() => { })
    apiFetch('/config/mcp-servers').then(r => r.json()).then(d => setMcpServers(d.servers || [])).catch(() => { })
  }, [])
  useEffect(() => {
    if (tab === 'audit' && isAdmin) {
      setAuditLoading(true)
      apiFetch('/audit/logs?limit=50').then(r => r.json()).then(d => setAuditLogs(d.logs || [])).catch(() => { }).finally(() => setAuditLoading(false))
    }
    if (tab === 'users' && isAdmin) {
      setUsersLoading(true)
      apiFetch('/auth/users').then(r => r.json()).then(d => setUsers(d.users || [])).catch(() => { }).finally(() => setUsersLoading(false))
    }
  }, [tab, isAdmin])

  const setSap = (k, v) => setCfg(c => ({ ...c, sap: { ...c.sap, [k]: v } }))
  const setMcp = (k, v) => setCfg(c => ({ ...c, mcp: { ...c.mcp, [k]: v } }))
  const setOllama = (k, v) => setCfg(c => ({ ...c, ollama: { ...c.ollama, [k]: v } }))

  const handleSave = async () => {
    setSaving(true); setSaveStatus(null)
    try { const r = await apiFetch('/config', { method: 'POST', body: JSON.stringify(cfg) }); setSaveStatus(r.ok ? 'ok' : 'err') }
    catch { setSaveStatus('err') }
    finally { setSaving(false); setTimeout(() => setSaveStatus(null), 3000) }
  }
  const handleTestSap = async () => {
    setTesting(true); setTestResult(null)
    try { setTestResult(await (await apiFetch('/config/test-sap', { method: 'POST' })).json()) }
    catch { setTestResult({ success: false, message: 'Cannot reach API server' }) }
    finally { setTesting(false) }
  }
  const handleAddMcp = async () => {
    if (!newServer.name || !newServer.url) return
    await apiFetch('/config/mcp-servers', { method: 'POST', body: JSON.stringify(newServer) })
    const d = await (await apiFetch('/config/mcp-servers')).json()
    setMcpServers(d.servers || []); setNewServer({ name: '', url: '', transport: 'sse', enabled: true })
  }
  const handleRemoveMcp = async (name) => {
    await apiFetch(`/config/mcp-servers/${encodeURIComponent(name)}`, { method: 'DELETE' })
    setMcpServers(s => s.filter(x => x.name !== name))
  }
  const handleTestMcp = async () => {
    if (!newServer.url) return
    setMcpTesting(true); setMcpTestResult(null)
    try { setMcpTestResult(await (await apiFetch('/config/test-mcp', { method: 'POST', body: JSON.stringify(newServer) })).json()) }
    catch { setMcpTestResult({ success: false, message: 'Cannot reach API server' }) }
    finally { setMcpTesting(false) }
  }
  const handleCreateUser = async () => {
    setCreateStatus(null)
    try {
      const res = await apiFetch('/auth/users', { method: 'POST', body: JSON.stringify(newUser) })
      const d = await res.json()
      if (!res.ok) { setCreateStatus({ ok: false, msg: d.detail }); return }
      setUsers(p => [...p, d.user])
      // Auto-show the Claude Desktop setup so admin can hand it to the user immediately
      if (d.mcp_key) {
        const serverUrl = window.location.origin
        setSetupData({
          user_id: d.user.user_id,
          mcp_key: d.mcp_key,
          claude_desktop_config: {
            mcpServers: {
              'sap-ai-agent': {
                url: `${serverUrl}/mcp/sse`,
                headers: { 'X-MCP-Key': d.mcp_key }
              }
            }
          }
        })
      }
      setNewUser({ user_id: '', password: '', full_name: '', email: '', roles: ['read_only'] })
      setCreateStatus({ ok: true, msg: `User '${d.user.user_id}' created — setup shown below` })
    } catch { setCreateStatus({ ok: false, msg: 'Request failed' }) }
    setTimeout(() => setCreateStatus(null), 4000)
  }

  const handleGetSetup = async (uid) => {
    setSetupLoading(uid)
    try {
      const d = await (await apiFetch(`/auth/users/${uid}/mcp-setup`)).json()
      setSetupData(d)
    } catch { /* ignore */ }
    finally { setSetupLoading(null) }
  }

  const handleGetMySetup = async () => {
    setMySetupLoading(true)
    try {
      const d = await (await apiFetch('/mcp/my-setup')).json()
      setMySetup(d)
    } catch { /* ignore */ }
    finally { setMySetupLoading(false) }
  }

  const handleCopy = (text) => {
    navigator.clipboard.writeText(text).then(() => { setCopied(true); setTimeout(() => setCopied(false), 2000) })
  }
  const handleDeactivate = async (uid) => {
    await apiFetch(`/auth/users/${uid}/deactivate`, { method: 'PATCH' })
    setUsers(p => p.map(u => u.user_id === uid ? { ...u, active: false } : u))
  }

  if (!cfg) return (
    <div className="modal-overlay">
      <div className="modal" style={{ alignItems: 'center', justifyContent: 'center', minHeight: 200 }}>
        <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>Loading configuration…</p>
      </div>
    </div>
  )

  const connType = cfg.sap?.connection_type || 'mock'
  const authType = cfg.sap?.auth_type || 'basic'
  const tabs = [
    { id: 'sap', label: 'SAP Connection' },
    { id: 'mcp', label: 'MCP Servers' },
    { id: 'ollama', label: 'LLM / Ollama' },
    { id: 'claude', label: 'Claude Desktop' },
    ...(isAdmin ? [{ id: 'users', label: 'Users & Roles' }, { id: 'audit', label: 'Audit Logs' }] : []),
  ]

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-head">
          <span className="modal-title">Configuration</span>
          <button className="modal-close" onClick={onClose}><Icons.x /></button>
        </div>

        <div className="modal-tabs">
          {tabs.map(t => <button key={t.id} className={`modal-tab ${tab === t.id ? 'active' : ''}`} onClick={() => setTab(t.id)}>{t.label}</button>)}
        </div>

        <div className="modal-body">

          {/* SAP Connection */}
          {tab === 'sap' && <>
            <div>
              <div className="form-section">Connection Type</div>
              <div className="conn-group">
                {[{ v: 'mock', icon: '🎭', label: 'Mock / Demo', sub: 'Simulated data — no SAP needed' },
                { v: 'cloud', icon: '☁️', label: 'SAP Cloud', sub: 'BTP, S/4HANA Cloud, Rise' },
                { v: 'on_premise', icon: '🏢', label: 'On-Premise', sub: 'SAP ECC, S/4HANA On-Prem' }]
                  .map(o => (
                    <button key={o.v} className={`conn-btn ${connType === o.v ? 'active' : ''}`} onClick={() => setSap('connection_type', o.v)}>
                      <div className="conn-icon">{o.icon}</div>
                      <div className="conn-label">{o.label}</div>
                      <div className="conn-sub">{o.sub}</div>
                    </button>
                  ))}
              </div>
            </div>
            {connType === 'mock' && (
              <div className="result-banner info">🎭 Mock mode active — all 30 tools use built-in simulated SAP data.</div>
            )}
            {connType !== 'mock' && <>
              <div className="form-section">System Details</div>
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
              {authType === 'oauth2' && <>
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
              </>}
              {authType === 'x509' && (
                <div className="form-group">
                  <label className="form-label">Certificate Path</label>
                  <input className="form-input mono" value={cfg.sap.x509_cert_path || ''} onChange={e => setSap('x509_cert_path', e.target.value)} placeholder="/path/to/client.pem" />
                </div>
              )}
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <button className="btn btn-secondary" onClick={handleTestSap} disabled={testing}>{testing ? 'Testing…' : 'Test Connection'}</button>
                {testResult && <div className={`result-banner ${testResult.success ? 'success' : 'error'}`}>{testResult.message}</div>}
              </div>
            </>}
          </>}

          {/* MCP Servers */}
          {tab === 'mcp' && <>
            <div>
              <div className="form-section">Built-in MCP Server</div>
              <div style={{ marginTop: 12, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600 }}>SAP Tools — stdio transport</div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>30 tools (FI/CO, MM, SD, HR, PP, ABAP) via <code style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>python mcp_server.py</code></div>
                </div>
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13 }}>
                  <input type="checkbox" checked={cfg.mcp?.builtin_enabled ?? true} onChange={e => setMcp('builtin_enabled', e.target.checked)} />
                  Enabled
                </label>
              </div>
            </div>
            <div>
              <div className="form-section">Custom MCP Servers</div>
              <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
                {mcpServers.filter(s => s.type === 'custom').length === 0 && <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>No custom servers configured.</p>}
                {mcpServers.filter(s => s.type === 'custom').map(s => (
                  <div className="mcp-item" key={s.name}>
                    <div>
                      <div className="mcp-name">{s.name}</div>
                      <div className="mcp-url">{s.url}</div>
                      <div style={{ display: 'flex', gap: 4, marginTop: 4 }}>
                        <span className="mcp-chip custom">{s.transport}</span>
                        <span className={`mcp-chip ${s.enabled ? 'enabled' : 'disabled'}`}>{s.enabled ? 'enabled' : 'disabled'}</span>
                      </div>
                    </div>
                    <button className="btn btn-danger" onClick={() => handleRemoveMcp(s.name)}>Remove</button>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <div className="form-section">Add New MCP Server</div>
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
                      <option value="stdio">stdio (local)</option>
                    </select>
                  </div>
                </div>
                <div className="form-group">
                  <label className="form-label">Server URL *</label>
                  <input className="form-input mono" value={newServer.url} onChange={e => setNewServer(s => ({ ...s, url: e.target.value }))} placeholder="http://localhost:8001/sse" />
                </div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <button className="btn btn-primary" onClick={handleAddMcp} disabled={!newServer.name || !newServer.url}>Add Server</button>
                  <button className="btn btn-secondary" onClick={handleTestMcp} disabled={!newServer.url || mcpTesting}>{mcpTesting ? 'Testing…' : 'Test'}</button>
                  {mcpTestResult && <div className={`result-banner ${mcpTestResult.success ? 'success' : 'error'}`}>{mcpTestResult.message}</div>}
                </div>
              </div>
            </div>
          </>}

          {/* Ollama / LLM */}
          {tab === 'ollama' && <>
            <div className="form-group">
              <label className="form-label">Ollama Server URL</label>
              <input className="form-input mono" value={cfg.ollama?.url || ''} onChange={e => setOllama('url', e.target.value)} placeholder="http://localhost:11434" />
              <span className="form-hint">Bind Ollama to <code style={{ fontFamily: 'var(--font-mono)' }}>127.0.0.1</code> only — never expose publicly.</span>
            </div>
            <div className="form-group">
              <label className="form-label">Default Model</label>
              <select className="form-select" value={cfg.ollama?.default_model || 'llama3.2'} onChange={e => setOllama('default_model', e.target.value)}>
                {MODELS.map(m => <option key={m} value={m}>{m}</option>)}
              </select>
              <span className="form-hint">Pull before use: <code style={{ fontFamily: 'var(--font-mono)' }}>ollama pull llama3.2</code></span>
            </div>
            <div style={{ padding: '14px', background: 'var(--bg-subtle)', borderRadius: 'var(--r-lg)', fontSize: 12, border: '1px solid var(--border)' }}>
              <div style={{ fontWeight: 700, marginBottom: 8, fontSize: 12.5 }}>Accuracy by module (llama3.2:8b)</div>
              <div className="accuracy-grid">
                <span>FI/CO: <b style={{ color: 'var(--success)' }}>88%</b></span>
                <span>MM: <b style={{ color: 'var(--success)' }}>85%</b></span>
                <span>SD: <b style={{ color: 'var(--success)' }}>87%</b></span>
                <span>HR: <b style={{ color: 'var(--warning)' }}>84%</b></span>
                <span>PP: <b style={{ color: 'var(--warning)' }}>82%</b></span>
                <span>ABAP: <b style={{ color: 'var(--warning)' }}>80%</b></span>
              </div>
              <div style={{ marginTop: 8, color: 'var(--text-muted)' }}>Full benchmarks: <code style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>docs/BENCHMARKS.md</code></div>
            </div>
          </>}

          {/* Users & Roles (admin) */}
          {tab === 'users' && isAdmin && <>
            <div>
              <div className="form-section">User Accounts</div>
              {usersLoading ? <p style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 12 }}>Loading users…</p> : (
                <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {users.map(u => (
                    <div key={u.user_id} className="user-row">
                      <div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <span style={{ fontWeight: 600, fontSize: 13 }}>{u.user_id}</span>
                          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{u.full_name}</span>
                          {!u.active && <span className="badge-role" style={{ background: 'var(--error-bg)', color: 'var(--error)' }}>inactive</span>}
                        </div>
                        <div style={{ display: 'flex', gap: 4, marginTop: 4, flexWrap: 'wrap' }}>
                          {(u.roles || []).map(r => (
                            <span key={r} className="badge-role" style={{ background: (ROLE_COLORS[r] || '#888') + '22', color: ROLE_COLORS[r] || '#888' }}>{ROLE_LABELS[r] || r}</span>
                          ))}
                        </div>
                      </div>
                      <div style={{ display: 'flex', gap: 6 }}>
                        {u.active && (
                          <button
                            className="btn btn-secondary"
                            style={{ fontSize: 11, padding: '4px 10px' }}
                            onClick={() => handleGetSetup(u.user_id)}
                            disabled={setupLoading === u.user_id}
                            title="Generate Claude Desktop config for this user"
                          >
                            {setupLoading === u.user_id ? '…' : '⚙ Setup'}
                          </button>
                        )}
                        {u.active && u.user_id !== currentUser?.user_id && (
                          <button className="btn btn-danger" style={{ fontSize: 11, padding: '4px 10px' }} onClick={() => handleDeactivate(u.user_id)}>Deactivate</button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div>
              <div className="form-section">Create User</div>
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
                    {ALL_ROLES.map(r => <option key={r} value={r}>{ROLE_LABELS[r] || r}</option>)}
                  </select>
                  <span className="form-hint">Roles control SAP module access. HR salary data restricted to hr_manager only.</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <button className="btn btn-primary" onClick={handleCreateUser} disabled={!newUser.user_id || !newUser.password}>Create User</button>
                  {createStatus && <span className={`save-status ${createStatus.ok ? 'ok' : 'err'}`}>{createStatus.ok ? '✓' : '✗'} {createStatus.msg}</span>}
                </div>
              </div>
            </div>
          </>}

          {/* Setup card — shown after user creation or clicking ⚙ Setup */}
          {tab === 'users' && isAdmin && setupData && (() => {
            const cfgText = JSON.stringify(setupData.claude_desktop_config, null, 2)
            return (
              <div style={{ border: '1px solid var(--success)', borderRadius: 8, padding: '14px 16px', background: 'var(--success-bg, #0f2e1a)', marginTop: 8 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                  <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--success)' }}>
                    Claude Desktop Setup — {setupData.user_id}
                  </div>
                  <button className="btn btn-secondary" style={{ fontSize: 11, padding: '3px 8px' }} onClick={() => setSetupData(null)}>✕ Dismiss</button>
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
                  Send this config to <b>{setupData.user_id}</b>. They paste it into{' '}
                  <code style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>~/Library/Application Support/Claude/claude_desktop_config.json</code>{' '}
                  and restart Claude Desktop. That's it — no passwords, no Python, no local install.
                </div>
                <pre style={{ fontFamily: 'var(--font-mono)', fontSize: 11, background: 'var(--bg-input, #111)', borderRadius: 6, padding: '10px 12px', overflowX: 'auto', margin: 0, color: 'var(--text-primary)' }}>{cfgText}</pre>
                <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                  <button className="btn btn-primary" style={{ fontSize: 12 }} onClick={() => handleCopy(cfgText)}>
                    {copied ? '✓ Copied!' : 'Copy Config'}
                  </button>
                  <button className="btn btn-secondary" style={{ fontSize: 12 }} onClick={() => {
                    const blob = new Blob([cfgText], { type: 'application/json' })
                    const a = document.createElement('a'); a.href = URL.createObjectURL(blob)
                    a.download = 'claude_desktop_config.json'; a.click()
                  }}>Download JSON</button>
                </div>
                <div style={{ marginTop: 10, fontSize: 11, color: 'var(--warning, #f0a)' }}>
                  This key is shown once. Clicking ⚙ Setup again will regenerate it and invalidate this one.
                </div>
              </div>
            )
          })()}

          {/* Claude Desktop — self-service tab */}
          {tab === 'claude' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div className="form-section">Connect Claude Desktop</div>
              <div style={{ fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.6 }}>
                Generate your personal MCP config. Paste it into Claude Desktop and all SAP tools become available instantly —
                no database credentials, no local Python setup required.
              </div>
              {!mySetup ? (
                <button className="btn btn-primary" onClick={handleGetMySetup} disabled={mySetupLoading} style={{ alignSelf: 'flex-start' }}>
                  {mySetupLoading ? 'Generating…' : 'Generate My Setup Config'}
                </button>
              ) : (() => {
                const cfgText = JSON.stringify(mySetup.claude_desktop_config, null, 2)
                return (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    <pre style={{ fontFamily: 'var(--font-mono)', fontSize: 11, background: 'var(--bg-input, #111)', borderRadius: 6, padding: '12px 14px', overflowX: 'auto', margin: 0, color: 'var(--text-primary)' }}>{cfgText}</pre>
                    <div style={{ display: 'flex', gap: 8 }}>
                      <button className="btn btn-primary" style={{ fontSize: 12 }} onClick={() => handleCopy(cfgText)}>
                        {copied ? '✓ Copied!' : 'Copy Config'}
                      </button>
                      <button className="btn btn-secondary" style={{ fontSize: 12 }} onClick={() => {
                        const blob = new Blob([cfgText], { type: 'application/json' })
                        const a = document.createElement('a'); a.href = URL.createObjectURL(blob)
                        a.download = 'claude_desktop_config.json'; a.click()
                      }}>Download JSON</button>
                      <button className="btn btn-secondary" style={{ fontSize: 12 }} onClick={() => { setMySetup(null) }}>Regenerate</button>
                    </div>
                    <ol style={{ fontSize: 12, color: 'var(--text-muted)', paddingLeft: 18, margin: 0, lineHeight: 2 }}>
                      {(mySetup.instructions || []).map((s, i) => <li key={i}>{s}</li>)}
                    </ol>
                    <div style={{ fontSize: 11, color: 'var(--warning, #f90)', marginTop: 4 }}>
                      This key is shown once. Click Regenerate to get a new one (invalidates the old key).
                    </div>
                  </div>
                )
              })()}
            </div>
          )}

          {/* Audit Logs (admin) */}
          {tab === 'audit' && isAdmin && <>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div className="form-section">Recent Audit Log (SOX / GDPR)</div>
              <button className="btn btn-secondary" style={{ fontSize: 12, padding: '5px 10px', gap: 5 }}
                onClick={() => { setAuditLoading(true); apiFetch('/audit/logs?limit=50').then(r => r.json()).then(d => setAuditLogs(d.logs || [])).finally(() => setAuditLoading(false)) }}>
                <Icons.refresh /> Refresh
              </button>
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: -14 }}>Written to <code style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>logs/audit_YYYY-MM-DD.jsonl</code> · Retain 7 years for SOX compliance</div>
            {auditLoading ? <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>Loading…</p>
              : auditLogs.length === 0 ? <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>No records yet. Records appear after the first /chat call.</p>
                : (
                  <div style={{ overflowX: 'auto' }}>
                    <table className="result-tbl audit-tbl">
                      <thead><tr><th>Time</th><th>User</th><th>Role</th><th>Tool</th><th>Query</th><th>ms</th></tr></thead>
                      <tbody>
                        {auditLogs.map((log, i) => (
                          <tr key={i}>
                            <td style={{ whiteSpace: 'nowrap', fontFamily: 'var(--font-mono)', fontSize: 11 }}>{new Date(log.timestamp).toLocaleTimeString()}</td>
                            <td style={{ fontWeight: 600 }}>{log.user_id}</td>
                            <td>{(log.user_roles || []).join(', ')}</td>
                            <td style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>{log.tool_called || '—'}</td>
                            <td style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={log.query}>{log.query}</td>
                            <td>{log.duration_ms}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
          </>}
        </div>

        <div className="modal-foot">
          <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            {saveStatus === 'ok' && <span className="save-status ok"><Icons.check /> Saved</span>}
            {saveStatus === 'err' && <span className="save-status err"><Icons.alert /> Save failed</span>}
            {['sap', 'mcp', 'ollama'].includes(tab) && (
              <button className="btn btn-primary" onClick={handleSave} disabled={saving || !isAdmin}>
                {saving ? 'Saving…' : isAdmin ? 'Save Configuration' : 'Admin only'}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── LoginScreen ──────────────────────────────────────────────────────────────

function LoginScreen({ onLogin }) {
  const [userId, setUserId] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault(); setLoading(true); setError('')
    try {
      const res = await fetch(`${API}/auth/login`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user_id: userId, password }) })
      const data = await res.json()
      if (!res.ok) { setError(data.detail || 'Invalid credentials'); return }
      onLogin(data)
    } catch { setError('Cannot connect to server. Is the API running on port 8000?') }
    finally { setLoading(false) }
  }

  return (
    <div className="login-screen">
      <div className="login-card">
        <div className="login-logo-wrap"><div className="login-logo">SAP</div></div>
        <h2 className="login-title">SAP AI Agent</h2>
        <p className="login-subtitle">Natural Language ERP Interface</p>
        <form onSubmit={handleSubmit} className="login-form">
          <div className="form-group">
            <label className="form-label">User ID</label>
            <input className="form-input" value={userId} onChange={e => setUserId(e.target.value)} placeholder="admin" autoFocus autoComplete="username" />
          </div>
          <div className="form-group">
            <label className="form-label">Password</label>
            <input className="form-input" type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="••••••••" autoComplete="current-password" />
          </div>
          {error && <div className="login-error">{error}</div>}
          <button className="btn btn-primary login-btn" type="submit" disabled={!userId || !password || loading}>
            {loading ? 'Signing in…' : 'Sign In'}
          </button>
        </form>
        <div className="login-demo">
          <span>Demo:</span>
          <code>admin / SapAdmin@2026!</code>
          <code>fi_user / Finance@123</code>
          <code>hr_user / HR@123</code>
          <code>demo / demo</code>
        </div>
      </div>
    </div>
  )
}

// ─── Sidebar ──────────────────────────────────────────────────────────────────

function _relativeDate(iso) {
  if (!iso) return ''
  const d = new Date(iso), now = new Date()
  const diff = Math.floor((now - d) / 1000)
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`
  return d.toLocaleDateString()
}

function Sidebar({ activeModule, onModuleClick, onReset, sapMode, allowedModules,
  conversations, sessionId, onNewChat, onLoadConversation, onDeleteConversation }) {
  const visible = MODULES.filter(m => m.id === 'all' || allowedModules === null || allowedModules.includes(m.moduleKey))
  const modeLabel = { mock: '🎭 Mock mode', cloud: '☁️ SAP Cloud', on_premise: '🏢 On-Premise' }[sapMode] || sapMode
  return (
    <div className="sidebar">
      <div className="sidebar-section-label">SAP Modules</div>
      <nav className="sidebar-nav">
        {visible.map(mod => (
          <button key={mod.id} className={`mod-btn ${activeModule === mod.id ? 'active' : ''}`} onClick={() => onModuleClick(mod.id)}>
            <span className="mod-icon"><ModuleIcon iconId={mod.iconId} color={mod.color} size={14} /></span>
            <span className="mod-label">
              <span className="mod-name">{mod.name}</span>
              <span className="mod-desc">{mod.desc}</span>
            </span>
          </button>
        ))}
      </nav>

      {conversations.length > 0 && (
        <>
          <div className="sidebar-section-label">Chat History</div>
          <div className="history-list">
            {conversations.map(c => (
              <div key={c.session_id}
                className={`history-item ${c.session_id === sessionId ? 'active' : ''}`}
                onClick={() => onLoadConversation(c.session_id)}>
                <div className="history-item-body">
                  <span className="history-item-title">{c.title || 'Untitled'}</span>
                  <span className="history-item-date">{_relativeDate(c.updated_at)}</span>
                </div>
                <button className="history-del-btn" title="Delete"
                  onClick={e => { e.stopPropagation(); onDeleteConversation(c.session_id) }}>
                  <Icons.trash />
                </button>
              </div>
            ))}
          </div>
        </>
      )}

      <div className="sidebar-footer">
        <button className="new-chat-btn" onClick={onNewChat}>+ New Chat</button>
        <div className="sidebar-mode-label">{modeLabel}</div>
        <button className="clear-btn" onClick={onReset}>
          <Icons.trash /> Clear Conversation
        </button>
      </div>
    </div>
  )
}

// ─── Main App ─────────────────────────────────────────────────────────────────

// Reconstruct tableData from tool_result for history messages
function _extractTableData(toolResult) {
  if (!toolResult || typeof toolResult !== 'object') return null
  for (const val of Object.values(toolResult)) {
    if (Array.isArray(val) && val.length > 0 && val[0] && typeof val[0] === 'object') {
      return { columns: Object.keys(val[0]), rows: val, total: val.length }
    }
  }
  return null
}

function _makeSessionId(userId) {
  return `${userId}-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
}

function _getOrCreateSessionId(userId) {
  const key = `sap_session_${userId}`
  let sid = localStorage.getItem(key)
  if (!sid) { sid = _makeSessionId(userId); localStorage.setItem(key, sid) }
  return sid
}

export default function App() {
  const [messages, setMessages] = useState([])
  const [streamingMsg, setStreamingMsg] = useState(null)
  // Ref tracks streaming content synchronously to avoid stale closure in done handler
  const streamingRef = useRef({ content: '', status_steps: [] })
  const rafRef = useRef(null)
  // Ref tracks streaming table data — updated without re-renders, flushed via RAF
  const tableRef = useRef(null)
  const tableRafRef = useRef(null)
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [model, setModel] = useState('llama3.2')
  const [activeModule, setActiveModule] = useState('all')
  const [ollamaStatus, setOllamaStatus] = useState('checking')
  const [sapMode, setSapMode] = useState('mock')
  const [showSettings, setShowSettings] = useState(false)
  const [researchMode, setResearchMode] = useState(false)

  const [authToken, setAuthToken] = useState(() => localStorage.getItem('sap_agent_token'))
  const [currentUser, setCurrentUser] = useState(() => {
    try { return JSON.parse(localStorage.getItem('sap_agent_user') || 'null') } catch { return null }
  })
  const [authEnabled, setAuthEnabled] = useState(true)
  const [devSecretWarn, setDevSecretWarn] = useState(false)
  const [allowedModules, setAllowedModules] = useState(null)

  // ── Chat history ────────────────────────────────────────────────────────────
  const [sessionId, setSessionId] = useState(() => {
    try {
      const u = JSON.parse(localStorage.getItem('sap_agent_user') || 'null')
      return u?.user_id ? _getOrCreateSessionId(u.user_id) : 'default'
    } catch { return 'default' }
  })
  const [conversations, setConversations] = useState([])
  const [viewMode, setViewMode] = useState('initial')

  const bottomRef = useRef(null)
  const inputRef = useRef(null)
  const hashLoadedRef = useRef(false)

  const needsLogin = authEnabled && !authToken

  const handleLogin = useCallback((data) => {
    localStorage.setItem('sap_agent_token', data.access_token)
    if (data.refresh_token) localStorage.setItem('sap_agent_refresh_token', data.refresh_token)
    localStorage.setItem('sap_agent_user', JSON.stringify({ user_id: data.user_id, roles: data.roles, full_name: data.full_name }))
    setAuthToken(data.access_token)
    setCurrentUser({ user_id: data.user_id, roles: data.roles, full_name: data.full_name })
    if (data.warning) setDevSecretWarn(true)
    setSessionId(_getOrCreateSessionId(data.user_id))
  }, [])

  const handleLogout = useCallback(() => {
    localStorage.removeItem('sap_agent_token')
    localStorage.removeItem('sap_agent_refresh_token')
    localStorage.removeItem('sap_agent_user')
    setAuthToken(null); setCurrentUser(null); setMessages([]); setStreamingMsg(null); streamingRef.current = { content: '', status_steps: [] }; setAllowedModules(null)
    setConversations([]); setSessionId('default'); setViewMode('initial')
    hashLoadedRef.current = false; window.location.hash = '#/'
  }, [])

  useEffect(() => { _onSessionExpired = handleLogout; return () => { _onSessionExpired = null } }, [handleLogout])

  useEffect(() => {
    const check = async () => {
      try {
        const res = await apiFetch('/health')
        if (res.status === 401) { handleLogout(); return }
        const d = await res.json()
        setOllamaStatus(d.llm_connected ? 'connected' : 'disconnected')
        if (d.model) setModel(d.model)
        if (d.sap_mode) setSapMode(d.sap_mode)
        if (d.auth_enabled === false) setAuthEnabled(false)
        if (d.dev_secret) setDevSecretWarn(true)
      } catch { setOllamaStatus('disconnected') }
    }
    check(); const id = setInterval(check, 30000); return () => clearInterval(id)
  }, [authToken, handleLogout])

  useEffect(() => {
    if (!authToken) return
    apiFetch('/auth/me').then(r => { if (r.status === 401) { handleLogout(); return } return r.json() })
      .then(d => {
        if (!d) return
        if (d.roles?.includes('admin')) { setAllowedModules(null) }
        else {
          setAllowedModules(d.allowed_modules || [])
          if (d.allowed_modules?.length === 1) {
            const mod = MODULES.find(m => m.moduleKey === d.allowed_modules[0])
            if (mod) setActiveModule(mod.id)
          }
        }
      }).catch(() => { })
  }, [authToken, handleLogout])

  useEffect(() => {
    if (needsLogin) return
    apiFetch('/tools').then(r => { if (r.status === 401) { handleLogout(); return } return r.json() }).then(d => d).catch(() => { })
  }, [authToken, needsLogin, handleLogout])

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, streamingMsg, loading])

  // ── History helpers ─────────────────────────────────────────────────────────
  const loadConversations = useCallback(async () => {
    try {
      const res = await apiFetch('/conversations')
      if (res.ok) { const d = await res.json(); setConversations(d.conversations || []) }
    } catch { }
  }, [])

  useEffect(() => {
    if (!authToken || needsLogin) return
    loadConversations()
  }, [authToken, needsLogin, loadConversations])

  const handleNewChat = useCallback(() => {
    const userId = currentUser?.user_id
    if (!userId) return
    const newSid = _makeSessionId(userId)
    localStorage.setItem(`sap_session_${userId}`, newSid)
    setSessionId(newSid)
    setMessages([]); setStreamingMsg(null); setViewMode('initial')
    window.location.hash = '#/'
  }, [currentUser])

  const handleLoadConversation = useCallback(async (sid) => {
    if (rafRef.current) { cancelAnimationFrame(rafRef.current); rafRef.current = null }
    if (tableRafRef.current) { cancelAnimationFrame(tableRafRef.current); tableRafRef.current = null }
    setStreamingMsg(null)
    setLoading(false)
    try {
      const res = await apiFetch(`/conversations/${encodeURIComponent(sid)}/messages`)
      if (!res.ok) return
      const data = await res.json()
      const uInitial = currentUser ? (currentUser.full_name || currentUser.user_id)[0].toUpperCase() : 'U'
      const msgs = data.messages.map(m => ({
        role: m.role,
        content: m.content,
        userInitial: uInitial,
        tool_called: m.tool_called || null,
        tool_result: m.tool_result || null,
        sap_source: m.sap_source || null,
        abap_check: m.abap_check || null,
        abap_code: m.abap_code || null,
        report: m.report || null,
        status_steps: m.status_steps || [],
        tableData: _extractTableData(m.tool_result),
      }))
      setMessages(msgs)
      setSessionId(sid)
      setViewMode('conversation')
      window.location.hash = `#/chat/${encodeURIComponent(sid)}`
      if (currentUser?.user_id) localStorage.setItem(`sap_session_${currentUser.user_id}`, sid)
    } catch { }
  }, [currentUser])

  // Restore conversation from URL hash on page load / login
  useEffect(() => {
    if (!currentUser || hashLoadedRef.current) return
    hashLoadedRef.current = true
    const hash = window.location.hash
    if (hash.startsWith('#/chat/')) {
      const sid = decodeURIComponent(hash.replace('#/chat/', ''))
      if (sid) handleLoadConversation(sid)
    }
  }, [currentUser, handleLoadConversation])

  // Handle browser back/forward
  useEffect(() => {
    const onHashChange = () => {
      const hash = window.location.hash
      if (hash.startsWith('#/chat/')) {
        const sid = decodeURIComponent(hash.replace('#/chat/', ''))
        if (sid) handleLoadConversation(sid)
      } else {
        setMessages([]); setStreamingMsg(null); setViewMode('initial')
      }
    }
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [handleLoadConversation])

  const handleDeleteConversation = useCallback(async (sid) => {
    try {
      await apiFetch(`/conversations/${encodeURIComponent(sid)}`, { method: 'DELETE' })
      setConversations(prev => prev.filter(c => c.session_id !== sid))
      if (sid === sessionId) { handleNewChat() }
    } catch { }
  }, [sessionId, handleNewChat])

  const handleSettingsClose = () => {
    setShowSettings(false)
    apiFetch('/health').then(r => r.json()).then(d => {
      if (d.model) setModel(d.model)
      if (d.sap_mode) setSapMode(d.sap_mode)
      setOllamaStatus(d.llm_connected ? 'connected' : 'disconnected')
    }).catch(() => { })
  }

  const userInitial = currentUser ? (currentUser.full_name || currentUser.user_id)[0].toUpperCase() : 'U'

  const sendResearch = useCallback(async (text) => {
    const msg = text.trim(); if (!msg || loading) return
    setViewMode('conversation')
    setMessages(p => [...p, { role: 'user', content: msg, userInitial }])
    setInput(''); setLoading(true)
    try {
      const res = await apiFetch('/research', { method: 'POST', body: JSON.stringify({ query: msg }) })
      if (res.status === 401) { handleLogout(); return }
      const data = await res.json()
      if (!res.ok) { setMessages(p => [...p, { role: 'bot', content: `Error: ${data.detail || 'Unknown error'}` }]); return }
      setMessages(p => [...p, {
        role: 'bot', content: data.report, research_mode: true,
        research_result: { formatted_report: data.report, anomalies: data.anomalies || [], tools_run: data.tools_used || [], sources_used: data.sap_sources || [], entity_type: data.entity_type, entity_id: data.entity_id },
        request_id: data.request_id,
      }])
    } catch { setMessages(p => [...p, { role: 'bot', content: 'Error: Cannot reach the SAP AI Agent API.' }]) }
    finally { setLoading(false); setTimeout(() => inputRef.current?.focus(), 50) }
  }, [loading, handleLogout, userInitial])

  const sendMessage = useCallback(async (text) => {
    if (researchMode) return sendResearch(text)
    const msg = text.trim(); if (!msg || loading) return
    setViewMode('conversation')
    setMessages(p => [...p, { role: 'user', content: msg, userInitial }])
    setInput(''); setLoading(true)
    if (rafRef.current) { cancelAnimationFrame(rafRef.current); rafRef.current = null }
    if (tableRafRef.current) { cancelAnimationFrame(tableRafRef.current); tableRafRef.current = null }
    streamingRef.current = { content: '', status_steps: [] }
    tableRef.current = null
    setStreamingMsg({ content: '', status_steps: [] })

    try {
      const token = localStorage.getItem('sap_agent_token')
      const headers = { 'Content-Type': 'application/json' }
      if (token) headers['Authorization'] = `Bearer ${token}`

      let res = await fetch(`${API}/chat/stream`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ message: msg, model, session_id: sessionId }),
      })

      if (res.status === 401) {
        const refreshed = await refreshAccessToken()
        if (!refreshed) { handleLogout(); setStreamingMsg(null); return }
        headers['Authorization'] = `Bearer ${localStorage.getItem('sap_agent_token')}`
        res = await fetch(`${API}/chat/stream`, {
          method: 'POST', headers,
          body: JSON.stringify({ message: msg, model, session_id: sessionId }),
        })
      }

      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        setStreamingMsg(null)
        setMessages(p => [...p, { role: 'bot', content: `Error: ${data.detail || 'Unknown error'}` }])
        return
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        // SSE events are delimited by double newline
        const parts = buffer.split('\n\n')
        buffer = parts.pop() // keep incomplete trailing chunk

        for (const part of parts) {
          if (!part.trim()) continue
          const lines = part.split('\n')
          let eventType = 'message'
          let dataStr = ''
          for (const line of lines) {
            if (line.startsWith('event: ')) eventType = line.slice(7).trim()
            if (line.startsWith('data: ')) dataStr = line.slice(6).trim()
          }
          if (!dataStr) continue
          let payload
          try { payload = JSON.parse(dataStr) } catch { continue }

          if (eventType === 'status') {
            streamingRef.current.status_steps = [...streamingRef.current.status_steps, payload.step]
            setStreamingMsg(prev => prev ? ({ ...prev, status_steps: streamingRef.current.status_steps }) : prev)

          } else if (eventType === 'text_delta') {
            streamingRef.current.content += payload.delta || ''
            if (!rafRef.current) {
              rafRef.current = requestAnimationFrame(() => {
                rafRef.current = null
                setStreamingMsg(prev => prev ? ({ ...prev, content: streamingRef.current.content }) : prev)
              })
            }

          } else if (eventType === 'table_start') {
            tableRef.current = { columns: payload.columns, rows: [], total: payload.total, loading: true }
            setStreamingMsg(prev => prev ? ({ ...prev, tableData: tableRef.current }) : prev)

          } else if (eventType === 'table_rows') {
            if (tableRef.current) {
              tableRef.current = { ...tableRef.current, rows: [...tableRef.current.rows, ...payload.rows] }
              if (!tableRafRef.current) {
                tableRafRef.current = requestAnimationFrame(() => {
                  tableRafRef.current = null
                  setStreamingMsg(prev => prev ? ({ ...prev, tableData: tableRef.current }) : prev)
                })
              }
            }

          } else if (eventType === 'table_end') {
            if (tableRef.current) {
              tableRef.current = { ...tableRef.current, loading: false }
              setStreamingMsg(prev => prev ? ({ ...prev, tableData: tableRef.current }) : prev)
            }

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

          } else if (eventType === 'error') {
            setStreamingMsg(null)
            setMessages(p => [...p, { role: 'bot', content: `Error: ${payload.message || 'Unknown error'}` }])
          }
        }
      }
    } catch {
      setStreamingMsg(null)
      setMessages(p => [...p, { role: 'bot', content: 'Error: Cannot reach the SAP AI Agent API. Make sure the server is running on port 8000.' }])
    } finally {
      setLoading(false)
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [loading, model, handleLogout, researchMode, sendResearch, userInitial, sessionId, loadConversations])

  const handleKeyDown = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(input) } }
  const handleReset = async () => {
    setMessages([]); setStreamingMsg(null)
    try { await apiFetch('/reset', { method: 'POST', body: JSON.stringify({ message: '', model, session_id: sessionId }) }) } catch { }
  }

  const currentModule = MODULES.find(m => m.id === activeModule) || MODULES[0]
  const showExamples = viewMode === 'initial'
  const primaryRole = currentUser?.roles?.[0]
  const statusLabel = { checking: 'Checking…', connected: 'LLM Online', disconnected: 'LLM Offline' }[ollamaStatus]

  if (needsLogin) return <LoginScreen onLogin={handleLogin} />

  return (
    <div className="app-shell">
      {showSettings && <SettingsModal onClose={handleSettingsClose} currentUser={currentUser} />}
      {devSecretWarn && <DevWarningBanner />}

      {/* Topbar */}
      <header className="topbar">
        <div className="topbar-left">
          <div className="topbar-logo">SAP</div>
          <span className="topbar-name">SAP AI Agent</span>
          <span className="topbar-sep" />
          <span className="topbar-subtitle">Natural Language ERP Interface</span>
        </div>
        <div className="topbar-right">
          <div className="status-pill">
            <div className={`status-dot ${ollamaStatus}`} />
            <span>{statusLabel}</span>
          </div>
          {currentUser && (
            <div className="user-chip">
              <div className="user-avatar">{userInitial}</div>
              <div className="user-info">
                <span className="user-name">{currentUser.full_name || currentUser.user_id}</span>
                {primaryRole && <span className="user-role">{ROLE_LABELS[primaryRole] || primaryRole}</span>}
              </div>
              <button className="icon-btn" onClick={handleLogout} title="Sign out" style={{ marginLeft: 2 }}>
                <Icons.logout />
              </button>
            </div>
          )}
          <button className="icon-btn" onClick={() => setShowSettings(true)} title="Configuration">
            <Icons.settings />
          </button>
        </div>
      </header>

      <div className="body-row">
        <Sidebar
          activeModule={activeModule}
          onModuleClick={setActiveModule}
          onReset={handleReset}
          sapMode={sapMode}
          allowedModules={allowedModules}
          conversations={conversations}
          sessionId={viewMode === 'conversation' ? sessionId : null}
          onNewChat={handleNewChat}
          onLoadConversation={handleLoadConversation}
          onDeleteConversation={handleDeleteConversation}
        />

        {/* Chat */}
        <div className="chat-area">
          {showExamples ? (
            <div className="welcome-panel">
              <div className="welcome-icon">
                <ModuleIcon iconId={currentModule.iconId} color={currentModule.color} size={26} />
              </div>
              <h2 className="welcome-title">Ask anything about {currentModule.name}</h2>
              <p className="welcome-sub">{currentModule.desc} — select an example or type your own query below</p>
              <div className="examples-grid">
                {currentModule.examples.map((ex, i) => (
                  <button key={i} className="example-card" onClick={() => sendMessage(ex)}>{ex}</button>
                ))}
              </div>
            </div>
          ) : (
            <div className="messages-list">
              {messages.map((msg, i) => <MessageRow key={i} msg={msg} />)}
              {streamingMsg && <StreamingMessageRow msg={streamingMsg} />}
              {!streamingMsg && loading && <TypingIndicator />}
              <div ref={bottomRef} />
            </div>
          )}

          {/* Input bar */}
          <div className="input-bar">
            <div className="input-controls">
              <select className="model-select" value={model} onChange={e => setModel(e.target.value)} disabled={researchMode} title="Select LLM model">
                {MODELS.map(m => <option key={m} value={m}>{m}</option>)}
              </select>
              <button className={`research-btn ${researchMode ? 'on' : ''}`} onClick={() => setResearchMode(r => !r)} title="Toggle Auto Research — chains multiple SAP tools automatically">
                <Icons.beaker />{researchMode ? 'Research ON' : 'Research'}
              </button>
            </div>
            <div className="input-wrap">
              <textarea
                ref={inputRef}
                className={`chat-input ${researchMode ? 'research-mode' : ''}`}
                rows={1}
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={researchMode
                  ? 'Research any SAP entity — e.g. "research vendor V001" or "deep dive on MAT002"'
                  : activeModule === 'ABAP'
                    ? 'Ask about ABAP… e.g. "Generate ABAP code for: transport DEVK900123 status check" or paste code to review'
                    : `Ask about ${currentModule.name}… (Enter to send, Shift+Enter for newline)`
                }
                disabled={loading}
              />
              <button
                className={`send-btn ${researchMode ? 'research-mode' : ''}`}
                onClick={() => sendMessage(input)}
                disabled={!input.trim() || loading}
                title="Send"
              >
                {loading ? <div className="spinner" /> : <Icons.send />}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
