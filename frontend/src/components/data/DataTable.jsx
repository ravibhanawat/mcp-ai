import { useState, useRef } from 'react'

const PAGE_SIZE = 100

export default function DataTable({ columns, rows, rowCount }) {
  const scrollRef = useRef(null)
  const [sortCol, setSortCol] = useState(null)
  const [sortDir, setSortDir] = useState('asc')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(0)

  const filtered = search
    ? rows.filter(r => columns.some(c => String(r[c] ?? '').toLowerCase().includes(search.toLowerCase())))
    : rows

  const sorted = sortCol == null ? filtered : [...filtered].sort((a, b) => {
    const av = a[sortCol] ?? '', bv = b[sortCol] ?? ''
    const cmp = String(av).localeCompare(String(bv), undefined, { numeric: true })
    return sortDir === 'asc' ? cmp : -cmp
  })

  function toggleSort(col) {
    if (sortCol === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortCol(col); setSortDir('asc') }
    setPage(0)
  }

  const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE))
  const pageRows = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)

  return (
    <div className="data-table-wrap">
      <div className="data-table-toolbar">
        <span className="data-row-count">
          {sorted.length !== (rowCount ?? rows.length)
            ? `${sorted.length} / ${rowCount ?? rows.length} rows`
            : `${rowCount ?? rows.length} rows`}
        </span>
        <input
          className="data-table-search"
          placeholder="Search…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
      </div>

      <div ref={scrollRef} className="data-table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              {columns.map(col => (
                <th key={col} onClick={() => toggleSort(col)} className="data-th">
                  {col}
                  {sortCol === col ? (sortDir === 'asc' ? ' ↑' : ' ↓') : ''}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pageRows.length === 0
              ? <tr key="empty"><td colSpan={columns.length} className="data-td data-td-empty">No records</td></tr>
              : pageRows.map((row, i) => (
                <tr key={page * PAGE_SIZE + i} className="data-tr">
                  {columns.map(col => (
                    <td key={col} className="data-td">{row[col] == null ? '' : String(row[col])}</td>
                  ))}
                </tr>
              ))
            }
          </tbody>
        </table>
      </div>
      {totalPages > 1 && (
        <div className="data-table-pagination">
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
