import { useRef, useEffect, useState } from 'react'
import useChatStore from '../../stores/chat-store.js'
import DataTable from './DataTable.jsx'
import DataVisualizer from './DataVisualizer.jsx'

const MIN_WIDTH = 320
const MAX_WIDTH = 900
const DEFAULT_WIDTH = 460

export default function DataPanel() {
  const dataPanel = useChatStore(s => s.dataPanel)
  const setDataPanel = useChatStore(s => s.setDataPanel)
  const [tab, setTab] = useState('table')
  const [width, setWidth] = useState(DEFAULT_WIDTH)
  const dragging = useRef(false)
  const startX = useRef(0)
  const startWidth = useRef(DEFAULT_WIDTH)

  // Reset tab to 'table' when new data arrives
  useEffect(() => {
    if (dataPanel) setTab('table')
  }, [dataPanel?.rows])

  function onMouseDown(e) {
    dragging.current = true
    startX.current = e.clientX
    startWidth.current = width
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }

  useEffect(() => {
    function onMouseMove(e) {
      if (!dragging.current) return
      const delta = startX.current - e.clientX
      const next = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, startWidth.current + delta))
      setWidth(next)
    }
    function onMouseUp() {
      if (!dragging.current) return
      dragging.current = false
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
    return () => {
      document.removeEventListener('mousemove', onMouseMove)
      document.removeEventListener('mouseup', onMouseUp)
    }
  }, [])

  if (!dataPanel) return null

  const { rows, title } = dataPanel
  const hasData = rows?.columns?.length > 0 && rows?.rows?.length > 0

  return (
    <div className="data-panel" style={{ width }}>
      <div className="data-panel-resize-handle" onMouseDown={onMouseDown} />
      <div className="data-panel-inner">
        <div className="data-panel-header">
          <span className="data-panel-title">{title || 'Query Results'}</span>
          <button className="data-panel-close" onClick={() => setDataPanel(null)} title="Close">✕</button>
        </div>
        {hasData && (
          <div className="data-panel-tabs">
            <button className={`data-tab ${tab === 'table' ? 'active' : ''}`} onClick={() => setTab('table')}>Table</button>
            <button className={`data-tab ${tab === 'chart' ? 'active' : ''}`} onClick={() => setTab('chart')}>Chart</button>
          </div>
        )}
        <div className="data-panel-body">
          {!hasData && <div className="data-panel-empty">No data available</div>}
          {hasData && tab === 'table' && (
            <DataTable columns={rows.columns} rows={rows.rows} rowCount={rows.row_count} />
          )}
          {hasData && tab === 'chart' && (
            <DataVisualizer columns={rows.columns} rows={rows.rows} />
          )}
        </div>
      </div>
    </div>
  )
}
