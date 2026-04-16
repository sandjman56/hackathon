import { useEffect, useRef, useState } from 'react'

const apiBase = import.meta.env.VITE_API_URL ?? ''

export default function EvaluationChunksView({ evaluationId, filename, onBack }) {
  const [chunks, setChunks] = useState([])
  const [page, setPage] = useState(1)
  const [perPage] = useState(25)
  const [totalPages, setTotalPages] = useState(0)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [expanded, setExpanded] = useState(() => new Set())
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  useEffect(() => {
    setLoading(true); setError(null)
    fetch(`${apiBase}/api/evaluations/${evaluationId}/chunks?page=${page}&per_page=${perPage}`)
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(d => {
        if (!mountedRef.current) return
        setChunks(d.chunks || []); setTotalPages(d.total_pages || 0); setTotal(d.total || 0)
      })
      .catch(e => { if (mountedRef.current) setError(e.message) })
      .finally(() => { if (mountedRef.current) setLoading(false) })
  }, [evaluationId, page, perPage])

  const toggle = (id) => {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  return (
    <div style={styles.container}>
      <div style={styles.topBar}>
        <button style={styles.backBtn} onClick={onBack}>&larr; BACK</button>
        <span style={styles.pageTitle}>CHUNKS: {filename}</span>
        <span style={styles.count}>{!loading && !error && `${total} chunks`}</span>
      </div>
      <div style={styles.body}>
        {error && <div style={styles.error}>Error: {error}</div>}
        {loading && <div style={styles.muted}>Loading...</div>}
        {!loading && chunks.length === 0 && <div style={styles.muted}>NO CHUNKS</div>}
        {!loading && chunks.length > 0 && (
          <>
            <table style={styles.table}>
              <thead>
                <tr>
                  <th style={styles.th}>LABEL</th>
                  <th style={styles.th}>BREADCRUMB</th>
                  <th style={styles.th}>PAGES</th>
                  <th style={styles.th}>CONTENT</th>
                </tr>
              </thead>
              <tbody>
                {chunks.map(c => {
                  const isOpen = expanded.has(c.id)
                  const body = isOpen ? c.content : (c.content || '').slice(0, 160) + (c.content?.length > 160 ? '…' : '')
                  return (
                    <tr key={c.id} style={styles.tr}>
                      <td style={styles.tdMono}>{c.chunk_label}</td>
                      <td style={styles.td}>{c.breadcrumb}</td>
                      <td style={styles.tdMono}>{c.page_start === c.page_end ? c.page_start : `${c.page_start}-${c.page_end}`}</td>
                      <td style={styles.td}>
                        <button style={styles.expandBtn} onClick={() => toggle(c.id)}>
                          {isOpen ? '▼' : '▶'}
                        </button>
                        <span style={{ whiteSpace: 'pre-wrap' }}>{body}</span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            {totalPages > 1 && (
              <div style={styles.pager}>
                <button style={styles.pagerBtn} disabled={page <= 1} onClick={() => setPage(p => Math.max(1, p - 1))}>PREV</button>
                <span style={styles.pageLabel}>PAGE {page} / {totalPages}</span>
                <button style={styles.pagerBtn} disabled={page >= totalPages} onClick={() => setPage(p => Math.min(totalPages, p + 1))}>NEXT</button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

const styles = {
  container: { height: '100vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' },
  topBar: {
    display: 'flex', alignItems: 'center', gap: '16px', padding: '12px 24px',
    borderBottom: '1px solid var(--border)', background: 'var(--bg-secondary)', flexShrink: 0,
  },
  backBtn: {
    fontFamily: 'var(--font-mono)', fontSize: '11px', letterSpacing: '1px',
    color: 'var(--text-secondary)', background: 'transparent',
    border: '1px solid var(--border)', borderRadius: '4px', padding: '6px 12px', cursor: 'pointer',
  },
  pageTitle: {
    fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 600,
    color: 'var(--green-primary)', letterSpacing: '2px',
  },
  count: { fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)' },
  body: { flex: 1, padding: '24px', overflowY: 'auto' },
  error: { fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--red-alert)', padding: '8px 0' },
  muted: { fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)', fontStyle: 'italic', padding: '8px 0' },
  table: { width: '100%', borderCollapse: 'collapse' },
  th: {
    fontFamily: 'var(--font-mono)', fontSize: '9px', letterSpacing: '1px',
    color: 'var(--text-muted)', textAlign: 'left', padding: '8px 12px',
    borderBottom: '1px solid var(--border)',
  },
  tr: { borderBottom: '1px solid var(--border)', verticalAlign: 'top' },
  td: { fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-secondary)', padding: '8px 12px' },
  tdMono: { fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--green-primary)', padding: '8px 12px' },
  expandBtn: {
    background: 'transparent', border: 'none', color: 'var(--green-primary)',
    cursor: 'pointer', marginRight: '6px', fontFamily: 'var(--font-mono)',
  },
  pager: {
    display: 'flex', alignItems: 'center', gap: '12px', marginTop: '16px',
    justifyContent: 'center',
  },
  pagerBtn: {
    fontFamily: 'var(--font-mono)', fontSize: '10px', letterSpacing: '1px',
    color: 'var(--green-primary)', background: 'transparent',
    border: '1px solid var(--green-primary)', borderRadius: '3px',
    padding: '4px 10px', cursor: 'pointer',
  },
  pageLabel: { fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)' },
}
