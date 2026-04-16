import { useEffect, useRef, useState } from 'react'

const apiBase = import.meta.env.VITE_API_URL ?? ''
const PER_PAGE = 25

export default function EvaluationChunksView({ evaluationId, filename, onBack }) {
  const [chunks, setChunks] = useState([])
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(0)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [expanded, setExpanded] = useState(() => new Set())
  const [mode, setMode] = useState('chunks')
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  useEffect(() => {
    setLoading(true); setError(null)
    fetch(`${apiBase}/api/evaluations/${evaluationId}/chunks?page=${page}&per_page=${PER_PAGE}`)
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(d => {
        if (!mountedRef.current) return
        setChunks(d.chunks || []); setTotalPages(d.total_pages || 0); setTotal(d.total || 0)
      })
      .catch(e => { if (mountedRef.current) setError(e.message) })
      .finally(() => { if (mountedRef.current) setLoading(false) })
  }, [evaluationId, page])

  const toggle = (id) => {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  const switchMode = (m) => {
    setMode(m)
    setExpanded(new Set())
  }

  const pageRange = (c) =>
    c.page_start === c.page_end ? `p.${c.page_start}` : `p.${c.page_start}–${c.page_end}`

  return (
    <div style={styles.container}>
      <div style={styles.topBar}>
        <button style={styles.backBtn} onClick={onBack}>&larr; BACK</button>
        <span style={styles.pageTitle}>{filename}</span>
        <button
          style={mode === 'chunks' ? styles.modeActive : styles.modeBtn}
          onClick={() => switchMode('chunks')}
        >
          CHUNKS
        </button>
        <button
          style={mode === 'table' ? styles.modeActive : styles.modeBtn}
          onClick={() => switchMode('table')}
        >
          FULL TABLE
        </button>
        <span style={styles.count}>{!loading && !error && `${total} chunks`}</span>
      </div>

      <div style={styles.body}>
        {error && <div style={styles.error}>Error: {error}</div>}
        {loading && <div style={styles.muted}>Loading...</div>}
        {!loading && chunks.length === 0 && <div style={styles.muted}>NO CHUNKS</div>}

        {!loading && chunks.length > 0 && mode === 'chunks' && (
          <>
            {chunks.map(c => {
              const isOpen = expanded.has(c.id)
              return (
                <div key={c.id} style={styles.chunkRow}>
                  <div style={styles.chunkHeader}>
                    <div style={styles.chunkInfo}>
                      <span style={styles.chunkLabel}>{c.chunk_label}</span>
                      {c.breadcrumb && (
                        <span style={styles.chunkBreadcrumb}> — {c.breadcrumb}</span>
                      )}
                      <span style={styles.chunkPages}> • {pageRange(c)}</span>
                    </div>
                    <button
                      style={isOpen ? styles.previewBtnActive : styles.previewBtn}
                      onClick={() => toggle(c.id)}
                    >
                      {isOpen ? 'COLLAPSE' : 'PREVIEW'}
                    </button>
                  </div>
                  {isOpen && (
                    <pre style={styles.chunkContent}>{c.content}</pre>
                  )}
                </div>
              )
            })}
          </>
        )}

        {!loading && chunks.length > 0 && mode === 'table' && (
          <div style={styles.tableWrap}>
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
                      <td style={styles.tdMono}>
                        {c.page_start === c.page_end ? c.page_start : `${c.page_start}-${c.page_end}`}
                      </td>
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
          </div>
        )}

        {!loading && chunks.length > 0 && totalPages > 1 && (
          <div style={styles.pager}>
            <button style={styles.pagerBtn} disabled={page <= 1} onClick={() => setPage(p => Math.max(1, p - 1))}>
              &larr; PREV
            </button>
            {Array.from({ length: totalPages }, (_, i) => i + 1)
              .filter(p => p === 1 || p === totalPages || Math.abs(p - page) <= 1)
              .reduce((acc, p, idx, arr) => {
                if (idx > 0 && p - arr[idx - 1] > 1) acc.push('...')
                acc.push(p)
                return acc
              }, [])
              .map((item, idx) =>
                item === '...'
                  ? <span key={`gap-${idx}`} style={styles.pageLabel}>…</span>
                  : (
                    <button
                      key={item}
                      style={item === page ? styles.pageNumActive : styles.pageNum}
                      onClick={() => setPage(item)}
                    >
                      {item}
                    </button>
                  )
              )}
            <button style={styles.pagerBtn} disabled={page >= totalPages} onClick={() => setPage(p => Math.min(totalPages, p + 1))}>
              NEXT &rarr;
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

const btnBase = {
  fontFamily: 'var(--font-mono)',
  fontSize: '10px',
  letterSpacing: '1px',
  background: 'transparent',
  borderRadius: '3px',
  padding: '5px 12px',
  cursor: 'pointer',
}

const styles = {
  container: { height: '100vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' },
  topBar: {
    display: 'flex', alignItems: 'center', gap: '12px', padding: '12px 24px',
    borderBottom: '1px solid var(--border)', background: 'var(--bg-secondary)', flexShrink: 0,
  },
  backBtn: {
    ...btnBase, fontSize: '11px',
    color: 'var(--text-secondary)', border: '1px solid var(--border)', borderRadius: '4px',
    padding: '6px 12px',
  },
  pageTitle: {
    fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 600,
    color: 'var(--green-primary)', letterSpacing: '2px',
  },
  modeBtn: {
    ...btnBase,
    color: 'var(--text-muted)', border: '1px solid var(--border)',
  },
  modeActive: {
    ...btnBase,
    color: 'var(--green-primary)', border: '1px solid var(--green-primary)',
    background: 'var(--green-dim)',
  },
  count: { fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)', marginLeft: 'auto' },
  body: { flex: 1, padding: '24px', overflowY: 'auto' },
  error: { fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--red-alert)', padding: '8px 0' },
  muted: { fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)', fontStyle: 'italic', padding: '8px 0' },

  // -- Chunks mode --
  chunkRow: {
    borderTop: '1px solid var(--border)', padding: '10px 0',
  },
  chunkHeader: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px',
  },
  chunkInfo: {
    fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-secondary)',
    flex: 1, minWidth: 0,
  },
  chunkLabel: { color: 'var(--green-primary)', fontWeight: 600 },
  chunkBreadcrumb: { color: 'var(--text-muted)', opacity: 0.8 },
  chunkPages: { color: 'var(--text-muted)', opacity: 0.7, fontSize: '11px' },
  previewBtn: {
    ...btnBase,
    color: 'var(--green-primary)', border: '1px solid var(--green-primary)',
    flexShrink: 0,
  },
  previewBtnActive: {
    ...btnBase,
    color: 'var(--bg-primary)', background: 'var(--green-primary)',
    border: '1px solid var(--green-primary)', flexShrink: 0,
  },
  chunkContent: {
    whiteSpace: 'pre-wrap', fontFamily: 'var(--font-mono)', fontSize: '11px',
    color: 'var(--text-secondary)', marginTop: '8px', padding: '10px 12px',
    background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: '4px',
    maxHeight: '400px', overflowY: 'auto',
  },

  // -- Table mode --
  tableWrap: { overflowX: 'auto', border: '1px solid var(--border)', borderRadius: '6px' },
  table: { width: '100%', borderCollapse: 'collapse' },
  th: {
    fontFamily: 'var(--font-mono)', fontSize: '9px', letterSpacing: '1px',
    color: 'var(--text-muted)', textAlign: 'left', padding: '8px 12px',
    borderBottom: '1px solid var(--border)', background: 'var(--bg-secondary)',
    position: 'sticky', top: 0,
  },
  tr: { borderBottom: '1px solid var(--border)', verticalAlign: 'top' },
  td: { fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-secondary)', padding: '8px 12px' },
  tdMono: { fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--green-primary)', padding: '8px 12px' },
  expandBtn: {
    background: 'transparent', border: 'none', color: 'var(--green-primary)',
    cursor: 'pointer', marginRight: '6px', fontFamily: 'var(--font-mono)',
  },

  // -- Pagination --
  pager: {
    display: 'flex', alignItems: 'center', gap: '8px', marginTop: '16px',
    justifyContent: 'center',
  },
  pagerBtn: {
    ...btnBase,
    color: 'var(--green-primary)', border: '1px solid var(--green-primary)',
  },
  pageNum: {
    ...btnBase,
    color: 'var(--text-muted)', border: '1px solid var(--border)',
    minWidth: '28px', textAlign: 'center',
  },
  pageNumActive: {
    ...btnBase,
    color: 'var(--green-primary)', border: '1px solid var(--green-primary)',
    background: 'var(--green-dim)', minWidth: '28px', textAlign: 'center',
  },
  pageLabel: { fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)' },
}
