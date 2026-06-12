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
  const chatVisible = useChatStore(s => s.chatVisible)
  const setChatVisible = useChatStore(s => s.setChatVisible)
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
  const panelStyle = chatVisible
    ? { width }
    : { width: '100vw', left: 0, transition: 'width 0.25s ease, left 0.25s ease' }

  return (
    <div className="data-panel" style={panelStyle}>
      <div className="data-panel-resize-handle" onMouseDown={chatVisible ? onMouseDown : undefined} style={{ cursor: chatVisible ? 'col-resize' : 'default' }} />
      <div className="data-panel-inner">
        <div className="data-panel-header">
          <span className="data-panel-title">{title || 'Query Results'}</span>
          <button
            className="data-panel-close"
            onClick={() => setChatVisible(!chatVisible)}
            title={chatVisible ? 'Expand to full screen' : 'Show chat'}
            style={{ marginRight: 4 }}
          >
            {chatVisible ? (
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polyline points="15 3 21 3 21 9" /><polyline points="9 21 3 21 3 15" />
                <line x1="21" y1="3" x2="14" y2="10" /><line x1="3" y1="21" x2="10" y2="14" />
              </svg>
            ) : (
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polyline points="8 3 3 3 3 8" /><polyline points="21 16 21 21 16 21" />
                <line x1="3" y1="3" x2="10" y2="10" /><line x1="21" y1="21" x2="14" y2="14" />
              </svg>
            )}
          </button>
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
