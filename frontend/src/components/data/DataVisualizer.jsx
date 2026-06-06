import { useState, useMemo } from 'react'

function BarChart({ data, labelKey, valueKey }) {
  const max = Math.max(...data.map(d => Number(d[valueKey]) || 0), 1)
  return (
    <div className="bar-chart">
      {data.slice(0, 20).map((d, i) => {
        const val = Number(d[valueKey]) || 0
        const pct = (val / max) * 100
        return (
          <div key={i} className="bar-row">
            <span className="bar-label" title={String(d[labelKey])}>{String(d[labelKey])}</span>
            <div className="bar-track">
              <div className="bar-fill" style={{ width: `${pct}%` }} />
            </div>
            <span className="bar-value">{val}</span>
          </div>
        )
      })}
    </div>
  )
}

export default function DataVisualizer({ columns, rows }) {
  const [labelCol, setLabelCol] = useState(columns[0] || '')
  const [valueCol, setValueCol] = useState(columns[1] || '')

  const data = useMemo(() => rows.map(row => {
    const obj = {}
    columns.forEach((col, i) => { obj[col] = row[i] })
    return obj
  }), [columns, rows])

  return (
    <div className="data-visualizer">
      <div className="viz-controls">
        <label className="viz-label">
          Label:
          <select value={labelCol} onChange={e => setLabelCol(e.target.value)} className="viz-select">
            {columns.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <label className="viz-label">
          Value:
          <select value={valueCol} onChange={e => setValueCol(e.target.value)} className="viz-select">
            {columns.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
      </div>
      {labelCol && valueCol && (
        <BarChart data={data} labelKey={labelCol} valueKey={valueCol} />
      )}
    </div>
  )
}
