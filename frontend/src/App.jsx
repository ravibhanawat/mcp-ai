import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import './App.css'
import { VList } from 'virtua'
import ReportWidget from './ReportWidget'
import { AbapReviewWidget, AbapCodeWidget } from './AbapWidget'
import ReceiptWidget from './ReceiptWidget'
import useChatStore from './stores/chat-store.js'
import { sendMessage as streamSend } from './lib/ask-stream.js'
import PhaseStepper from './components/chat/PhaseStepper.jsx'
import MarkdownRenderer from './components/ui/MarkdownRenderer.jsx'
import MessageRowComponent from './components/chat/MessageRow.jsx'
import StreamingMessageRow from './components/chat/StreamingMessageRow.jsx'
import DataPanel from './components/data/DataPanel.jsx'
import { API, apiFetch, apiJson, setSessionExpiredHandler } from './lib/api'
import AIConfiguration from './components/admin/AIConfiguration'

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

const MODELS = ['kutty', 'llama3.2', 'llama3.1', 'mistral', 'gemma2', 'codellama']
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
  clavis: () => (
    <Svg size={18}>
      <path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" />
    </Svg>
  ),
}

function ModuleIcon({ iconId, color, size = 14 }) {
  const I = Icons[iconId] || Icons.grid
  return <span style={{ color, display: 'flex', alignItems: 'center' }}><I size={size} /></span>
}

function statusClass(val) {
  const s = String(val).toLowerCase()
  if (['ok', 'open', 'active', 'paid', 'delivered', 'success', 'released'].includes(s)) return 'st-success'
  if (['blocked', 'error', 'cancelled', 'failed', 'poor'].includes(s)) return 'st-error'
  if (['pending', 'partial', 'in_progress', 'in_transit', 'modifiable', 'needs_review'].includes(s)) return 'st-warning'
  return ''
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

// ─── getNumericColumns Helper ──────────────────────────────────────────────────

function getNumericColumns(columns, rows) {
  if (!rows || rows.length === 0) return []
  return columns.filter(col => {
    return rows.some(row => {
      const val = row[col]
      if (val === null || val === undefined || val === '') return false
      const parsed = parseFloat(String(val).replace(/[$,%]/g, '').trim())
      return !isNaN(parsed)
    })
  })
}

const polarToCartesian = (centerX, centerY, radius, angleInDegrees) => {
  const angleInRadians = (angleInDegrees - 90) * Math.PI / 180.0
  return {
    x: centerX + (radius * Math.cos(angleInRadians)),
    y: centerY + (radius * Math.sin(angleInRadians))
  }
}

const getArcPath = (x, y, radius, startAngle, endAngle) => {
  const start = polarToCartesian(x, y, radius, endAngle)
  const end = polarToCartesian(x, y, radius, startAngle)
  const largeArcFlag = endAngle - startAngle <= 180 ? "0" : "1"
  return [
    "M", x, y,
    "L", start.x, start.y,
    "A", radius, radius, 0, largeArcFlag, 0, end.x, end.y,
    "Z"
  ].join(" ")
}

// ─── DataVisualizer Component ───────────────────────────────────────────────

function DataVisualizer({ columns, rows }) {
  const [xCol, setXCol] = useState('')
  const [yCol, setYCol] = useState('')
  const [chartType, setChartType] = useState('bar')
  const [hoveredIdx, setHoveredIdx] = useState(null)
  
  const numericCols = getNumericColumns(columns, rows)
  
  useEffect(() => {
    if (columns.length > 0) {
      const firstNonNum = columns.find(c => !numericCols.includes(c)) || columns[0]
      setXCol(firstNonNum)
    }
    if (numericCols.length > 0) {
      setYCol(numericCols[0])
    }
  }, [columns, numericCols])

  if (!rows || rows.length === 0) return <div className="chart-empty">No rows to visualize</div>
  if (numericCols.length === 0) return <div className="chart-empty">No numeric columns found for visualization</div>

  const getVal = (r, col) => {
    if (!r || !col) return 0
    const raw = r[col]
    if (raw === null || raw === undefined) return 0
    const val = parseFloat(String(raw).replace(/[$,%]/g, '').trim())
    return isNaN(val) ? 0 : val
  }

  let chartData = rows.map((r, i) => ({
    label: String(r[xCol] || `Item ${i + 1}`),
    value: getVal(r, yCol),
    raw: r
  }))

  const hasNonZero = chartData.some(d => d.value > 0)
  if (hasNonZero) {
    chartData = chartData.filter(d => d.value > 0)
  }

  chartData.sort((a, b) => b.value - a.value)

  const maxItems = 10
  if (chartData.length > maxItems) {
    const top = chartData.slice(0, maxItems - 1)
    const other = chartData.slice(maxItems - 1)
    const otherSum = other.reduce((sum, d) => sum + d.value, 0)
    chartData = [
      ...top,
      { label: 'Other', value: otherSum, raw: null }
    ]
  }

  const maxValue = Math.max(...chartData.map(d => d.value), 1)
  const sumValues = chartData.reduce((sum, d) => sum + d.value, 0)

  const width = 640
  const height = 360
  const pad = { top: 40, right: 200, bottom: 60, left: 60 }
  const chartW = width - pad.left - pad.right
  const chartH = height - pad.top - pad.bottom

  const colors = [
    '#3B82F6', '#8B5CF6', '#10B981', '#F59E0B', '#EC4899', '#06B6D4',
    '#6366F1', '#EF4444', '#14B8A6', '#84CC16', '#F43F5E', '#A855F7'
  ]

  const gridTicks = [0, 0.25, 0.5, 0.75, 1]

  const renderChart = () => {
    if (chartType === 'bar') {
      const barW = (chartW / chartData.length) * 0.65
      const barGap = (chartW / chartData.length) * 0.35
      return (
        <g>
          {gridTicks.map((tick, idx) => {
            const y = pad.top + chartH * (1 - tick)
            return (
              <g key={idx}>
                <line x1={pad.left} y1={y} x2={pad.left + chartW} y2={y} stroke="var(--border)" strokeDasharray="3 3" strokeWidth="1" />
                <text x={pad.left - 8} y={y + 4} textAnchor="end" fontSize="10" fill="var(--text-muted)">
                  {Math.round(tick * maxValue).toLocaleString()}
                </text>
              </g>
            )
          })}
          {chartData.map((d, i) => {
            const h = (d.value / maxValue) * chartH
            const x = pad.left + i * (barW + barGap) + barGap / 2
            const y = pad.top + chartH - h
            const isHovered = hoveredIdx === i
            const color = colors[i % colors.length]
            return (
              <g key={i} onMouseEnter={() => setHoveredIdx(i)} onMouseLeave={() => setHoveredIdx(null)} style={{ cursor: 'pointer' }}>
                <rect 
                  x={x} 
                  y={y} 
                  width={barW} 
                  height={Math.max(h, 2)} 
                  fill={color} 
                  opacity={isHovered ? 0.95 : 0.8}
                  rx="4"
                  style={{ transition: 'all 0.15s ease' }}
                />
                {(isHovered || chartData.length <= 8) && (
                  <text 
                    x={x + barW / 2} 
                    y={y - 6} 
                    textAnchor="middle" 
                    fontSize="10" 
                    fontWeight="600" 
                    fill="var(--text-primary)"
                  >
                    {d.value.toLocaleString()}
                  </text>
                )}
                <text 
                  x={x + barW / 2} 
                  y={pad.top + chartH + 16} 
                  textAnchor="middle" 
                  fontSize="9.5" 
                  fill="var(--text-secondary)"
                  transform={`rotate(15, ${x + barW / 2}, ${pad.top + chartH + 16})`}
                >
                  {d.label.length > 10 ? d.label.slice(0, 10) + '..' : d.label}
                </text>
              </g>
            )
          })}
          <line x1={pad.left} y1={pad.top + chartH} x2={pad.left + chartW} y2={pad.top + chartH} stroke="var(--border)" strokeWidth="1" />
        </g>
      )
    }

    if (chartType === 'line') {
      const ptCount = chartData.length
      const getPtX = (idx) => pad.left + (ptCount > 1 ? idx * (chartW / (ptCount - 1)) : chartW / 2)
      const getPtY = (idx) => pad.top + chartH - (chartData[idx].value / maxValue) * chartH

      const points = chartData.map((d, idx) => ({ x: getPtX(idx), y: getPtY(idx) }))
      let pathD = ''
      if (points.length > 0) {
        pathD = `M ${points[0].x} ${points[0].y} ` + points.slice(1).map(p => `L ${p.x} ${p.y}`).join(' ')
      }
      
      const areaPathD = points.length > 0 
        ? `${pathD} L ${points[points.length - 1].x} ${pad.top + chartH} L ${points[0].x} ${pad.top + chartH} Z`
        : ''

      return (
        <g>
          {gridTicks.map((tick, idx) => {
            const y = pad.top + chartH * (1 - tick)
            return (
              <g key={idx}>
                <line x1={pad.left} y1={y} x2={pad.left + chartW} y2={y} stroke="var(--border)" strokeDasharray="3 3" strokeWidth="1" />
                <text x={pad.left - 8} y={y + 4} textAnchor="end" fontSize="10" fill="var(--text-muted)">
                  {Math.round(tick * maxValue).toLocaleString()}
                </text>
              </g>
            )
          })}
          
          {areaPathD && (
            <path d={areaPathD} fill="url(#line-grad)" opacity="0.1" />
          )}

          {pathD && (
            <path d={pathD} fill="none" stroke="var(--accent)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
          )}

          {points.map((pt, idx) => {
            const isHovered = hoveredIdx === idx
            return (
              <g 
                key={idx} 
                onMouseEnter={() => setHoveredIdx(idx)} 
                onMouseLeave={() => setHoveredIdx(null)}
                style={{ cursor: 'pointer' }}
              >
                <circle 
                  cx={pt.x} 
                  cy={pt.y} 
                  r={isHovered ? 6 : 4} 
                  fill="var(--accent)" 
                  stroke="var(--bg-card)" 
                  strokeWidth="2" 
                  style={{ transition: 'all 0.15s ease' }}
                />
                {(isHovered || ptCount <= 8) && (
                  <text 
                    x={pt.x} 
                    y={pt.y - 10} 
                    textAnchor="middle" 
                    fontSize="10" 
                    fontWeight="600" 
                    fill="var(--text-primary)"
                  >
                    {chartData[idx].value.toLocaleString()}
                  </text>
                )}
                <text 
                  x={pt.x} 
                  y={pad.top + chartH + 16} 
                  textAnchor="middle" 
                  fontSize="9.5" 
                  fill="var(--text-secondary)"
                  transform={`rotate(15, ${pt.x}, ${pad.top + chartH + 16})`}
                >
                  {chartData[idx].label.length > 10 ? chartData[idx].label.slice(0, 10) + '..' : chartData[idx].label}
                </text>
              </g>
            )
          })}
          <line x1={pad.left} y1={pad.top + chartH} x2={pad.left + chartW} y2={pad.top + chartH} stroke="var(--border)" strokeWidth="1" />
        </g>
      )
    }

    if (chartType === 'pie' || chartType === 'donut') {
      const centerX = pad.left + chartW / 2
      const centerY = pad.top + chartH / 2
      const radius = Math.min(chartW, chartH) / 2 * 0.95
      
      let accumulatedAngle = 0
      
      return (
        <g>
          {sumValues === 0 ? (
            <text x={centerX} y={centerY} textAnchor="middle" fill="var(--text-muted)">No data value</text>
          ) : (
            chartData.map((d, i) => {
              const pct = d.value / sumValues
              const angleSize = pct * 360
              const startAngle = accumulatedAngle
              const endAngle = accumulatedAngle + angleSize
              accumulatedAngle = endAngle

              const pathD = getArcPath(centerX, centerY, radius, startAngle, endAngle)
              const isHovered = hoveredIdx === i
              const color = colors[i % colors.length]

              const midAngle = startAngle + angleSize / 2
              const centroidRad = radius * (chartType === 'donut' ? 0.72 : 0.6)
              const centroid = polarToCartesian(centerX, centerY, centroidRad, midAngle)

              return (
                <g 
                  key={i} 
                  onMouseEnter={() => setHoveredIdx(i)} 
                  onMouseLeave={() => setHoveredIdx(null)}
                  style={{ cursor: 'pointer' }}
                >
                  <path 
                    d={pathD} 
                    fill={color} 
                    opacity={isHovered ? 0.95 : 0.8}
                    stroke="var(--bg-card)"
                    strokeWidth="1.5"
                    style={{ transition: 'all 0.15s ease' }}
                  />
                  {pct > 0.05 && (
                    <text 
                      x={centroid.x} 
                      y={centroid.y + 4} 
                      textAnchor="middle" 
                      fontSize="9" 
                      fontWeight="600" 
                      fill="#ffffff"
                    >
                      {Math.round(pct * 100)}%
                    </text>
                  )}
                </g>
              )
            })
          )}
          {chartType === 'donut' && (
            <circle cx={centerX} cy={centerY} r={radius * 0.55} fill="var(--bg-card)" stroke="var(--border)" strokeWidth="0.5" />
          )}
        </g>
      )
    }
  }

  return (
    <div className="visualizer-container">
      <div className="visualizer-config">
        <div className="vis-config-group">
          <label className="vis-label">Chart Type</label>
          <div className="vis-tabs">
            {['bar', 'line', 'pie', 'donut'].map(type => (
              <button 
                key={type} 
                className={`vis-tab ${chartType === type ? 'active' : ''}`}
                onClick={() => setChartType(type)}
              >
                {type.toUpperCase()}
              </button>
            ))}
          </div>
        </div>

        <div className="vis-config-fields">
          <div className="vis-field">
            <label className="vis-label">X-Axis Label</label>
            <select className="form-select vis-select" value={xCol} onChange={e => setXCol(e.target.value)}>
              {columns.map(col => <option key={col} value={col}>{col.replace(/_/g, ' ').toUpperCase()}</option>)}
            </select>
          </div>
          <div className="vis-field">
            <label className="vis-label">Y-Axis Metric</label>
            <select className="form-select vis-select" value={yCol} onChange={e => setYCol(e.target.value)}>
              {numericCols.map(col => <option key={col} value={col}>{col.replace(/_/g, ' ').toUpperCase()}</option>)}
            </select>
          </div>
        </div>
      </div>

      <div className="visualizer-content">
        <div className="visualizer-chart-wrap">
          <svg width={width} height={height} className="visualizer-svg">
            <defs>
              <linearGradient id="line-grad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.4"/>
                <stop offset="100%" stopColor="var(--accent)" stopOpacity="0.0"/>
              </linearGradient>
            </defs>
            {renderChart()}
          </svg>
        </div>

        <div className="visualizer-legend">
          <span className="legend-title">{yCol.replace(/_/g, ' ').toUpperCase()} Distribution</span>
          <div className="legend-list">
            {chartData.map((d, i) => {
              const color = colors[i % colors.length]
              const pct = sumValues > 0 ? ((d.value / sumValues) * 100).toFixed(1) : '0'
              const isHovered = hoveredIdx === i
              return (
                <div 
                  key={i} 
                  className={`legend-item ${isHovered ? 'hovered' : ''}`}
                  onMouseEnter={() => setHoveredIdx(i)}
                  onMouseLeave={() => setHoveredIdx(null)}
                >
                  <span className="legend-bullet" style={{ background: color }} />
                  <span className="legend-name" title={d.label}>{d.label}</span>
                  <span className="legend-val">
                    <strong>{d.value.toLocaleString()}</strong> 
                    <span className="legend-pct">({pct}%)</span>
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      </div>
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

// ─── MessageRow (legacy — superseded by components/chat/MessageRow.jsx) ───────

function MessageRowLegacy({ msg, onViewData, onVisualizeData }) {
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

// ─── Plan Icons ──────────────────────────────────────────────────────────────

function PlanCheckIcon({ size = "h-4.5 w-4.5" }) {
  return (
    <svg className={`${size} text-green-500`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" style={{ width: '16px', height: '16px' }}>
      <circle cx="12" cy="12" r="10" />
      <path d="m9 12 2 2 4-4" />
    </svg>
  )
}

function PlanProgressIcon({ size = "h-4.5 w-4.5" }) {
  return (
    <svg className={`${size} text-blue-500`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" style={{ width: '16px', height: '16px', animation: 'spin 3s linear infinite' }}>
      <path d="M10.1 2.182a10 10 0 0 1 3.8 0" />
      <path d="M13.9 21.818a10 10 0 0 1-3.8 0" />
      <path d="M17.603 4.2a10 10 0 0 1 2.2 3.1" />
      <path d="M4.197 19.8a10 10 0 0 1-2.2-3.1" />
      <path d="M21.818 10.1a10 10 0 0 1 0 3.8" />
      <path d="M2.182 13.9a10 10 0 0 1 0-3.8" />
      <path d="M19.803 17.6a10 10 0 0 1-3.1 2.2" />
      <path d="M4.197 6.4a10 10 0 0 1 3.1-2.2" />
    </svg>
  )
}

function PlanAlertIcon({ size = "h-4.5 w-4.5" }) {
  return (
    <svg className={`${size} text-yellow-500`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" style={{ width: '16px', height: '16px' }}>
      <circle cx="12" cy="12" r="10" />
      <line x1="12" y1="8" x2="12" y2="12" />
      <line x1="12" y1="16" x2="12.01" y2="16" />
    </svg>
  )
}

function PlanFailedIcon({ size = "h-4.5 w-4.5" }) {
  return (
    <svg className={`${size} text-red-500`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" style={{ width: '16px', height: '16px' }}>
      <circle cx="12" cy="12" r="10" />
      <line x1="15" y1="9" x2="9" y2="15" />
      <line x1="9" y1="9" x2="15" y2="15" />
    </svg>
  )
}

function PlanPendingIcon({ size = "h-4.5 w-4.5" }) {
  return (
    <svg className={`${size} text-muted-foreground`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ width: '16px', height: '16px', opacity: 0.6 }}>
      <circle cx="12" cy="12" r="10" />
    </svg>
  )
}

// Initial task data for Plan component
const initialTasks = [
  {
    id: "1",
    title: "Research Project Requirements",
    description: "Gather all necessary information about project scope and requirements",
    status: "in-progress",
    priority: "high",
    level: 0,
    dependencies: [],
    subtasks: [
      {
        id: "1.1",
        title: "Interview stakeholders",
        description: "Conduct interviews with key stakeholders to understand needs",
        status: "completed",
        priority: "high",
        tools: ["communication-agent", "meeting-scheduler"],
      },
      {
        id: "1.2",
        title: "Review existing documentation",
        description: "Go through all available documentation and extract requirements",
        status: "in-progress",
        priority: "medium",
        tools: ["file-system", "browser"],
      },
      {
        id: "1.3",
        title: "Compile findings report",
        description: "Create a comprehensive report of all gathered information",
        status: "need-help",
        priority: "medium",
        tools: ["file-system", "markdown-processor"],
      },
    ],
  },
  {
    id: "2",
    title: "Design System Architecture",
    description: "Create the overall system architecture based on requirements",
    status: "in-progress",
    priority: "high",
    level: 0,
    dependencies: [],
    subtasks: [
      {
        id: "2.1",
        title: "Define component structure",
        description: "Map out all required components and their interactions",
        status: "pending",
        priority: "high",
        tools: ["architecture-planner", "diagramming-tool"],
      },
      {
        id: "2.2",
        title: "Create data flow diagrams",
        description: "Design diagrams showing how data will flow through the system",
        status: "pending",
        priority: "medium",
        tools: ["diagramming-tool", "file-system"],
      },
      {
        id: "2.3",
        title: "Document API specifications",
        description: "Write detailed specifications for all APIs in the system",
        status: "pending",
        priority: "high",
        tools: ["api-designer", "openapi-generator"],
      },
    ],
  },
  {
    id: "3",
    title: "Implementation Planning",
    description: "Create a detailed plan for implementing the system",
    status: "pending",
    priority: "medium",
    level: 1,
    dependencies: ["1", "2"],
    subtasks: [
      {
        id: "3.1",
        title: "Resource allocation",
        description: "Determine required resources and allocate them to tasks",
        status: "pending",
        priority: "medium",
        tools: ["project-manager", "resource-calculator"],
      },
      {
        id: "3.2",
        title: "Timeline development",
        description: "Create a timeline with milestones and deadlines",
        status: "pending",
        priority: "high",
        tools: ["timeline-generator", "gantt-chart-creator"],
      },
      {
        id: "3.3",
        title: "Risk assessment",
        description: "Identify potential risks and develop mitigation strategies",
        status: "pending",
        priority: "medium",
        tools: ["risk-analyzer"],
      },
    ],
  },
  {
    id: "4",
    title: "Development Environment Setup",
    description: "Set up all necessary tools and environments for development",
    status: "in-progress",
    priority: "high",
    level: 0,
    dependencies: [],
    subtasks: [
      {
        id: "4.1",
        title: "Install development tools",
        description: "Set up IDEs, version control, and other necessary development tools",
        status: "pending",
        priority: "high",
        tools: ["shell", "package-manager"],
      },
      {
        id: "4.2",
        title: "Configure CI/CD pipeline",
        description: "Set up continuous integration and deployment pipelines",
        status: "pending",
        priority: "medium",
        tools: ["github-actions", "gitlab-ci", "jenkins-connector"],
      },
      {
        id: "4.3",
        title: "Set up testing framework",
        description: "Configure automated testing frameworks for the project",
        status: "pending",
        priority: "high",
        tools: ["test-runner", "shell"],
      },
    ],
  },
  {
    id: "5",
    title: "Initial Development Sprint",
    description: "Execute the first development sprint based on the plan",
    status: "pending",
    priority: "medium",
    level: 1,
    dependencies: ["4"],
    subtasks: [
      {
        id: "5.1",
        title: "Implement core features",
        description: "Develop the essential features identified in the requirements",
        status: "pending",
        priority: "high",
        tools: ["code-assistant", "github", "file-system", "shell"],
      },
      {
        id: "5.2",
        title: "Perform unit testing",
        description: "Create and execute unit tests for implemented features",
        status: "pending",
        priority: "medium",
        tools: ["test-runner", "code-coverage-analyzer"],
      },
      {
        id: "5.3",
        title: "Document code",
        description: "Create documentation for the implemented code",
        status: "pending",
        priority: "low",
        tools: ["documentation-generator", "markdown-processor"],
      },
    ],
  },
];

function Plan({ planData }) {
  const [tasks, setTasks] = useState(() => {
    if (planData && Array.isArray(planData) && planData.length > 0) {
      return planData;
    }
    return JSON.parse(JSON.stringify(initialTasks));
  });

  const [expandedTasks, setExpandedTasks] = useState(["1"]);
  const [expandedSubtasks, setExpandedSubtasks] = useState({});

  const toggleTaskExpansion = (taskId) => {
    setExpandedTasks((prev) =>
      prev.includes(taskId)
        ? prev.filter((id) => id !== taskId)
        : [...prev, taskId]
    );
  };

  const toggleSubtaskExpansion = (taskId, subtaskId) => {
    const key = `${taskId}-${subtaskId}`;
    setExpandedSubtasks((prev) => ({
      ...prev,
      [key]: !prev[key],
    }));
  };

  const toggleTaskStatus = (taskId) => {
    setTasks((prev) =>
      prev.map((task) => {
        if (task.id === taskId) {
          const statuses = ["completed", "in-progress", "pending", "need-help", "failed"];
          const currentIndex = Math.floor(Math.random() * statuses.length);
          const newStatus = statuses[currentIndex];

          const updatedSubtasks = task.subtasks.map((subtask) => ({
            ...subtask,
            status: newStatus === "completed" ? "completed" : subtask.status,
          }));

          return {
            ...task,
            status: newStatus,
            subtasks: updatedSubtasks,
          };
        }
        return task;
      })
    );
  };

  const toggleSubtaskStatus = (taskId, subtaskId) => {
    setTasks((prev) =>
      prev.map((task) => {
        if (task.id === taskId) {
          const updatedSubtasks = task.subtasks.map((subtask) => {
            if (subtask.id === subtaskId) {
              const newStatus =
                subtask.status === "completed" ? "pending" : "completed";
              return { ...subtask, status: newStatus };
            }
            return subtask;
          });

          const allSubtasksCompleted = updatedSubtasks.every(
            (s) => s.status === "completed"
          );

          return {
            ...task,
            subtasks: updatedSubtasks,
            status: allSubtasksCompleted ? "completed" : task.status,
          };
        }
        return task;
      })
    );
  };

  return (
    <div className="plan-container">
      <div className="plan-card">
        <ul className="plan-task-list">
          {tasks.map((task, index) => {
            const isExpanded = expandedTasks.includes(task.id);
            const isCompleted = task.status === "completed";

            return (
              <li key={task.id} className="plan-task-item">
                {/* Task row */}
                <div 
                  className="plan-task-row"
                  onClick={() => toggleTaskExpansion(task.id)}
                >
                  <div
                    className="plan-status-icon-wrap"
                    onClick={(e) => {
                      e.stopPropagation();
                      toggleTaskStatus(task.id);
                    }}
                  >
                    {task.status === "completed" ? (
                      <PlanCheckIcon />
                    ) : task.status === "in-progress" ? (
                      <PlanProgressIcon />
                    ) : task.status === "need-help" ? (
                      <PlanAlertIcon />
                    ) : task.status === "failed" ? (
                      <PlanFailedIcon />
                    ) : (
                      <PlanPendingIcon />
                    )}
                  </div>

                  <div className="plan-task-title-wrap">
                    <div style={{ flex: 1, minWidth: 0, paddingRight: '8px' }}>
                      <span className={`plan-task-title ${isCompleted ? 'completed' : ''}`}>
                        {task.title}
                      </span>
                    </div>

                    <div className="plan-task-meta">
                      {task.dependencies && task.dependencies.length > 0 && (
                        <div style={{ display: 'flex', gap: '4px' }}>
                          {task.dependencies.map((dep, idx) => (
                            <span key={idx} className="plan-dep-badge">
                              {dep}
                            </span>
                          ))}
                        </div>
                      )}

                      <span className={`plan-status-badge ${task.status}`}>
                        {task.status}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Subtasks connector and list */}
                <div 
                  className="plan-subtask-container"
                  style={{
                    maxHeight: isExpanded ? '1000px' : '0',
                    opacity: isExpanded ? 1 : 0,
                    pointerEvents: isExpanded ? 'auto' : 'none'
                  }}
                >
                  {task.subtasks && task.subtasks.length > 0 && (
                    <>
                      <div className="plan-subtask-connector" />
                      <ul className="plan-subtask-list">
                        {task.subtasks.map((subtask) => {
                          const subtaskKey = `${task.id}-${subtask.id}`;
                          const isSubtaskExpanded = expandedSubtasks[subtaskKey];

                          return (
                            <li 
                              key={subtask.id} 
                              className="plan-subtask-item"
                              onClick={() => toggleSubtaskExpansion(task.id, subtask.id)}
                            >
                              <div className="plan-subtask-row">
                                <div
                                  className="plan-status-icon-wrap"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    toggleSubtaskStatus(task.id, subtask.id);
                                  }}
                                >
                                  {subtask.status === "completed" ? (
                                    <PlanCheckIcon size="h-3.5 w-3.5" />
                                  ) : subtask.status === "in-progress" ? (
                                    <PlanProgressIcon size="h-3.5 w-3.5" />
                                  ) : subtask.status === "need-help" ? (
                                    <PlanAlertIcon size="h-3.5 w-3.5" />
                                  ) : subtask.status === "failed" ? (
                                    <PlanFailedIcon size="h-3.5 w-3.5" />
                                  ) : (
                                    <PlanPendingIcon size="h-3.5 w-3.5" />
                                  )}
                                </div>

                                <span className={`plan-subtask-title ${subtask.status === "completed" ? "completed" : ""}`}>
                                  {subtask.title}
                                </span>
                              </div>

                              <div 
                                className="plan-subtask-details"
                                style={{
                                  maxHeight: isSubtaskExpanded ? '200px' : '0',
                                  opacity: isSubtaskExpanded ? 1 : 0,
                                  pointerEvents: isSubtaskExpanded ? 'auto' : 'none'
                                }}
                              >
                                <p style={{ padding: '4px 0' }}>{subtask.description}</p>
                                {subtask.tools && subtask.tools.length > 0 && (
                                  <div className="plan-tools-row">
                                    <span className="plan-tools-label">MCP Servers:</span>
                                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                                      {subtask.tools.map((tool, idx) => (
                                        <span key={idx} className="plan-tool-badge">
                                          {tool}
                                        </span>
                                      ))}
                                    </div>
                                  </div>
                                )}
                              </div>
                            </li>
                          );
                        })}
                      </ul>
                    </>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}

// ─── ShiningText ──────────────────────────────────────────────────────────────

function ShiningText({ text }) {
  return <span className="shining-text">{text}</span>
}

// ─── TypingIndicator ──────────────────────────────────────────────────────────

function TypingIndicator() {
  return (
    <div className="typing-row">
      <div className="msg-avatar bot-av">AI</div>
      <div className="typing-bubble">
        <ShiningText text="Kutty is thinking..." />
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
    ...(isAdmin ? [{ id: 'ai', label: 'AI Configuration' }, { id: 'users', label: 'Users & Roles' }, { id: 'audit', label: 'Audit Logs' }] : []),
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
            <div className="form-warning">
              These settings have moved to <strong>AI Configuration</strong>, where you can
              register any provider — not only Ollama — and route different tasks to
              different models. This tab is read-only and will be removed in the next release.
            </div>
            <div className="form-group">
              <label className="form-label">Ollama Server URL</label>
              <input className="form-input mono" disabled value={cfg.ollama?.url || ''} onChange={e => setOllama('url', e.target.value)} placeholder="http://localhost:11434" />
              <span className="form-hint">Bind Ollama to <code style={{ fontFamily: 'var(--font-mono)' }}>127.0.0.1</code> only — never expose publicly.</span>
            </div>
            <div className="form-group">
              <label className="form-label">Default Model</label>
              <select className="form-select" disabled value={cfg.ollama?.default_model || 'llama3.2'} onChange={e => setOllama('default_model', e.target.value)}>
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

          {/* AI Configuration (admin) */}
          {tab === 'ai' && isAdmin && <AIConfiguration />}

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

function ClavisMark({ size = 42, variant = 'light' }) {
  // CLAVIS key logo. variant 'light' = solid navy; 'panel' = outlined for dark backgrounds.
  const w = size
  const h = Math.round(size * (54 / 58))
  return (
    <svg width={w} height={h} viewBox="0 0 58 54" fill="none">
      <polygon points="29,2 52,15 52,39 29,52 6,39 6,15"
        fill={variant === 'panel' ? '#24426e' : '#1B3254'}
        stroke={variant === 'panel' ? '#C89B3C' : 'none'} strokeWidth={variant === 'panel' ? 1.2 : 0}/>
      <circle cx="22" cy="27" r="9" fill="#C89B3C"/>
      <circle cx="22" cy="27" r="4" fill="#1B3254"/>
      <rect x="31" y="24.5" width="17" height="5" rx="2.5" fill="#C89B3C"/>
      <rect x="43" y="29.5" width="4.5" height="7" rx="2" fill="#C89B3C"/>
      <rect x="36.5" y="29.5" width="4" height="9" rx="2" fill="#C89B3C"/>
    </svg>
  )
}

// User-id quick-fill for local development only. Never carries passwords:
// anything in this file is compiled into the production bundle and readable by
// every visitor. import.meta.env.DEV is false in `vite build`, so the list and
// the block that renders it are dropped from the shipped asset.
const LG_DEV_BUILD = import.meta.env.DEV
const LG_DEMO_USER_IDS = LG_DEV_BUILD ? ['admin', 'fi_user', 'hr_user', 'demo'] : []

// Builds a CSS box-shadow string of randomly-placed stars across a 2000x2000 field.
// Paired with a ::after duplicate offset 2000px down so the upward drift loops seamlessly.
function lgStarShadows(count, color) {
  const out = []
  for (let i = 0; i < count; i++) {
    out.push(`${Math.floor(Math.random() * 2000)}px ${Math.floor(Math.random() * 2000)}px ${color}`)
  }
  return out.join(',')
}

function LoginScreen({ onLogin, theme = 'light' }) {
  const isDark = theme === 'dark'
  const [userId, setUserId] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [showPw, setShowPw] = useState(false)

  // Backdrop starfields — dense galaxy in dark mode, sparse constellation in light mode.
  const starsFaint = useMemo(() => lgStarShadows(700, 'rgba(255,255,255,.85)'), [])
  const starsMid = useMemo(() => lgStarShadows(220, 'rgba(207,227,255,.95)'), [])
  const starsGold = useMemo(() => lgStarShadows(70, 'rgba(230,200,126,.95)'), [])
  const starsGoldLight = useMemo(() => lgStarShadows(140, 'rgba(200,155,60,.55)'), [])
  const starsNavyLight = useMemo(() => lgStarShadows(90, 'rgba(27,50,84,.35)'), [])

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      const res = await fetch(`${API}/auth/login`, {
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
    <>
      <style>{`
        @keyframes lgRise{from{opacity:0;transform:translateY(26px) scale(.985)}to{opacity:1;transform:none}}
        @keyframes lgFloat{0%,100%{transform:translateY(0)}50%{transform:translateY(-9px)}}
        @keyframes lgFloatY{0%,100%{transform:translateY(0);opacity:.5}50%{transform:translateY(-26px);opacity:.9}}
        @keyframes lgGlow{0%,100%{opacity:.55;transform:scale(1)}50%{opacity:1;transform:scale(1.12)}}
        @keyframes lgSpin{to{transform:rotate(360deg)}}
        @keyframes lgStarDrift{from{transform:translateY(0)}to{transform:translateY(-2000px)}}
        @keyframes lgTwinkle{0%,100%{opacity:.45}50%{opacity:1}}
        @keyframes lgTwinkleSoft{0%,100%{opacity:.3}50%{opacity:.85}}
        @keyframes lgMwPulse{0%,100%{opacity:.7}50%{opacity:.95}}
        @keyframes lgDrift1{0%,100%{transform:translate(0,0)}50%{transform:translate(60px,40px)}}
        @keyframes lgDrift2{0%,100%{transform:translate(0,0)}50%{transform:translate(-50px,-30px)}}
        @keyframes lgShoot{0%{opacity:0;transform:translate(0,0) rotate(22deg)}4%{opacity:1}16%{opacity:0;transform:translate(420px,170px) rotate(22deg)}100%{opacity:0;transform:translate(420px,170px) rotate(22deg)}}

        .lg-root{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;overflow:hidden;font-family:var(--font-sans);-webkit-font-smoothing:antialiased}
        /* theme tokens */
        .lg-root.lg-dark{background:#081320;color:#eef2f8;
          --lg-ink:#eef2f8;--lg-ink2:#9fb0c8;--lg-line:rgba(255,255,255,.12);
          --lg-card-bg:linear-gradient(165deg, rgba(28,46,78,.72), rgba(12,26,48,.66));
          --lg-card-border:rgba(255,255,255,.12);
          --lg-card-shadow:0 40px 90px -30px rgba(0,0,0,.75), inset 0 1px 0 rgba(255,255,255,.08);
          --lg-logo-shadow:drop-shadow(0 10px 22px rgba(0,0,0,.5));
          --lg-wm-accent:#C89B3C;
          --lg-input-bg:rgba(255,255,255,.05);--lg-input-ph:#73849c;
          --lg-input-fborder:#C89B3C;--lg-input-fbg:rgba(255,255,255,.08);--lg-input-fring:rgba(200,155,60,.14);
          --lg-toggle-hover:#e6c87e;--lg-toggle-hover-bg:rgba(255,255,255,.06);
          --lg-link:#e6c87e;--lg-accent:#C89B3C;
          --lg-btn-bg:linear-gradient(180deg,#d6a945,#C89B3C);--lg-btn-color:#1a1300;--lg-btn-shadow:0 12px 28px -10px rgba(200,155,60,.7);
          --lg-spin-track:rgba(26,19,0,.3);--lg-spin-head:#1a1300;
          --lg-chip-bg:rgba(255,255,255,.05);--lg-chip-hover-color:#e6c87e;--lg-chip-hover-border:#C89B3C;--lg-chip-hover-bg:rgba(200,155,60,.08);
          --lg-error-bg:rgba(220,38,38,.14);--lg-error-border:rgba(248,113,113,.4);--lg-error-color:#ffb4b4;
          --lg-foot:#5b6c84}
        .lg-root.lg-light{background:#F6F1FA;color:#1a2233;
          --lg-ink:#1a2233;--lg-ink2:#5d6678;--lg-line:rgba(27,50,84,.12);
          --lg-card-bg:rgba(255,255,255,.72);
          --lg-card-border:rgba(255,255,255,.85);
          --lg-card-shadow:0 40px 90px -34px rgba(27,50,84,.32), 0 2px 10px rgba(27,50,84,.06), inset 0 1px 0 rgba(255,255,255,.9);
          --lg-logo-shadow:drop-shadow(0 8px 18px rgba(27,50,84,.22));
          --lg-wm-accent:#a87f28;
          --lg-input-bg:rgba(255,255,255,.85);--lg-input-ph:#9aa2b2;
          --lg-input-fborder:#1B3254;--lg-input-fbg:#fff;--lg-input-fring:rgba(27,50,84,.1);
          --lg-toggle-hover:#1B3254;--lg-toggle-hover-bg:rgba(27,50,84,.06);
          --lg-link:#1B3254;--lg-accent:#1B3254;
          --lg-btn-bg:#1B3254;--lg-btn-color:#fff;--lg-btn-shadow:0 12px 26px -10px rgba(27,50,84,.5);
          --lg-spin-track:rgba(255,255,255,.35);--lg-spin-head:#fff;
          --lg-chip-bg:rgba(255,255,255,.65);--lg-chip-hover-color:#1B3254;--lg-chip-hover-border:#1B3254;--lg-chip-hover-bg:#fff;
          --lg-error-bg:#fef2f2;--lg-error-border:#fecaca;--lg-error-color:#dc2626;
          --lg-foot:#97a0b2}

        /* ----- atmospheric background (shared structure, themed colors) ----- */
        .lg-bg{position:absolute;inset:0;overflow:hidden;z-index:0}
        .lg-bg-base{position:absolute;inset:0}
        .lg-dark .lg-bg-base{background:radial-gradient(70% 55% at 18% 22%, rgba(58,40,110,.55) 0%, transparent 60%),radial-gradient(60% 60% at 85% 78%, rgba(200,155,60,.14) 0%, transparent 60%),radial-gradient(55% 60% at 62% 30%, rgba(36,66,110,.6) 0%, transparent 65%),linear-gradient(160deg, #0a1124 0%, #05070f 60%, #03040a 100%)}
        .lg-light .lg-bg-base{background:radial-gradient(60% 50% at 18% 18%, rgba(200,155,60,.18) 0%, transparent 58%),radial-gradient(55% 55% at 85% 22%, rgba(225,165,185,.20) 0%, transparent 60%),radial-gradient(60% 60% at 80% 85%, rgba(130,170,225,.22) 0%, transparent 62%),linear-gradient(155deg, #FCF8F0 0%, #F3ECFA 48%, #E9F1FC 100%)}
        .lg-neb{position:absolute;border-radius:50%;filter:blur(78px);opacity:.5;pointer-events:none}
        .lg-dark .lg-neb{mix-blend-mode:screen}
        .lg-light .lg-neb{mix-blend-mode:normal;filter:blur(80px)}
        .lg-neb.n1{width:560px;height:560px;top:-140px;left:-90px;animation:lgDrift1 18s ease-in-out infinite}
        .lg-neb.n2{width:480px;height:480px;bottom:-150px;right:-70px;animation:lgDrift2 21s ease-in-out infinite}
        .lg-neb.n3{width:420px;height:420px;top:38%;left:54%;animation:lgDrift1 24s ease-in-out infinite reverse}
        .lg-neb.n4{width:360px;height:360px;top:8%;left:60%;animation:lgDrift2 26s ease-in-out infinite}
        .lg-dark .lg-neb.n1{background:radial-gradient(circle,#5b3aa0,transparent 70%)}
        .lg-dark .lg-neb.n2{background:radial-gradient(circle,#caa24a,transparent 70%);opacity:.28}
        .lg-dark .lg-neb.n3{background:radial-gradient(circle,#1f74a8,transparent 70%);opacity:.34}
        .lg-dark .lg-neb.n4{background:radial-gradient(circle,#a8437f,transparent 70%);opacity:.22}
        .lg-light .lg-neb.n1{background:radial-gradient(circle,rgba(200,155,60,.55),transparent 70%);opacity:.55}
        .lg-light .lg-neb.n2{background:radial-gradient(circle,rgba(130,170,225,.6),transparent 70%);opacity:.5}
        .lg-light .lg-neb.n3{background:radial-gradient(circle,rgba(190,150,225,.5),transparent 70%);opacity:.42}
        .lg-light .lg-neb.n4{background:radial-gradient(circle,rgba(228,150,175,.5),transparent 70%);opacity:.4}
        .lg-mw{position:absolute;width:175%;height:355px;top:25%;left:-38%;transform:rotate(-18deg);filter:blur(44px);mix-blend-mode:screen;opacity:.85;pointer-events:none;animation:lgMwPulse 12s ease-in-out infinite}
        .lg-dark .lg-mw{background:radial-gradient(ellipse at center, rgba(150,130,225,.20), rgba(120,150,225,.10) 42%, transparent 72%)}
        .lg-light .lg-mw{opacity:.8;background:radial-gradient(ellipse at center, rgba(255,255,255,.7), rgba(210,200,240,.28) 42%, transparent 72%)}
        .lg-stars{position:absolute;top:0;left:0;border-radius:50%;background:transparent;pointer-events:none}
        .lg-stars.s1{width:1px;height:1px;animation:lgStarDrift 140s linear infinite, lgTwinkle 4s ease-in-out infinite}
        .lg-stars.s2{width:2px;height:2px;animation:lgStarDrift 95s linear infinite, lgTwinkle 6s ease-in-out infinite .8s}
        .lg-stars.s3{width:2px;height:2px;animation:lgStarDrift 60s linear infinite, lgTwinkle 5s ease-in-out infinite .4s}
        .lg-light .lg-stars.s1{width:2px;height:2px;animation:lgStarDrift 130s linear infinite, lgTwinkleSoft 5s ease-in-out infinite}
        .lg-light .lg-stars.s2{animation:lgStarDrift 80s linear infinite, lgTwinkleSoft 6s ease-in-out infinite .6s}
        .lg-stars::after{content:" ";position:absolute;top:2000px;left:0;width:inherit;height:inherit;border-radius:50%;background:transparent;box-shadow:inherit}
        .lg-shoot{position:absolute;width:130px;height:2px;border-radius:2px;opacity:0;pointer-events:none;
          background:linear-gradient(90deg,#fff,rgba(255,255,255,0));filter:drop-shadow(0 0 6px rgba(255,255,255,.8))}
        .lg-shoot.sh1{top:16%;left:8%;animation:lgShoot 8s ease-in infinite 2s}
        .lg-shoot.sh2{top:40%;left:34%;animation:lgShoot 11s ease-in infinite 6s}
        .lg-light .lg-shoot{display:none}
        .lg-grid{position:absolute;inset:0;opacity:.55;background-size:54px 54px;-webkit-mask-image:radial-gradient(80% 80% at 50% 45%,#000 35%,transparent 85%);mask-image:radial-gradient(80% 80% at 50% 45%,#000 35%,transparent 85%)}
        .lg-dark .lg-grid{background-image:linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.035) 1px,transparent 1px)}
        .lg-light .lg-grid{background-image:linear-gradient(rgba(27,50,84,.05) 1px,transparent 1px),linear-gradient(90deg,rgba(27,50,84,.05) 1px,transparent 1px)}
        .lg-grain{position:absolute;inset:0;opacity:.05;pointer-events:none;
          background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='200'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='2'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E")}
        .lg-light .lg-grain{opacity:.035;mix-blend-mode:multiply}
        .lg-pt{position:absolute;width:5px;height:5px;border-radius:50%;opacity:.5}
        .lg-pt:nth-child(1){top:18%;left:24%;animation:lgFloatY 7s ease-in-out infinite}
        .lg-pt:nth-child(2){top:70%;left:18%;animation:lgFloatY 9s ease-in-out infinite 1s}
        .lg-pt:nth-child(3){top:30%;left:78%;animation:lgFloatY 8s ease-in-out infinite .5s}
        .lg-pt:nth-child(4){top:82%;left:72%;animation:lgFloatY 10s ease-in-out infinite 1.4s}
        .lg-pt:nth-child(5){top:12%;left:62%;animation:lgFloatY 6.5s ease-in-out infinite .8s}
        .lg-dark .lg-pt{background:#e6c87e;box-shadow:0 0 8px #e6c87e}
        .lg-dark .lg-pt:nth-child(2),.lg-dark .lg-pt:nth-child(4){background:#7fb6e0;box-shadow:0 0 8px #7fb6e0}
        .lg-light .lg-pt{background:rgba(200,155,60,.55);box-shadow:0 0 10px rgba(200,155,60,.5)}
        .lg-light .lg-pt:nth-child(2){background:rgba(130,170,225,.55);box-shadow:0 0 10px rgba(130,170,225,.55)}
        .lg-light .lg-pt:nth-child(4){background:rgba(190,150,225,.55);box-shadow:0 0 10px rgba(190,150,225,.55)}

        /* ----- card (themed via vars) ----- */
        .lg-card{position:relative;z-index:2;width:430px;max-width:calc(100vw - 40px);
          background:var(--lg-card-bg);
          border:1px solid var(--lg-card-border);border-radius:24px;padding:44px 46px;color:var(--lg-ink);
          -webkit-backdrop-filter:blur(22px) saturate(140%);backdrop-filter:blur(22px) saturate(140%);
          box-shadow:var(--lg-card-shadow);
          animation:lgRise .8s cubic-bezier(.2,.7,.2,1) both}
        .lg-card::before{content:"";position:absolute;top:-1px;left:34px;right:34px;height:1px;background:linear-gradient(90deg,transparent,#C89B3C,transparent);opacity:.75}
        .lg-logo-wrap{display:flex;flex-direction:column;align-items:center;margin-bottom:26px}
        .lg-halo-mark{position:relative;width:62px;height:58px;display:flex;align-items:center;justify-content:center;margin-bottom:16px}
        .lg-halo2{position:absolute;width:120px;height:120px;border-radius:50%;background:radial-gradient(circle,rgba(200,155,60,.32),transparent 65%);animation:lgGlow 4.5s ease-in-out infinite}
        .lg-halo-mark svg{position:relative;z-index:2;animation:lgFloat 5s ease-in-out infinite;filter:var(--lg-logo-shadow)}
        .lg-wordmark{font-family:var(--font-display);font-size:25px;font-weight:600;letter-spacing:.3px;color:var(--lg-ink)}
        .lg-wordmark b{color:var(--lg-wm-accent);font-weight:600}
        .lg-tagline{font-size:10.5px;letter-spacing:.26em;text-transform:uppercase;color:var(--lg-ink2);margin-top:7px}

        .lg-form2{display:flex;flex-direction:column;gap:15px;margin-top:6px}
        .lg-field2{position:relative}
        .lg-lbl{display:block;font-size:11.5px;font-weight:600;color:var(--lg-ink2);margin-bottom:7px;letter-spacing:.04em;text-transform:uppercase;font-family:var(--font-sans)}
        .lg-inp{width:100%;height:50px;border:1px solid var(--lg-line);border-radius:12px;padding:0 16px;font-size:14px;font-family:var(--font-sans);color:var(--lg-ink);background:var(--lg-input-bg);outline:none;transition:border-color .2s,box-shadow .2s,background .2s}
        .lg-inp::placeholder{color:var(--lg-input-ph)}
        .lg-inp:focus{border-color:var(--lg-input-fborder);background:var(--lg-input-fbg);box-shadow:0 0 0 4px var(--lg-input-fring)}
        .lg-pw-toggle2{position:absolute;right:6px;top:30px;height:40px;padding:0 12px;border:none;background:none;color:var(--lg-ink2);font-size:12px;font-weight:600;cursor:pointer;border-radius:8px;font-family:var(--font-sans)}
        .lg-pw-toggle2:hover{color:var(--lg-toggle-hover);background:var(--lg-toggle-hover-bg)}
        .lg-row2{display:flex;align-items:center;justify-content:space-between;margin-top:-3px}
        .lg-remember2{display:flex;align-items:center;gap:8px;font-size:12.5px;color:var(--lg-ink2);cursor:pointer;font-family:var(--font-sans)}
        .lg-remember2 input{accent-color:var(--lg-accent);width:15px;height:15px}
        .lg-link2{font-size:12.5px;font-weight:600;color:var(--lg-link);text-decoration:none;background:none;border:none;cursor:pointer;font-family:var(--font-sans);padding:0}
        .lg-link2:hover{text-decoration:underline}
        .lg-btn2{height:52px;margin-top:6px;border:none;border-radius:12px;cursor:pointer;background:var(--lg-btn-bg);color:var(--lg-btn-color);font-family:var(--font-sans);font-size:14.5px;font-weight:700;letter-spacing:.02em;display:flex;align-items:center;justify-content:center;gap:9px;box-shadow:var(--lg-btn-shadow);transition:transform .12s,box-shadow .2s,filter .2s,background .2s}
        .lg-dark .lg-btn2:hover:not(:disabled){filter:brightness(1.06);box-shadow:0 16px 34px -10px rgba(200,155,60,.8)}
        .lg-light .lg-btn2:hover:not(:disabled){background:#16294a;box-shadow:0 16px 32px -10px rgba(27,50,84,.55)}
        .lg-btn2:active:not(:disabled){transform:translateY(1px)}
        .lg-btn2:disabled{opacity:.55;cursor:not-allowed}
        .lg-spin2{width:15px;height:15px;border:2px solid var(--lg-spin-track);border-top-color:var(--lg-spin-head);border-radius:50%;animation:lgSpin .7s linear infinite}
        .lg-error{font-size:12.5px;color:var(--lg-error-color);background:var(--lg-error-bg);border:1px solid var(--lg-error-border);border-radius:10px;padding:10px 14px;font-family:var(--font-sans)}
        .lg-demo2{margin-top:26px;border-top:1px solid var(--lg-line);padding-top:16px}
        .lg-demo-label2{font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--lg-ink2);margin-bottom:10px;font-family:var(--font-sans)}
        .lg-demo-row{display:flex;flex-wrap:wrap;gap:7px}
        .lg-chip2{font-family:var(--font-mono);font-size:11px;color:var(--lg-ink2);background:var(--lg-chip-bg);border:1px solid var(--lg-line);border-radius:8px;padding:5px 11px;cursor:pointer;transition:all .15s}
        .lg-chip2:hover{color:var(--lg-chip-hover-color);border-color:var(--lg-chip-hover-border);background:var(--lg-chip-hover-bg)}
        .lg-foot2{position:absolute;bottom:22px;left:0;right:0;text-align:center;font-size:11px;color:var(--lg-foot);letter-spacing:.04em;z-index:2;font-family:var(--font-sans)}

        @media(max-width:480px){.lg-card{padding:36px 26px}}
      `}</style>

      <div className={`lg-root ${isDark ? 'lg-dark' : 'lg-light'}`}>
        {/* themed backdrop: galaxy (dark) / luminous sky (light) */}
        <div className="lg-bg">
          <div className="lg-bg-base" />
          <div className="lg-mw" />
          <div className="lg-neb n1" /><div className="lg-neb n2" /><div className="lg-neb n3" /><div className="lg-neb n4" />
          <div className="lg-stars s1" style={{ boxShadow: isDark ? starsFaint : starsGoldLight }} />
          <div className="lg-stars s2" style={{ boxShadow: isDark ? starsMid : starsNavyLight }} />
          {isDark && <div className="lg-stars s3" style={{ boxShadow: starsGold }} />}
          <div className="lg-shoot sh1" /><div className="lg-shoot sh2" />
          <div className="lg-grid" />
          <span className="lg-pt" /><span className="lg-pt" /><span className="lg-pt" /><span className="lg-pt" /><span className="lg-pt" />
          <div className="lg-grain" />
        </div>

        {/* glass login card */}
        <main className="lg-card">
          <div className="lg-logo-wrap">
            <div className="lg-halo-mark">
              <div className="lg-halo2" />
              <ClavisMark size={56} variant={isDark ? 'panel' : 'light'} />
            </div>
            <div className="lg-wordmark">KUTTY <b>AI</b></div>
            <div className="lg-tagline">Enterprise AI Assistant</div>
          </div>

          <form className="lg-form2" onSubmit={handleSubmit}>
            <div className="lg-field2">
              <label className="lg-lbl" htmlFor="lg-userid">User ID</label>
              <input
                id="lg-userid"
                className="lg-inp"
                value={userId}
                onChange={e => setUserId(e.target.value)}
                placeholder="Enter your user ID"
                autoFocus
                autoComplete="username"
              />
            </div>
            <div className="lg-field2">
              <label className="lg-lbl" htmlFor="lg-password">Password</label>
              <input
                id="lg-password"
                className="lg-inp"
                type={showPw ? 'text' : 'password'}
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="Enter your password"
                autoComplete="current-password"
                style={{ paddingRight: 70 }}
              />
              <button type="button" className="lg-pw-toggle2" onClick={() => setShowPw(p => !p)}>
                {showPw ? 'Hide' : 'Show'}
              </button>
            </div>

            <div className="lg-row2">
              <label className="lg-remember2"><input type="checkbox" /> Remember me</label>
              <button type="button" className="lg-link2">Need help?</button>
            </div>

            {error && <div className="lg-error">{error}</div>}

            <button className="lg-btn2" type="submit" disabled={!userId || !password || loading}>
              {loading && <span className="lg-spin2" />}
              {loading ? 'Verifying…' : 'Sign In'}
            </button>
          </form>

          {LG_DEV_BUILD && (
            <div className="lg-demo2">
              <div className="lg-demo-label2">Dev quick-fill (user id only)</div>
              <div className="lg-demo-row">
                {LG_DEMO_USER_IDS.map(u => (
                  <button key={u} className="lg-chip2" type="button" onClick={() => setUserId(u)}>
                    {u}
                  </button>
                ))}
              </div>
            </div>
          )}
        </main>

        <div className="lg-foot2">© KUTTY 2026 · Secure access via CLAVIS</div>
      </div>
    </>
  )
}

function _parseClaudeExample(ex) {
  const splitWords = [' for ', ' on ', ' about ', ' to ', ' of ', ' with ', ' in ']
  let title = ex
  let subtitle = ''
  
  for (const word of splitWords) {
    if (ex.includes(word)) {
      const parts = ex.split(word)
      title = parts[0]
      subtitle = word.trim() + ' ' + parts.slice(1).join(word)
      break
    }
  }

  if (!subtitle) {
    const words = ex.split(' ')
    if (words.length > 3) {
      title = words.slice(0, 3).join(' ')
      subtitle = words.slice(3).join(' ')
    } else {
      title = ex
      subtitle = 'Ask or query directly'
    }
  }

  return { title, subtitle }
}

function _getExampleIcon(ex, currentModule) {
  const lower = ex.toLowerCase()
  let iconId = currentModule?.iconId || 'grid'
  
  if (lower.includes('code') || lower.includes('abap') || lower.includes('transport') || lower.includes('develop')) {
    iconId = 'code'
  } else if (lower.includes('report') || lower.includes('utilization') || lower.includes('capacity') || lower.includes('chart') || lower.includes('metrics')) {
    iconId = 'grid'
  } else if (lower.includes('document') || lower.includes('bill') || lower.includes('order') || lower.includes('vendor') || lower.includes('material')) {
    iconId = 'package'
  } else if (lower.includes('dollar') || lower.includes('cost') || lower.includes('ledger') || lower.includes('gl')) {
    iconId = 'dollar'
  }
  
  return iconId
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

function Sidebar({ onReset, sapMode,
  conversations, sessionId, onNewChat, onLoadConversation, onDeleteConversation,
  collapsed, onToggleCollapse, searchQuery, onSearchChange, searchRef, currentUser, onLogout }) {
  const modeLabel = { mock: '🎭 Mock mode', cloud: '☁️ SAP Cloud', on_premise: '🏢 On-Premise' }[sapMode] || sapMode
  const filteredConversations = conversations.filter(c => 
    (c.title || 'Untitled').toLowerCase().includes((searchQuery || '').toLowerCase())
  )

  if (collapsed) {
    return (
      <div className="sidebar collapsed-sidebar">
        <div className="sidebar-collapsed-header">
          <button className="sidebar-toggle-btn" onClick={onToggleCollapse} title="Expand sidebar">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="4" y1="12" x2="20" y2="12" strokeLinecap="round" />
              <line x1="4" y1="6" x2="20" y2="6" strokeLinecap="round" />
              <line x1="4" y1="18" x2="20" y2="18" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        
        <div className="sidebar-collapsed-logo" title="Kutty">
          <svg width="22" height="20" viewBox="0 0 22 20" fill="none">
            <circle cx="7" cy="10" r="5.5" fill="#C89B3C"/>
            <circle cx="7" cy="10" r="2.2" fill="#1a1a2e"/>
            <rect x="12.5" y="8.5" width="8.5" height="3" rx="1.5" fill="#C89B3C"/>
            <rect x="18" y="11.5" width="2.5" height="4" rx="1" fill="#C89B3C"/>
            <rect x="14.5" y="11.5" width="2.2" height="5" rx="1" fill="#C89B3C"/>
          </svg>
        </div>

        <button className="sidebar-collapsed-icon-btn" onClick={() => { onToggleCollapse(); setTimeout(() => searchRef.current?.focus(), 150) }} title="Search chats">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
        </button>

        <button className="sidebar-collapsed-icon-btn" onClick={onNewChat} title="New chat">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="12" y1="5" x2="12" y2="19" strokeLinecap="round" />
            <line x1="5" y1="12" x2="19" y2="12" strokeLinecap="round" />
          </svg>
        </button>

        <div style={{ flex: 1 }} />

        <div className="sidebar-collapsed-footer">
          {currentUser && (
            <div className="sidebar-collapsed-user" title={currentUser.full_name || currentUser.user_id}>
              {currentUser.full_name ? currentUser.full_name[0].toUpperCase() : 'U'}
            </div>
          )}
          <button className="sidebar-collapsed-icon-btn logout-btn" onClick={onLogout} title="Sign out">
            <Icons.logout />
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <div className="sidebar-logo-section">
          <span className="sidebar-brand-name">CLA<span className="brand-accent">VIS</span></span>
          <span className="sidebar-brand-badge">v0.1</span>
        </div>
        <button className="sidebar-toggle-btn" onClick={onToggleCollapse} title="Collapse sidebar">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="4" y1="12" x2="20" y2="12" strokeLinecap="round" />
            <line x1="4" y1="6" x2="20" y2="6" strokeLinecap="round" />
            <line x1="4" y1="18" x2="20" y2="18" strokeLinecap="round" />
          </svg>
        </button>
      </div>

      <div className="sidebar-search-container">
        <div className="sidebar-search-wrap">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="search-icon">
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input
            ref={searchRef}
            type="text"
            className="sidebar-search-input"
            placeholder="Search chats"
            value={searchQuery}
            onChange={e => onSearchChange(e.target.value)}
          />
          <kbd className="sidebar-kbd">⌘K</kbd>
        </div>
      </div>

      <div className="sidebar-new-chat-container">
        <button className="sidebar-new-chat-btn" onClick={onNewChat}>
          <span className="plus-icon">+</span> New chat
        </button>
      </div>

      <div className="sidebar-history-header">
        <span className="sidebar-section-label" style={{ padding: 0 }}>Earlier</span>
      </div>

      <div className="history-list">
        {filteredConversations.map(c => (
          <div key={c.session_id}
            className={`history-item ${c.session_id === sessionId ? 'active' : ''}`}
            onClick={() => onLoadConversation(c.session_id)}>
            <div className="history-item-body">
              <span className="history-item-title">{c.title || 'Untitled'}</span>
              <span className="history-item-subtitle">
                {c.session_id ? c.session_id.slice(-10) : ''} · {c.msg_count || c.message_count || 2} msgs · {_relativeDate(c.updated_at)}
              </span>
            </div>
            <button className="history-del-btn" title="Delete"
              onClick={e => { e.stopPropagation(); onDeleteConversation(c.session_id) }}>
              <Icons.trash />
            </button>
          </div>
        ))}
        {filteredConversations.length === 0 && (
          <div className="history-empty">No conversations found</div>
        )}
      </div>
      <div className="sidebar-footer">
        {currentUser && (
          <div className="sidebar-user-section">
            <div className="sidebar-user-avatar">
              {currentUser.full_name ? currentUser.full_name[0].toUpperCase() : 'U'}
            </div>
            <div className="sidebar-user-details">
              <span className="user-name">{currentUser.full_name || currentUser.user_id}</span>
              <span className="user-role">READER</span>
            </div>
            <button className="sidebar-footer-logout-btn" onClick={onLogout} title="Sign out">
              <Icons.logout />
            </button>
          </div>
        )}
        <div className="sidebar-mode-label" style={{ marginTop: 8 }}>{modeLabel}</div>
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

function getModelIcon(modelName) {
  const lower = (modelName || '').toLowerCase()
  if (lower.includes('code')) {
    return (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <polyline points="16 18 22 12 16 6" />
        <polyline points="8 6 2 12 8 18" />
      </svg>
    )
  }
  if (lower.includes('gemma')) {
    return (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <polygon points="12 2 22 8.5 22 19.5 12 22 2 19.5 2 8.5" />
      </svg>
    )
  }
  if (lower.includes('mistral')) {
    return (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
      </svg>
    )
  }
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="3" y="11" width="18" height="10" rx="2" />
      <circle cx="12" cy="5" r="2" />
      <path d="M12 7v4" />
      <line x1="9" y1="16" x2="9" y2="16" />
      <line x1="15" y1="16" x2="15" y2="16" />
    </svg>
  )
}

export default function App() {
  const {
    isRunning,
    streamingAnswer,
    currentPhase,
    statusSteps,
    streamError,
    chatVisible,
    dataPanel,
    messages,
  } = useChatStore()
  const setMessages = (msgs) => {
    const store = useChatStore.getState()
    store.setMessages(typeof msgs === 'function' ? msgs(store.messages) : msgs)
  }
  const [input, setInput] = useState('')
  const [model, setModel] = useState('kutty')
  const [ollamaStatus, setOllamaStatus] = useState('checking')
  const [sapMode, setSapMode] = useState('mock')
  const [showSettings, setShowSettings] = useState(false)
  const [researchMode, setResearchMode] = useState(false)

  // ── Theme, Sidebar, Search & Modal States ───────────────────────────────────
  const [theme, setTheme] = useState(() => localStorage.getItem('theme') || 'light')
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => localStorage.getItem('sidebarCollapsed') === 'true')
  const [searchQuery, setSearchQuery] = useState('')
  const [showSuggestionsModal, setShowSuggestionsModal] = useState(false)

  const sidebarSearchRef = useRef(null)

  useEffect(() => {
    if (theme === 'dark') {
      document.documentElement.classList.add('dark')
    } else {
      document.documentElement.classList.remove('dark')
    }
    localStorage.setItem('theme', theme)
  }, [theme])

  useEffect(() => {
    localStorage.setItem('sidebarCollapsed', String(sidebarCollapsed))
  }, [sidebarCollapsed])

  useEffect(() => {
    const handleGlobalKeyDown = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setSidebarCollapsed(false)
        setTimeout(() => {
          sidebarSearchRef.current?.focus()
        }, 100)
      }
    }
    window.addEventListener('keydown', handleGlobalKeyDown)
    return () => window.removeEventListener('keydown', handleGlobalKeyDown)
  }, [])

  const [authToken, setAuthToken] = useState(() => localStorage.getItem('sap_agent_token'))
  const [currentUser, setCurrentUser] = useState(() => {
    try { return JSON.parse(localStorage.getItem('sap_agent_user') || 'null') } catch { return null }
  })
  const [authEnabled, setAuthEnabled] = useState(true)
  const [devSecretWarn, setDevSecretWarn] = useState(false)

  // ── Chat history ────────────────────────────────────────────────────────────
  const [sessionId, setSessionId] = useState(() => {
    try {
      const u = JSON.parse(localStorage.getItem('sap_agent_user') || 'null')
      return u?.user_id ? _getOrCreateSessionId(u.user_id) : 'default'
    } catch { return 'default' }
  })
  const [conversations, setConversations] = useState([])
  const [viewMode, setViewMode] = useState('initial')

  const vlistRef = useRef(null)
  const inputRef = useRef(null)
  const hashLoadedRef = useRef(false)
  const [showModelDropdown, setShowModelDropdown] = useState(false)

  const adjustInputHeight = () => {
    const textarea = inputRef.current
    if (!textarea) return
    textarea.style.height = 'auto'
    textarea.style.height = `${Math.min(textarea.scrollHeight, 260)}px`
  }

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
    setAuthToken(null); setCurrentUser(null); setMessages([])
    useChatStore.getState().resetStreamState()
    setConversations([]); setSessionId('default'); setViewMode('initial')
    hashLoadedRef.current = false; window.location.hash = '#/'
  }, [])

  useEffect(() => { setSessionExpiredHandler(handleLogout); return () => { setSessionExpiredHandler(null) } }, [handleLogout])

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
    if (needsLogin) return
    apiFetch('/tools').then(r => { if (r.status === 401) { handleLogout(); return } return r.json() }).then(d => d).catch(() => { })
  }, [authToken, needsLogin, handleLogout])

  // Auto-scroll chat to bottom when new messages arrive or stream updates
  useEffect(() => {
    const list = vlistRef.current
    if (!list) return
    const total = messages.length + (isRunning ? 1 : 0)
    if (total > 0) list.scrollToIndex(total - 1, { align: 'end', smooth: true })
  }, [messages.length, isRunning, streamingAnswer])

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
    setMessages([]); useChatStore.getState().resetStreamState(); setViewMode('initial')
    window.location.hash = '#/'
  }, [currentUser])

  const handleLoadConversation = useCallback(async (sid) => {
    useChatStore.getState().resetStreamState()
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
      setSidebarCollapsed(true)
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
        setMessages([]); useChatStore.getState().resetStreamState(); setViewMode('initial')
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
    const msg = text.trim(); if (!msg || isRunning) return
    setViewMode('conversation')
    setSidebarCollapsed(true)
    setMessages(p => [...p, { role: 'user', content: msg, userInitial }])
    setInput('')
    useChatStore.getState().setIsRunning(true)
    if (inputRef.current) inputRef.current.style.height = 'auto'
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
    } catch { setMessages(p => [...p, { role: 'bot', content: 'Error: Cannot reach the Kutty API.' }]) }
    finally { useChatStore.getState().setIsRunning(false); setTimeout(() => inputRef.current?.focus(), 50) }
  }, [isRunning, handleLogout, userInitial])

  const sendMessage = useCallback(async (text) => {
    if (researchMode) return sendResearch(text)
    const msg = text.trim()
    if (!msg || isRunning) return

    setViewMode('conversation')
    setSidebarCollapsed(true)
    setInput('')
    if (inputRef.current) inputRef.current.style.height = 'auto'

    const token = localStorage.getItem('sap_agent_token')
    await streamSend(msg, {
      token,
      onTokenRefresh: async () => {
        const refreshed = await refreshAccessToken()
        if (!refreshed) { handleLogout(); return null }
        return localStorage.getItem('sap_agent_token')
      },
      sessionId: sessionId || 'default',
      model,
      userInitial,
    })

    loadConversations()
    setTimeout(() => inputRef.current?.focus(), 50)
  }, [isRunning, researchMode, sendResearch, handleLogout, sessionId, loadConversations, model, userInitial])

  const handleKeyDown = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(input) } }
  const handleReset = async () => {
    setMessages([]); useChatStore.getState().resetStreamState()
    try { await apiFetch('/reset', { method: 'POST', body: JSON.stringify({ message: '', model, session_id: sessionId }) }) } catch { }
  }

  const showExamples = viewMode === 'initial'
  const primaryRole = currentUser?.roles?.[0]
  const statusLabel = { checking: 'Checking…', connected: 'LLM Online', disconnected: 'LLM Offline' }[ollamaStatus]

  if (needsLogin) return <LoginScreen onLogin={handleLogin} theme={theme} />

  return (
    <div className="app-shell">
      {showSettings && <SettingsModal onClose={handleSettingsClose} currentUser={currentUser} />}

      {(chatVisible || !dataPanel) && (
        <Sidebar
          onReset={handleReset}
          sapMode={sapMode}
          conversations={conversations}
          sessionId={viewMode === 'conversation' ? sessionId : null}
          onNewChat={handleNewChat}
          onLoadConversation={handleLoadConversation}
          onDeleteConversation={handleDeleteConversation}
          collapsed={sidebarCollapsed}
          onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
          searchRef={sidebarSearchRef}
          currentUser={currentUser}
          onLogout={handleLogout}
        />
      )}

      <div className="main-content-layout" style={(!chatVisible && dataPanel) ? { display: 'none' } : {}}>
        {devSecretWarn && <DevWarningBanner />}

        {/* Topbar */}
        <header className="topbar">
          <div className="topbar-left">
            <div className="topbar-logo">
              <svg width="18" height="17" viewBox="0 0 22 20" fill="none">
                <circle cx="7" cy="10" r="5.5" fill="#C89B3C"/>
                <circle cx="7" cy="10" r="2.2" fill="#1a1a2e"/>
                <rect x="12.5" y="8.5" width="8.5" height="3" rx="1.5" fill="#C89B3C"/>
                <rect x="18" y="11.5" width="2.5" height="4" rx="1" fill="#C89B3C"/>
                <rect x="14.5" y="11.5" width="2.2" height="5" rx="1" fill="#C89B3C"/>
              </svg>
            </div>
            <span className="topbar-name">KUTTY</span>
            <span className="topbar-sep" />
            <span className="topbar-subtitle">Enterprise AI Assistant</span>
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
            <button className="icon-btn" onClick={() => setTheme(t => t === 'light' ? 'dark' : 'light')} title="Toggle Light/Dark Theme">
              {theme === 'light' ? (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />
                </svg>
              ) : (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="4" />
                  <path d="M12 2v2" />
                  <path d="M12 20v2" />
                  <path d="m4.93 4.93 1.41 1.41" />
                  <path d="m17.66 17.66 1.41 1.41" />
                  <path d="M2 12h2" />
                  <path d="M20 12h2" />
                  <path d="m6.34 17.66-1.41 1.41" />
                  <path d="m19.07 4.93-1.41 1.41" />
                </svg>
              )}
            </button>
            <button className="icon-btn" onClick={() => setShowSettings(true)} title="Configuration">
              <Icons.settings />
            </button>
          </div>
        </header>

        {/* Chat */}
        <div className="chat-area">
          {showExamples ? (
            <div className="welcome-panel-gradient" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flex: 1, padding: '40px 20px', overflowY: 'auto' }}>
              <div className="chat-home-container">
                <div className="chat-home-header">
                  <h1 className="chat-home-title">How can I help today?</h1>
                  <p className="chat-home-subtitle">Type a command or ask a question</p>
                </div>

                {/* Explore Section */}
                <div className="google-explore-section">
                  <div className="google-explore-header">
                    <h2 className="google-explore-title">Explore Kutty agents</h2>
                  </div>

                  <div className="google-cards-grid">
                    <div className="google-card" onClick={() => setInput("What is the budget vs actual for Cost Center CC200?")}>
                      <div className="google-card-header">
                        <div className="google-card-icon icon-yellow">
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <line x1="12" y1="1" x2="12" y2="23" />
                            <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
                          </svg>
                        </div>
                        <span className="google-card-title">FI/CO Analyst</span>
                      </div>
                      <p className="google-card-desc">Finance & Controlling agent for invoices and budget checks.</p>
                    </div>

                    <div className="google-card" onClick={() => setInput("Check stock level for MAT002 at plant 1000")}>
                      <div className="google-card-header">
                        <div className="google-card-icon icon-blue">
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <polyline points="22 12 16 12 14 15 10 15 8 12 2 12" />
                            <path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />
                          </svg>
                        </div>
                        <span className="google-card-title">MM Stock Manager</span>
                      </div>
                      <p className="google-card-desc">Materials Management agent for stock levels and reordering.</p>
                    </div>

                    <div className="google-card" onClick={() => setInput("Show details for sales order SO5001")}>
                      <div className="google-card-header">
                        <div className="google-card-icon icon-purple">
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <circle cx="9" cy="21" r="1" />
                            <circle cx="20" cy="21" r="1" />
                            <path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6" />
                          </svg>
                        </div>
                        <span className="google-card-title">SD Sales Assistant</span>
                      </div>
                      <p className="google-card-desc">Sales & Distribution agent for tracking customer orders.</p>
                    </div>

                    <div className="google-card" onClick={() => setInput("Get employee info and leave balance for EMP001")}>
                      <div className="google-card-header">
                        <div className="google-card-icon icon-green">
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                            <circle cx="9" cy="7" r="4" />
                            <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
                            <path d="M16 3.13a4 4 0 0 1 0 7.75" />
                          </svg>
                        </div>
                        <span className="google-card-title">HR Representative</span>
                      </div>
                      <p className="google-card-desc">Human Resources agent for leaves, payslips, and employee data.</p>
                    </div>

                    <div className="google-card" onClick={() => setInput("Show outstanding for customer ALEC001 unit T1-304")}>
                      <div className="google-card-header">
                        <div className="google-card-icon icon-pink">
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M3 21h18" />
                            <path d="M19 21v-8a2 2 0 0 0-2-2H7a2 2 0 0 0-2 2v8" />
                            <path d="M9 21v-4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v4" />
                            <line x1="14" y1="1" x2="14" y2="4" />
                            <line x1="10" y1="1" x2="10" y2="4" />
                            <path d="M12 4a3 3 0 0 0-3 3v4h6V7a3 3 0 0 0-3-3z" />
                          </svg>
                        </div>
                        <span className="google-card-title">Real Estate Analyst</span>
                      </div>
                      <p className="google-card-desc">Parivartan agent for unit outstandings and cheque parking.</p>
                    </div>

                    <div className="google-card" onClick={() => setInput("Show program ZREP_VENDOR_LIST source code")}>
                      <div className="google-card-header">
                        <div className="google-card-icon icon-orange">
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <polyline points="16 18 22 12 16 6" />
                            <polyline points="8 6 2 12 8 18" />
                          </svg>
                        </div>
                        <span className="google-card-title">ABAP Developer</span>
                      </div>
                      <p className="google-card-desc">Development and transport status check assistant.</p>
                    </div>
                  </div>

                  <div className="google-explore-footer">
                    <a className="google-build-link" onClick={() => { inputRef.current?.focus() }}>
                      <span>Start building</span>
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <line x1="5" y1="12" x2="19" y2="12" />
                        <polyline points="12 5 19 12 12 19" />
                      </svg>
                    </a>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <VList ref={vlistRef} className="messages-list">
              {messages.map((msg, i) => (
                <MessageRowComponent
                  key={i}
                  msg={msg}
                  SapSourceBadge={SapSourceBadge}
                  ResearchReport={ResearchReport}
                  Plan={Plan}
                />
              ))}
              {isRunning && (
                <StreamingMessageRow
                  key="streaming"
                  msg={{
                    content: streamingAnswer,
                    status_steps: statusSteps,
                    currentPhase: currentPhase,
                  }}
                  Plan={Plan}
                />
              )}
              {streamError && (
                <div key="error" className="msg-row bot-row">
                  <div className="msg-bubble bot-bubble" style={{ color: 'var(--error, #dc2626)' }}>
                    ⚠ {streamError}
                  </div>
                </div>
              )}
            </VList>
          )}

          {/* Input bar */}
          <div className="input-bar">
            <div className={`prompt-box ${researchMode ? 'research-active' : ''}`}>
              <div className="prompt-textarea-container">
                <textarea
                  ref={inputRef}
                  className="prompt-textarea"
                  value={input}
                  placeholder={researchMode
                    ? 'Research any SAP entity — e.g. "research vendor V001" or "deep dive on MAT002"'
                    : 'Ask Kutty about SAP or your ticket backlog… (Enter to send, Shift+Enter for newline)'
                  }
                  onChange={e => {
                    setInput(e.target.value)
                    adjustInputHeight()
                  }}
                  onKeyDown={handleKeyDown}
                  disabled={isRunning}
                />
              </div>

              <div className="prompt-footer">
                <div className="prompt-footer-left">
                  {/* Custom Model Dropdown */}
                  <div className="custom-dropdown-container" style={{ position: 'relative' }}>
                    <button
                      type="button"
                      className={`custom-dropdown-trigger ${showModelDropdown ? 'open' : ''}`}
                      onClick={() => setShowModelDropdown(!showModelDropdown)}
                      disabled={researchMode}
                      title="Select LLM model"
                    >
                      {getModelIcon(model)}
                      <span style={{ textTransform: 'capitalize' }}>{model}</span>
                      <svg className="chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <polyline points="6 9 12 15 18 9" />
                      </svg>
                    </button>

                    {showModelDropdown && (
                      <div className="custom-dropdown-overlay">
                        <div className="custom-dropdown-backdrop" onClick={() => setShowModelDropdown(false)} />
                        <div className="custom-dropdown-menu">
                          <div className="custom-dropdown-header">Select Model</div>
                          {MODELS.map(m => (
                            <button
                              key={m}
                              type="button"
                              className={`custom-dropdown-item ${model === m ? 'active' : ''}`}
                              onClick={() => {
                                setModel(m)
                                setShowModelDropdown(false)
                              }}
                            >
                              <span className="dropdown-item-content">
                                {getModelIcon(m)}
                                <span className="dropdown-item-text">{m}</span>
                              </span>
                              {model === m && (
                                <svg className="check-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                                  <polyline points="20 6 9 17 4 12" />
                                </svg>
                              )}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>

                  <div className="prompt-divider" />

                  {/* Attachment Button */}
                  <label className="attachment-btn" title="Attach file">
                    <input
                      type="file"
                      className="hidden-file-input"
                      onChange={e => {
                        const file = e.target.files?.[0]
                        if (file) {
                          setInput(prev => prev + ` [Attached: ${file.name}] `)
                          setTimeout(adjustInputHeight, 50)
                        }
                      }}
                    />
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
                    </svg>
                  </label>

                  {/* Research Mode Toggle (Beaker) */}
                  <button
                    type="button"
                    className={`research-toggle-btn ${researchMode ? 'active' : ''}`}
                    onClick={() => setResearchMode(!researchMode)}
                    title="Toggle Auto Research — chains multiple SAP tools automatically"
                  >
                    <Icons.beaker />
                  </button>

                  {/* Suggestions Button */}
                  <button
                    type="button"
                    className="research-toggle-btn"
                    onClick={() => setShowSuggestionsModal(true)}
                    title="Show suggestions"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                      <line x1="9" y1="9" x2="9.01" y2="9" />
                      <line x1="15" y1="9" x2="15.01" y2="9" />
                      <line x1="9" y1="15" x2="15" y2="15" />
                    </svg>
                  </button>
                </div>

                <div className="prompt-footer-right">
                  {/* Send Button */}
                  <button
                    type="button"
                    className={`prompt-send-btn ${input.trim() && !isRunning ? 'active' : ''}`}
                    onClick={() => {
                      if (input.trim() && !isRunning) {
                        sendMessage(input)
                      }
                    }}
                    disabled={!input.trim() || isRunning}
                    title="Send message"
                  >
                    {isRunning ? (
                      <div className="spinner dark" />
                    ) : (
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                        <line x1="5" y1="12" x2="19" y2="12" />
                        <polyline points="12 5 19 12 12 19" />
                      </svg>
                    )}
                  </button>
                </div>
              </div>
            </div>
            <div className="input-footer">Kutty can make mistakes. Verify important results.</div>
          </div>
        </div>
      </div>
      {showSuggestionsModal && (
        <div className="suggestions-modal-overlay" onClick={() => setShowSuggestionsModal(false)}>
          <div className="suggestions-modal-card" onClick={e => e.stopPropagation()}>
            <div className="suggestions-modal-header">
              <span className="suggestions-modal-title">What would you like help with today?</span>
              <button className="suggestions-modal-close-btn" onClick={() => setShowSuggestionsModal(false)} title="Close">✕</button>
            </div>
            <div className="suggestions-modal-list">
              {MODULES[0].examples.map((ex, i) => (
                <div
                  key={i}
                  className="suggestions-modal-row"
                  onClick={() => {
                    sendMessage(ex);
                    setShowSuggestionsModal(false);
                  }}
                >
                  <span className="suggestions-modal-num">{i + 1}</span>
                  <span className="suggestions-modal-text">{ex}</span>
                  <span className="options-card-enter">↵</span>
                </div>
              ))}
              <div
                className="suggestions-modal-row"
                onClick={() => {
                  setShowSuggestionsModal(false);
                  setTimeout(() => inputRef.current?.focus(), 100);
                }}
              >
                <span className="suggestions-modal-num">{MODULES[0].examples.length + 1}</span>
                <span className="suggestions-modal-text">Something else</span>
                <span className="options-card-enter">↵</span>
              </div>
            </div>
            <div className="suggestions-modal-footer">
              <div className="suggestions-modal-input-wrap">
                <span className="suggestions-modal-pencil-icon">✎</span>
                <input
                  type="text"
                  className="suggestions-modal-input-field"
                  placeholder="Something else"
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === 'Enter' && input.trim()) {
                      sendMessage(input);
                      setShowSuggestionsModal(false);
                    }
                  }}
                />
              </div>
              <button className="suggestions-modal-skip-btn" onClick={() => setShowSuggestionsModal(false)}>Skip</button>
            </div>
          </div>
        </div>
      )}
      <DataPanel />
    </div>
  )
}
