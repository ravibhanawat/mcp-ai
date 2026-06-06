import { useState } from 'react'

const PAGE_SIZE = 50

export default function DataTable({ columns, rows, rowCount }) {
  const [page, setPage] = useState(0)
  const [sortCol, setSortCol] = useState(null)
  const [sortDir, setSortDir] = useState('asc')

  const sorted = sortCol == null ? rows : [...rows].sort((a, b) => {
    const idx = columns.indexOf(sortCol)
    const av = a[idx], bv = b[idx]
    if (av == null) return 1; if (bv == null) return -1
    const cmp = String(av).localeCompare(String(bv), undefined, { numeric: true })
    return sortDir === 'asc' ? cmp : -cmp
  })

  const pageRows = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
  const totalPages = Math.ceil(sorted.length / PAGE_SIZE)

  function toggleSort(col) {
    if (sortCol === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortCol(col); setSortDir('asc') }
  }

  return (
    <div className="data-table-wrap">
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
                {row.map((cell, j) => (
                  <td key={j} className="data-td">{cell == null ? '' : String(cell)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {totalPages > 1 && (
        <div className="data-table-footer">
          <span className="data-row-count">{rowCount ?? sorted.length} rows</span>
          <div className="data-pagination">
            <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0} className="page-btn">‹</button>
            <span className="page-label">{page + 1} / {totalPages}</span>
            <button onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))} disabled={page === totalPages - 1} className="page-btn">›</button>
          </div>
        </div>
      )}
      {totalPages <= 1 && (
        <div className="data-table-footer">
          <span className="data-row-count">{rowCount ?? sorted.length} rows</span>
        </div>
      )}
    </div>
  )
}
