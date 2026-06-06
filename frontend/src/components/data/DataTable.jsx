import { useState } from 'react'

const PAGE_SIZE = 50

export default function DataTable({ columns, rows, rowCount }) {
  const [page, setPage] = useState(0)
  const [sortCol, setSortCol] = useState(null)
  const [sortDir, setSortDir] = useState('asc')
  const [search, setSearch] = useState('')

  const filtered = search
    ? rows.filter(r => columns.some(c => String(r[c] ?? '').toLowerCase().includes(search.toLowerCase())))
    : rows

  const sorted = sortCol == null ? filtered : [...filtered].sort((a, b) => {
    const av = a[sortCol] ?? '', bv = b[sortCol] ?? ''
    const cmp = String(av).localeCompare(String(bv), undefined, { numeric: true })
    return sortDir === 'asc' ? cmp : -cmp
  })

  const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE))
  const pageRows = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)

  function toggleSort(col) {
    if (sortCol === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortCol(col); setSortDir('asc') }
    setPage(0)
  }

  return (
    <div className="data-table-wrap">
      <div className="data-table-toolbar">
        <span className="data-row-count">{rowCount ?? sorted.length} rows{search ? ` (filtered)` : ''}</span>
        <input
          className="data-table-search"
          placeholder="Search…"
          value={search}
          onChange={e => { setSearch(e.target.value); setPage(0) }}
        />
      </div>
      <div className="data-table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              {columns.map(col => (
                <th key={col} onClick={() => toggleSort(col)} className="data-th">
                  {col}
                  {sortCol === col && <span className="sort-icon">{sortDir === 'asc' ? ' ↑' : ' ↓'}</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pageRows.map((row, i) => (
              <tr key={i} className="data-tr">
                {columns.map(col => (
                  <td key={col} className="data-td">{row[col] == null ? '' : String(row[col])}</td>
                ))}
              </tr>
            ))}
            {pageRows.length === 0 && (
              <tr><td colSpan={columns.length} className="data-td" style={{ textAlign: 'center', color: 'var(--text-muted)' }}>No records</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {totalPages > 1 && (
        <div className="data-table-footer">
          <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0} className="page-btn">‹</button>
          <span className="page-label">{page + 1} / {totalPages}</span>
          <button onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))} disabled={page === totalPages - 1} className="page-btn">›</button>
        </div>
      )}
    </div>
  )
}
