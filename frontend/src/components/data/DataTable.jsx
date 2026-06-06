import { useState, useRef } from 'react'
import { Virtualizer } from 'virtua'

export default function DataTable({ columns, rows, rowCount }) {
  const scrollRef = useRef(null)
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

  function toggleSort(col) {
    if (sortCol === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortCol(col); setSortDir('asc') }
  }

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
          <Virtualizer as="tbody" scrollRef={scrollRef}>
            {sorted.length === 0
              ? [<tr key="empty"><td colSpan={columns.length} className="data-td data-td-empty">No records</td></tr>]
              : sorted.map((row, i) => (
                <tr key={i} className="data-tr">
                  {columns.map(col => (
                    <td key={col} className="data-td">{row[col] == null ? '' : String(row[col])}</td>
                  ))}
                </tr>
              ))
            }
          </Virtualizer>
        </table>
      </div>
    </div>
  )
}
