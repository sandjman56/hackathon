import { useEffect, useState } from 'react'

const apiBase = import.meta.env.VITE_API_URL ?? ''

function formatBytes(n) {
  if (n == null) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(2)} MB`
}

export default function SourcesModal({ onClose }) {
  const [sources, setSources] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)
  const [busy, setBusy]       = useState(null)   // filename currently ingesting
  const [results, setResults] = useState({})     // filename -> result/error

  const fetchSources = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${apiBase}/api/regulations/sources`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setSources(data.sources || [])
    } catch (e) {
      setError(e.message || 'Failed to load sources')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchSources() }, [])

  // Close on Escape
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const ingest = async (filename) => {
    setBusy(filename)
    setResults((r) => ({ ...r, [filename]: { status: 'running' } }))
    try {
      const res = await fetch(`${apiBase}/api/regulations/ingest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename, is_current: false }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
      setResults((r) => ({ ...r, [filename]: { status: 'done', data } }))
      // Refresh counts after ingestion completes.
      fetchSources()
    } catch (e) {
      setResults((r) => ({
        ...r, [filename]: { status: 'error', error: e.message },
      }))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div style={styles.backdrop} onClick={onClose}>
      <div style={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div style={styles.header}>
          <span style={styles.title}>REGULATORY SOURCES</span>
          <button style={styles.closeBtn} onClick={onClose} title="Close">×</button>
        </div>

        <div style={styles.subtitle}>
          PDFs available for chunking and embedding into the regulatory vector store.
        </div>

        <div style={styles.body}>
          {loading && <div style={styles.muted}>Loading sources…</div>}
          {error && <div style={styles.error}>Error: {error}</div>}
          {!loading && !error && sources.length === 0 && (
            <div style={styles.muted}>No PDFs found in backend/.</div>
          )}

          {sources.map((s) => {
            const result = results[s.filename]
            const isBusy = busy === s.filename
            const ingested = s.ingested_chunks > 0
            return (
              <div key={s.filename} style={styles.row}>
                <div style={styles.rowMain}>
                  <div style={styles.fname}>{s.filename}</div>
                  <div style={styles.meta}>
                    {formatBytes(s.size_bytes)}
                    {' · '}
                    {ingested
                      ? <span style={styles.ingested}>{s.ingested_chunks} chunks ingested</span>
                      : <span style={styles.notIngested}>not ingested</span>}
                  </div>
                  {result?.status === 'done' && (
                    <div style={styles.successLine}>
                      ✓ {result.data.chunks_written} chunks written
                      {' · '}{result.data.sections} sections
                      {' · '}{result.data.parser_warnings} warnings
                      {' · '}dim {result.data.embedding_dim}
                    </div>
                  )}
                  {result?.status === 'error' && (
                    <div style={styles.errorLine}>✗ {result.error}</div>
                  )}
                </div>
                <button
                  type="button"
                  style={{
                    ...styles.actionBtn,
                    ...(isBusy ? styles.actionBtnBusy : {}),
                  }}
                  disabled={isBusy}
                  onClick={() => ingest(s.filename)}
                >
                  {isBusy
                    ? 'EMBEDDING…'
                    : ingested ? 'RE-EMBED' : 'CHUNK & EMBED'}
                </button>
              </div>
            )
          })}
        </div>

        <div style={styles.footer}>
          <span style={styles.footerHint}>
            Embedding runs server-side and may take 30-90s per PDF.
          </span>
          <button style={styles.footerBtn} onClick={onClose}>CLOSE</button>
        </div>
      </div>
    </div>
  )
}

const styles = {
  backdrop: {
    position: 'fixed',
    inset: 0,
    background: 'rgba(0, 0, 0, 0.7)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 1000,
    backdropFilter: 'blur(2px)',
  },
  modal: {
    width: 'min(640px, 90vw)',
    maxHeight: '85vh',
    background: 'var(--bg-secondary)',
    border: '1px solid var(--green-primary)',
    borderRadius: '8px',
    boxShadow: '0 0 30px rgba(0, 255, 100, 0.15)',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '14px 18px',
    borderBottom: '1px solid var(--border)',
    background: 'var(--bg-card)',
  },
  title: {
    fontFamily: 'var(--font-mono)',
    fontSize: '12px',
    letterSpacing: '3px',
    color: 'var(--green-primary)',
  },
  closeBtn: {
    background: 'transparent',
    border: 'none',
    color: 'var(--text-muted)',
    fontSize: '22px',
    cursor: 'pointer',
    lineHeight: 1,
    padding: '0 4px',
  },
  subtitle: {
    padding: '10px 18px 0',
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--text-muted)',
  },
  body: {
    padding: '14px 18px',
    overflowY: 'auto',
    display: 'flex',
    flexDirection: 'column',
    gap: '10px',
    flex: 1,
  },
  row: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: '12px',
    padding: '12px 14px',
    background: 'var(--bg-card)',
    border: '1px solid var(--border)',
    borderRadius: '6px',
  },
  rowMain: {
    flex: 1,
    minWidth: 0,
  },
  fname: {
    fontFamily: 'var(--font-mono)',
    fontSize: '12px',
    color: 'var(--text-primary)',
    wordBreak: 'break-all',
  },
  meta: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--text-muted)',
    marginTop: '4px',
  },
  ingested: { color: 'var(--green-primary)' },
  notIngested: { color: 'var(--yellow-warn)' },
  successLine: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--green-primary)',
    marginTop: '6px',
  },
  errorLine: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--red-alert)',
    marginTop: '6px',
    wordBreak: 'break-word',
  },
  actionBtn: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    letterSpacing: '1px',
    color: 'var(--green-primary)',
    background: 'var(--green-dim)',
    border: '1px solid var(--green-primary)',
    borderRadius: '4px',
    padding: '8px 12px',
    cursor: 'pointer',
    flexShrink: 0,
    whiteSpace: 'nowrap',
  },
  actionBtnBusy: {
    cursor: 'wait',
    opacity: 0.6,
  },
  footer: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '12px 18px',
    borderTop: '1px solid var(--border)',
    background: 'var(--bg-card)',
  },
  footerHint: {
    fontFamily: 'var(--font-mono)',
    fontSize: '9px',
    color: 'var(--text-muted)',
  },
  footerBtn: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    letterSpacing: '1px',
    color: 'var(--text-secondary)',
    background: 'transparent',
    border: '1px solid var(--border)',
    borderRadius: '4px',
    padding: '6px 14px',
    cursor: 'pointer',
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
