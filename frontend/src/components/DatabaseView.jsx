import { useEffect, useState } from 'react'
import TableDetail from './TableDetail.jsx'
import EcfrIngestModal from './EcfrIngestModal.jsx'

const apiBase = import.meta.env.VITE_API_URL ?? ''

export default function DatabaseView({ onBack }) {
  const [tables, setTables] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedTable, setSelectedTable] = useState(null)
  const [ingestOpen, setIngestOpen] = useState(false)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const res = await fetch(`${apiBase}/api/db/tables`)
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data = await res.json()
        if (!cancelled) setTables(data)
      } catch (e) {
        if (!cancelled) setError(e.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [])

  if (selectedTable) {
    return (
      <TableDetail
        key={selectedTable}
        tableName={selectedTable}
        onBack={() => setSelectedTable(null)}
      />
    )
  }

  return (
    <div style={styles.container}>
      <div style={styles.topBar}>
        <button style={styles.backBtn} onClick={onBack}>
          &larr; BACK
        </button>
        <span style={styles.pageTitle}>DATABASE</span>
        <span style={styles.tableCount}>
          {!loading && !error && `${tables.length} tables`}
        </span>
        <div style={{ flex: 1 }} />
        <button style={styles.ingestBtn} onClick={() => setIngestOpen(true)}>
          INGEST eCFR
        </button>
      </div>

      {ingestOpen && <EcfrIngestModal onClose={() => setIngestOpen(false)} />}

      <div style={styles.body}>
        {loading && <div style={styles.muted}>Loading tables...</div>}
        {error && (
          <div style={styles.error}>
            Error: {error}
            <button style={styles.retryBtn} onClick={() => { setError(null); setLoading(true); window.location.reload() }}>
              RETRY
            </button>
          </div>
        )}
        {!loading && !error && tables.length === 0 && (
          <div style={styles.muted}>No tables found in the database.</div>
        )}

        <div style={styles.grid}>
          {tables.map((t) => (
            <button
              key={t.name}
              style={styles.card}
              onClick={() => setSelectedTable(t.name)}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = 'var(--green-primary)'
                e.currentTarget.style.boxShadow = '0 0 20px rgba(0, 255, 135, 0.15)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = 'var(--border)'
                e.currentTarget.style.boxShadow = 'none'
              }}
            >
              <div style={styles.cardName}>{t.name}</div>
              <div style={styles.cardMeta}>
                <span>{t.row_count} rows</span>
                <span style={styles.metaDot}>&middot;</span>
                <span>{t.column_count} columns</span>
              </div>
            </button>
          ))}
        </div>
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
  ingestBtn: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    letterSpacing: '2px',
    color: 'var(--green-primary)',
    background: 'var(--green-dim)',
    border: '1px solid var(--green-primary)',
    borderRadius: '4px',
    padding: '6px 14px',
    cursor: 'pointer',
  },
  pageTitle: {
    fontFamily: 'var(--font-mono)',
    fontSize: '14px',
    fontWeight: 600,
    color: 'var(--green-primary)',
    letterSpacing: '3px',
  },
  tableCount: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    color: 'var(--text-muted)',
  },
  body: {
    flex: 1,
    padding: '24px',
    overflowY: 'auto',
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
    gap: '16px',
  },
  card: {
    background: 'var(--bg-card)',
    border: '1px solid var(--border)',
    borderRadius: '8px',
    padding: '20px',
    cursor: 'pointer',
    textAlign: 'left',
    transition: 'border-color 0.15s, box-shadow 0.15s',
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
  },
  cardName: {
    fontFamily: 'var(--font-mono)',
    fontSize: '13px',
    fontWeight: 600,
    color: 'var(--green-primary)',
    wordBreak: 'break-all',
  },
  cardMeta: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--text-muted)',
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
  },
  metaDot: {
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
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
  },
  retryBtn: {
    fontFamily: 'var(--font-mono)',
    fontSize: '9px',
    letterSpacing: '1px',
    color: 'var(--text-secondary)',
    background: 'transparent',
    border: '1px solid var(--border)',
    borderRadius: '3px',
    padding: '4px 8px',
    cursor: 'pointer',
  },
}
