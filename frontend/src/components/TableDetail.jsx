import { useEffect, useState, useCallback } from 'react'
import ChunksView from './ChunksView'

const apiBase = import.meta.env.VITE_API_URL ?? ''

export default function TableDetail({ tableName, onBack }) {
  if (tableName === 'regulatory_chunks') {
    return <ChunksView onBack={onBack} />
  }

  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [page, setPage] = useState(1)
  const [confirmClear, setConfirmClear] = useState(false)
  const [clearing, setClearing] = useState(false)

  const fetchPage = useCallback(async (p) => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(
        `${apiBase}/api/db/tables/${encodeURIComponent(tableName)}?page=${p}&per_page=25`
      )
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setData(json)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [tableName])

  useEffect(() => {
    fetchPage(page)
  }, [page, fetchPage])

  // Auto-dismiss confirm after 3 seconds
  useEffect(() => {
    if (!confirmClear) return
    const timer = setTimeout(() => setConfirmClear(false), 3000)
    return () => clearTimeout(timer)
  }, [confirmClear])

  const handleClear = async () => {
    if (!confirmClear) {
      setConfirmClear(true)
      return
    }
    setClearing(true)
    setConfirmClear(false)
    try {
      const res = await fetch(
        `${apiBase}/api/db/tables/${encodeURIComponent(tableName)}/rows`,
        { method: 'DELETE' }
      )
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
    } catch (e) {
      setError(e.message)
    } finally {
      setClearing(false)
      setPage(1)
      fetchPage(1)
    }
  }

  const truncateCell = (val) => {
    if (val == null) return 'NULL'
    const s = String(val)
    return s.length > 100 ? s.slice(0, 97) + '...' : s
  }

  return (
    <div style={styles.container}>
      <div style={styles.topBar}>
        <button style={styles.backBtn} onClick={onBack}>
          &larr; BACK
        </button>
        <span style={styles.pageTitle}>{tableName}</span>
        {data && (
          <span style={styles.rowBadge}>
            {data.total_rows} rows
          </span>
        )}
        <div style={{ flex: 1 }} />
        <button
          style={confirmClear ? styles.clearBtnConfirm : styles.clearBtn}
          onClick={handleClear}
          disabled={clearing}
        >
          {clearing
            ? 'CLEARING...'
            : confirmClear
              ? `DELETE ALL ${data?.total_rows ?? 0} ROWS?`
              : 'CLEAR TABLE'}
        </button>
      </div>

      <div style={styles.body}>
        {loading && !data && (
          <div style={styles.muted}>Loading...</div>
        )}
        {error && (
          <div style={styles.error}>Error: {error}</div>
        )}
        {data && (
          <>
            <div style={styles.tableWrap}>
              <table style={styles.table}>
                <thead>
                  <tr>
                    {data.columns.map((col) => (
                      <th key={col.name} style={styles.th}>
                        <div style={styles.colName}>{col.name}</div>
                        <div style={styles.colType}>{col.type}</div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.rows.length === 0 ? (
                    <tr>
                      <td
                        colSpan={data.columns.length}
                        style={styles.emptyCell}
                      >
                        No rows
                      </td>
                    </tr>
                  ) : (
                    data.rows.map((row, i) => (
                      <tr
                        key={i}
                        style={i % 2 === 0 ? styles.rowEven : styles.rowOdd}
                      >
                        {row.map((cell, j) => (
                          <td key={j} style={styles.td}>
                            {truncateCell(cell)}
                          </td>
                        ))}
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            {data.total_pages > 1 && (
              <div style={styles.pagination}>
                <button
                  style={styles.pageBtn}
                  disabled={page <= 1}
                  onClick={() => setPage((p) => p - 1)}
                >
                  &larr; PREV
                </button>
                <span style={styles.pageInfo}>
                  Page {data.page} of {data.total_pages}
                </span>
                <button
                  style={styles.pageBtn}
                  disabled={page >= data.total_pages}
                  onClick={() => setPage((p) => p + 1)}
                >
                  NEXT &rarr;
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

const styles = {
  container: {
    height: '100vh',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
  },
  topBar: {
    display: 'flex',
    alignItems: 'center',
    gap: '16px',
    padding: '12px 24px',
    borderBottom: '1px solid var(--border)',
    background: 'var(--bg-secondary)',
    flexShrink: 0,
  },
  backBtn: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    letterSpacing: '1px',
    color: 'var(--text-secondary)',
    background: 'transparent',
    border: '1px solid var(--border)',
    borderRadius: '4px',
    padding: '6px 12px',
    cursor: 'pointer',
  },
  pageTitle: {
    fontFamily: 'var(--font-mono)',
    fontSize: '14px',
    fontWeight: 600,
    color: 'var(--green-primary)',
    letterSpacing: '2px',
  },
  rowBadge: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--text-muted)',
    padding: '3px 8px',
    border: '1px solid var(--border)',
    borderRadius: '4px',
  },
  clearBtn: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    letterSpacing: '1px',
    color: 'var(--red-alert)',
    background: 'transparent',
    border: '1px solid var(--border)',
    borderRadius: '4px',
    padding: '6px 14px',
    cursor: 'pointer',
    transition: 'border-color 0.15s',
  },
  clearBtnConfirm: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    letterSpacing: '1px',
    color: 'var(--red-alert)',
    background: 'transparent',
    border: '1px solid var(--red-alert)',
    borderRadius: '4px',
    padding: '6px 14px',
    cursor: 'pointer',
    boxShadow: '0 0 10px rgba(255, 68, 68, 0.2)',
  },
  body: {
    flex: 1,
    padding: '20px 24px',
    overflowY: 'auto',
  },
  tableWrap: {
    overflowX: 'auto',
    border: '1px solid var(--border)',
    borderRadius: '6px',
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse',
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
  },
  th: {
    textAlign: 'left',
    padding: '10px 14px',
    background: 'var(--bg-secondary)',
    borderBottom: '1px solid var(--border)',
    position: 'sticky',
    top: 0,
    whiteSpace: 'nowrap',
  },
  colName: {
    color: 'var(--text-primary)',
    fontWeight: 600,
    fontSize: '11px',
  },
  colType: {
    color: 'var(--text-muted)',
    fontSize: '9px',
    marginTop: '2px',
  },
  td: {
    padding: '8px 14px',
    color: 'var(--text-secondary)',
    borderBottom: '1px solid var(--border)',
    whiteSpace: 'nowrap',
    maxWidth: '300px',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  },
  rowEven: {
    background: 'var(--bg-card)',
  },
  rowOdd: {
    background: 'var(--bg-primary)',
  },
  emptyCell: {
    padding: '20px 14px',
    color: 'var(--text-muted)',
    fontStyle: 'italic',
    textAlign: 'center',
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
  },
  pagination: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '16px',
    padding: '16px 0',
  },
  pageBtn: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    letterSpacing: '1px',
    color: 'var(--text-secondary)',
    background: 'transparent',
    border: '1px solid var(--border)',
    borderRadius: '4px',
    padding: '6px 12px',
    cursor: 'pointer',
  },
  pageInfo: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--text-muted)',
  },
  muted: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    color: 'var(--text-muted)',
    fontStyle: 'italic',
    padding: '8px 0',
  },
  error: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    color: 'var(--red-alert)',
    padding: '8px 0',
  },
}
