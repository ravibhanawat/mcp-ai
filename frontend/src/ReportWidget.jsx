/**
 * SAP AI Agent — Inline Report Widgets
 *
 * Renders chart/table widgets inline inside chat bubbles.
 * All drawn with pure SVG + CSS — zero external chart libraries.
 *
 * Exported component: <ReportWidget report={...} />
 *
 * Supported chart_type values (from report_agent.py):
 *   pie     → SVG arc pie chart + legend
 *   bar     → CSS flex horizontal bar chart
 *   heatmap → CSS grid of color-tinted tiles
 *   pivot   → HTML pivot table with row/col totals
 *   table   → Sortable data table with status-row colouring
 */

import { useState } from 'react'

// ─── Colour palette ───────────────────────────────────────────────────────────

const PALETTE = [
  '#0070D2', '#16a34a', '#d97706', '#7c3aed',
  '#db2777', '#0891b2', '#ea580c', '#65a30d',
  '#9333ea', '#0284c7', '#dc2626', '#059669',
]

const STATUS_BG = {
  normal:   'rgba(22,163,74,0.15)',
  warning:  'rgba(217,119,6,0.18)',
  critical: 'rgba(220,38,38,0.15)',
  ok:       'rgba(22,163,74,0.15)',
}
const STATUS_FG = {
  normal:   '#16a34a',
  warning:  '#d97706',
  critical: '#dc2626',
  ok:       '#16a34a',
}

// Interpolate a value 0-100 between three colours (low → mid → high)
function heatColor(value, config = {}) {
  const low  = config.low_color  || '#16a34a'
  const mid  = config.mid_color  || '#d97706'
  const high = config.high_color || '#dc2626'
  const warnThr = config.thresholds?.warning  ?? 50
  const critThr = config.thresholds?.critical ?? 80
  if (value >= critThr) return high
  if (value >= warnThr) return mid
  return low
}

// ─── Pie Chart ────────────────────────────────────────────────────────────────

function PieChart({ data = [], config = {} }) {
  const [hovered, setHovered] = useState(null)
  const SIZE  = 160
  const CX    = SIZE / 2
  const CY    = SIZE / 2
  const R     = SIZE / 2 - 10
  const total = data.reduce((s, d) => s + d.value, 0) || 1

  let cumAngle = -Math.PI / 2   // start at top

  const slices = data.map((d, i) => {
    const angle = (d.value / total) * 2 * Math.PI
    const x1 = CX + R * Math.cos(cumAngle)
    const y1 = CY + R * Math.sin(cumAngle)
    cumAngle += angle
    const x2 = CX + R * Math.cos(cumAngle)
    const y2 = CY + R * Math.sin(cumAngle)
    const large = angle > Math.PI ? 1 : 0
    const path = [
      `M ${CX} ${CY}`,
      `L ${x1} ${y1}`,
      `A ${R} ${R} 0 ${large} 1 ${x2} ${y2}`,
      'Z',
    ].join(' ')
    return { ...d, path, color: PALETTE[i % PALETTE.length], index: i }
  })

  return (
    <div className="rw-pie-wrap">
      <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`}>
        {slices.map(s => (
          <path
            key={s.index}
            d={s.path}
            fill={s.color}
            stroke="#fff"
            strokeWidth={hovered === s.index ? 2 : 1}
            opacity={hovered === null || hovered === s.index ? 1 : 0.65}
            style={{ cursor: 'pointer', transition: 'opacity 0.2s' }}
            onMouseEnter={() => setHovered(s.index)}
            onMouseLeave={() => setHovered(null)}
          />
        ))}
        {/* Centre label */}
        <text x={CX} y={CY - 4} textAnchor="middle" fontSize="11" fill="var(--text-secondary)" fontWeight="600">{data.length}</text>
        <text x={CX} y={CY + 10} textAnchor="middle" fontSize="9"  fill="var(--text-secondary)">items</text>
      </svg>
      {/* Legend */}
      <ul className="rw-pie-legend">
        {slices.map(s => (
          <li
            key={s.index}
            className={`rw-pie-legend-item ${hovered === s.index ? 'active' : ''}`}
            onMouseEnter={() => setHovered(s.index)}
            onMouseLeave={() => setHovered(null)}
          >
            <span className="rw-pie-dot" style={{ background: s.color }} />
            <span className="rw-pie-label">{s.label}</span>
            <span className="rw-pie-val">{s.value} {config.unit || ''}</span>
            <span className="rw-pie-pct">({s.pct}%)</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

// ─── Bar Chart ────────────────────────────────────────────────────────────────

function BarChart({ data = [], config = {} }) {
  const max = Math.max(...data.map(d => d.value), 1)
  const color = config.color || '#0070D2'

  return (
    <div className="rw-bar-wrap">
      {data.map((d, i) => {
        const pct = (d.value / max) * 100
        const barColor = PALETTE[i % PALETTE.length]
        return (
          <div key={i} className="rw-bar-row">
            <div className="rw-bar-label" title={d.label}>{d.label}</div>
            <div className="rw-bar-track">
              <div
                className="rw-bar-fill"
                style={{ width: `${pct}%`, background: barColor, transition: 'width 0.5s ease' }}
              />
            </div>
            <div className="rw-bar-val">{d.value} <span className="rw-bar-unit">{config.unit || ''}</span></div>
          </div>
        )
      })}
    </div>
  )
}

// ─── Heat Map ─────────────────────────────────────────────────────────────────

function HeatMap({ data = [], config = {} }) {
  return (
    <div className="rw-heat-grid">
      {data.map((d, i) => {
        const bg = heatColor(d.value, config)
        return (
          <div
            key={i}
            className="rw-heat-tile"
            style={{ background: bg + '33', border: `1.5px solid ${bg}` }}
            title={`${d.label}: ${d.value}${config.unit || ''}`}
          >
            <div className="rw-heat-tile-label">{d.id || d.label}</div>
            <div className="rw-heat-tile-name">{d.id ? d.label : ''}</div>
            <div className="rw-heat-tile-value" style={{ color: bg }}>
              {d.value}{config.unit || ''}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ─── Pivot Table ──────────────────────────────────────────────────────────────

function PivotTable({ rows = [], columns = [], values = [], config = {} }) {
  // Calculate max value for cell tinting
  const allVals = values.flat()
  const maxVal = Math.max(...allVals, 1)

  // Row totals & col totals
  const rowTotals = values.map(row => row.reduce((a, b) => a + b, 0))
  const colTotals = columns.map((_, ci) => values.reduce((sum, row) => sum + (row[ci] || 0), 0))
  const grandTotal = rowTotals.reduce((a, b) => a + b, 0)

  return (
    <div className="rw-pivot-wrap">
      <table className="rw-pivot-table">
        <thead>
          <tr>
            <th className="rw-pivot-th rw-pivot-corner">{config.row_label || 'Row'}</th>
            {columns.map((col, ci) => (
              <th key={ci} className="rw-pivot-th">{col}</th>
            ))}
            <th className="rw-pivot-th rw-pivot-total">Total</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr key={ri}>
              <td className="rw-pivot-row-label">{row}</td>
              {(values[ri] || []).map((val, ci) => {
                const intensity = maxVal > 0 ? val / maxVal : 0
                const bg = `rgba(0, 112, 210, ${(intensity * 0.35).toFixed(2)})`
                return (
                  <td key={ci} className="rw-pivot-cell" style={{ background: bg }}>
                    {val}
                  </td>
                )
              })}
              <td className="rw-pivot-row-total">{rowTotals[ri]}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td className="rw-pivot-row-label rw-pivot-foot-label">Total</td>
            {colTotals.map((t, ci) => (
              <td key={ci} className="rw-pivot-col-total">{t}</td>
            ))}
            <td className="rw-pivot-grand-total">{grandTotal}</td>
          </tr>
        </tfoot>
      </table>
    </div>
  )
}

// ─── Data Table ───────────────────────────────────────────────────────────────

function DataTable({ columns = [], rows = [], config = {} }) {
  const [sortCol, setSortCol]   = useState(null)
  const [sortDir, setSortDir]   = useState('asc')

  const statusCol = config.status_column ?? null
  const statusMap = config.status_map   || {}

  const handleSort = (ci) => {
    if (sortCol === ci) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortCol(ci); setSortDir('asc') }
  }

  const sorted = [...rows].sort((a, b) => {
    if (sortCol === null) return 0
    const av = a[sortCol] ?? ''
    const bv = b[sortCol] ?? ''
    const n  = (v) => parseFloat(v)
    const cmp = !isNaN(n(av)) && !isNaN(n(bv))
      ? n(av) - n(bv)
      : String(av).localeCompare(String(bv))
    return sortDir === 'asc' ? cmp : -cmp
  })

  return (
    <div className="rw-table-wrap">
      <table className="rw-table">
        <thead>
          <tr>
            {columns.map((col, ci) => (
              <th
                key={ci}
                className="rw-table-th"
                onClick={() => handleSort(ci)}
                style={{ cursor: 'pointer', userSelect: 'none' }}
              >
                {col}
                <span className="rw-sort-icon">
                  {sortCol === ci ? (sortDir === 'asc' ? ' ↑' : ' ↓') : ' ⇅'}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, ri) => {
            const rawStatus = statusCol !== null ? (row[statusCol] || '') : ''
            const status    = statusMap[rawStatus] || rawStatus
            const bg        = STATUS_BG[status]  || ''
            return (
              <tr key={ri} style={{ background: bg }}>
                {row.map((cell, ci) => {
                  if (ci === statusCol) {
                    const fg = STATUS_FG[status] || 'inherit'
                    return (
                      <td key={ci} className="rw-table-td">
                        <span className="rw-status-chip" style={{ color: fg, background: bg, border: `1px solid ${fg}` }}>
                          {cell}
                        </span>
                      </td>
                    )
                  }
                  return <td key={ci} className="rw-table-td">{cell}</td>
                })}
              </tr>
            )
          })}
          {sorted.length === 0 && (
            <tr><td colSpan={columns.length} className="rw-table-empty">No data</td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

// ─── Main dispatcher ──────────────────────────────────────────────────────────

/**
 * @param {{ report: object }} props
 *   report.chart_type  — 'pie' | 'bar' | 'heatmap' | 'pivot' | 'table'
 *   report.title       — string
 *   report.data        — array (pie / bar / heatmap)
 *   report.rows        — array (pivot)
 *   report.columns     — array (pivot / table)
 *   report.values      — 2-D array (pivot)
 *   report.config      — object
 */
export default function ReportWidget({ report }) {
  if (!report) return null

  const { chart_type, title, data, rows, columns, values, config } = report

  let chart = null
  switch (chart_type) {
    case 'pie':
      chart = <PieChart data={data} config={config} />
      break
    case 'bar':
      chart = <BarChart data={data} config={config} />
      break
    case 'heatmap':
      chart = <HeatMap data={data} config={config} />
      break
    case 'pivot':
      chart = <PivotTable rows={rows} columns={columns} values={values} config={config} />
      break
    case 'table':
      chart = <DataTable columns={columns} rows={rows} config={config} />
      break
    default:
      chart = <BarChart data={data || []} config={config || {}} />
  }

  const typeLabel = {
    pie:     'Pie Chart',
    bar:     'Bar Chart',
    heatmap: 'Heat Map',
    pivot:   'Pivot Table',
    table:   'Data Table',
  }[chart_type] || 'Chart'

  return (
    <div className="rw-root">
      <div className="rw-header">
        <span className="rw-title">{title}</span>
        <span className="rw-type-badge">{typeLabel}</span>
      </div>
      <div className="rw-body">
        {chart}
      </div>
    </div>
  )
}
