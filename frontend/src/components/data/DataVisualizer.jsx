import { useState, useMemo, useEffect, useRef, useCallback } from 'react'
import VChart from '@visactor/vchart'

const CHART_TYPES = [
  { id: 'bar',     label: 'Bar' },
  { id: 'line',    label: 'Line' },
  { id: 'area',    label: 'Area' },
  { id: 'pie',     label: 'Pie' },
  { id: 'donut',   label: 'Donut' },
  { id: 'scatter', label: 'Scatter' },
  { id: 'radar',   label: 'Radar' },
  { id: 'heatmap', label: 'Heatmap' },
]

function isNumeric(val) {
  if (val === null || val === undefined || val === '') return false
  return !isNaN(parseFloat(String(val).replace(/[$,%]/g, '')))
}

function numVal(val) {
  if (val === null || val === undefined || val === '') return 0
  return parseFloat(String(val).replace(/[$,%]/g, '')) || 0
}

function buildSpec(chartType, data, labelCol, valueCol, value2Col) {
  const theme = {
    colorScheme: {
      default: ['#6366f1','#8b5cf6','#06b6d4','#10b981','#f59e0b','#ec4899','#f43f5e','#3b82f6','#a855f7','#14b8a6']
    }
  }

  const baseStyle = {
    background: 'transparent',
  }

  if (chartType === 'bar') {
    return {
      ...baseStyle,
      type: 'bar',
      data: [{ id: 'data', values: data }],
      xField: labelCol,
      yField: valueCol,
      bar: { style: { cornerRadius: [4, 4, 0, 0] } },
      axes: [
        { orient: 'bottom', label: { style: { fill: '#9ca3af', fontSize: 11 } }, tick: { visible: false } },
        { orient: 'left',   label: { style: { fill: '#9ca3af', fontSize: 11 } }, grid: { style: { stroke: 'rgba(255,255,255,0.06)' } } }
      ],
      tooltip: { mark: { content: [{ key: d => d[labelCol], value: d => d[valueCol] }] } },
      ...theme,
    }
  }

  if (chartType === 'line') {
    return {
      ...baseStyle,
      type: 'line',
      data: [{ id: 'data', values: data }],
      xField: labelCol,
      yField: valueCol,
      line: { style: { lineWidth: 2.5 } },
      point: { style: { size: 6, fillOpacity: 1 } },
      axes: [
        { orient: 'bottom', label: { style: { fill: '#9ca3af', fontSize: 11 } }, tick: { visible: false } },
        { orient: 'left',   label: { style: { fill: '#9ca3af', fontSize: 11 } }, grid: { style: { stroke: 'rgba(255,255,255,0.06)' } } }
      ],
      ...theme,
    }
  }

  if (chartType === 'area') {
    return {
      ...baseStyle,
      type: 'area',
      data: [{ id: 'data', values: data }],
      xField: labelCol,
      yField: valueCol,
      area: { style: { fillOpacity: 0.2 } },
      line: { style: { lineWidth: 2.5 } },
      point: { style: { size: 5, fillOpacity: 1 } },
      axes: [
        { orient: 'bottom', label: { style: { fill: '#9ca3af', fontSize: 11 } }, tick: { visible: false } },
        { orient: 'left',   label: { style: { fill: '#9ca3af', fontSize: 11 } }, grid: { style: { stroke: 'rgba(255,255,255,0.06)' } } }
      ],
      ...theme,
    }
  }

  if (chartType === 'pie' || chartType === 'donut') {
    return {
      ...baseStyle,
      type: 'pie',
      data: [{ id: 'data', values: data }],
      categoryField: labelCol,
      valueField: valueCol,
      pie: {
        style: { stroke: 'rgba(0,0,0,0.3)', lineWidth: 1.5 },
        innerRadius: chartType === 'donut' ? 0.5 : 0,
        outerRadius: 0.85,
      },
      label: {
        visible: true,
        style: { fill: '#d1d5db', fontSize: 11 },
        formatMethod: (val, datum) => `${datum[labelCol]}: ${numVal(datum[valueCol]).toLocaleString()}`,
      },
      legends: {
        visible: true,
        orient: 'right',
        item: { label: { style: { fill: '#9ca3af', fontSize: 11 } } },
      },
      ...theme,
    }
  }

  if (chartType === 'scatter') {
    const xF = isNumeric(data[0]?.[labelCol]) ? labelCol : valueCol
    const yF = valueCol
    return {
      ...baseStyle,
      type: 'scatter',
      data: [{ id: 'data', values: data }],
      xField: xF,
      yField: yF,
      point: { style: { size: 8, fillOpacity: 0.8, stroke: 'transparent' } },
      axes: [
        { orient: 'bottom', label: { style: { fill: '#9ca3af', fontSize: 11 } }, grid: { style: { stroke: 'rgba(255,255,255,0.06)' } } },
        { orient: 'left',   label: { style: { fill: '#9ca3af', fontSize: 11 } }, grid: { style: { stroke: 'rgba(255,255,255,0.06)' } } }
      ],
      ...theme,
    }
  }

  if (chartType === 'radar') {
    return {
      ...baseStyle,
      type: 'radar',
      data: [{ id: 'data', values: data }],
      categoryField: labelCol,
      valueField: valueCol,
      area: { visible: true, style: { fillOpacity: 0.15 } },
      line: { style: { lineWidth: 2 } },
      point: { visible: true, style: { size: 5 } },
      axes: [
        { orient: 'radius', label: { style: { fill: '#9ca3af', fontSize: 10 } }, grid: { style: { stroke: 'rgba(255,255,255,0.08)' } } },
        { orient: 'angle',  label: { style: { fill: '#9ca3af', fontSize: 11 } }, grid: { style: { stroke: 'rgba(255,255,255,0.08)' } } }
      ],
      ...theme,
    }
  }

  if (chartType === 'heatmap') {
    const yF = value2Col || (columns => columns.find(c => c !== labelCol && c !== valueCol)) || labelCol
    const heatValues = data.map(d => ({
      x: String(d[labelCol]),
      y: String(d[yF] ?? d[labelCol]),
      value: numVal(d[valueCol]),
    }))
    return {
      ...baseStyle,
      type: 'heatmap',
      data: [{ id: 'data', values: heatValues }],
      xField: 'x',
      yField: 'y',
      valueField: 'value',
      color: { range: ['#1e1b4b', '#6366f1', '#a5b4fc'] },
      axes: [
        { orient: 'bottom', label: { style: { fill: '#9ca3af', fontSize: 11 } } },
        { orient: 'left',   label: { style: { fill: '#9ca3af', fontSize: 11 } } }
      ],
      ...theme,
    }
  }

  return null
}

function VChartCanvas({ spec }) {
  const wrapRef = useRef(null)
  const containerRef = useRef(null)
  const chartRef = useRef(null)
  const [dims, setDims] = useState(null)

  // Measure wrapper once it has real pixel dimensions
  useEffect(() => {
    if (!wrapRef.current) return
    const ro = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect
      if (width > 0 && height > 0) setDims({ width, height })
    })
    ro.observe(wrapRef.current)
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    if (!containerRef.current || !spec || !dims) return
    if (chartRef.current) {
      chartRef.current.release()
      chartRef.current = null
    }
    const fullSpec = { ...spec, width: dims.width, height: dims.height }
    const chart = new VChart(fullSpec, { dom: containerRef.current })
    chart.renderAsync()
    chartRef.current = chart
    return () => {
      chart.release()
      chartRef.current = null
    }
  }, [spec, dims])

  return (
    <div ref={wrapRef} style={{ width: '100%', height: '100%' }}>
      <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
    </div>
  )
}

export default function DataVisualizer({ columns, rows }) {
  // rows are already objects keyed by column name
  const data = useMemo(() => rows, [rows])

  const numericCols = useMemo(() => columns.filter(c => data.some(r => isNumeric(r[c]))), [columns, data])
  const labelCols = columns

  // Prefer a name/label column; fall back to first non-numeric
  const defaultLabel = columns.find(c => /name|label|title|desc/i.test(c) && !numericCols.includes(c))
    || columns.find(c => !numericCols.includes(c))
    || columns[0] || ''
  const defaultValue = numericCols[0] || columns[1] || ''

  const [chartType, setChartType] = useState('bar')
  const [labelCol, setLabelCol]   = useState(defaultLabel)
  const [valueCol, setValueCol]   = useState(defaultValue)

  const spec = useMemo(() => {
    if (!labelCol || !valueCol || data.length === 0) return null
    const sliced = data.slice(0, 50)
    return buildSpec(chartType, sliced, labelCol, valueCol, columns)
  }, [chartType, labelCol, valueCol, data, columns])

  if (!columns.length || !rows.length) {
    return <div className="chart-empty">No data to visualize</div>
  }

  return (
    <div className="data-visualizer">
      <div className="viz-toolbar">
        <div className="viz-type-tabs">
          {CHART_TYPES.map(ct => (
            <button
              key={ct.id}
              className={`viz-type-btn ${chartType === ct.id ? 'active' : ''}`}
              onClick={() => setChartType(ct.id)}
            >
              {ct.label}
            </button>
          ))}
        </div>
        <div className="viz-field-selects">
          <label className="viz-label">
            <span>Label</span>
            <select value={labelCol} onChange={e => setLabelCol(e.target.value)} className="viz-select">
              {labelCols.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
          <label className="viz-label">
            <span>Value</span>
            <select value={valueCol} onChange={e => setValueCol(e.target.value)} className="viz-select">
              {columns.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
        </div>
      </div>
      <div className="viz-chart-area">
        {spec ? <VChartCanvas spec={spec} /> : <div className="chart-empty">Select label and value columns</div>}
      </div>
    </div>
  )
}
