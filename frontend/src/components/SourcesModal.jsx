import { useEffect, useRef, useState, useCallback } from 'react'

// Vitest/@testing-library compatibility shim (test-only, no-op in prod):
// @testing-library/dom's waitFor detects fake timers via `typeof jest !== 'undefined'`.
// Under vitest, `vi` exists instead of `jest`, so waitFor falls back to its
// real-timer path AND @testing-library/react's asyncWrapper drains via
// `setTimeout(0)`, which IS faked by vi.useFakeTimers() → causes indefinite
// hangs in tests that combine fake timers with waitFor. Aliasing jest → vi
// lets testing-library take the fake-timer path which advances timers via
// jest.advanceTimersByTime. The `vi` global only exists in vitest, so this
// block is dead code in production bundles.
if (
  typeof globalThis !== 'undefined' &&
  typeof globalThis.vi !== 'undefined' &&
  typeof globalThis.jest === 'undefined'
) {
  globalThis.jest = globalThis.vi
}

const apiBase = import.meta.env.VITE_API_URL ?? ''
const POLL_INTERVAL_MS = 2000
const MAX_BYTES = 25 * 1024 * 1024

function formatBytes(n) {
  if (n == null) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(2)} MB`
}

function formatEta(secs) {
  if (secs == null || !Number.isFinite(secs) || secs < 0) return ''
  if (secs < 60) return `~${Math.round(secs)}s`
  const m = Math.floor(secs / 60)
  const s = Math.round(secs % 60)
  return `~${m}m ${s}s`
}

function computeEta(row) {
  if (row.status !== 'embedding') return null
  if (!row.embedding_started_at || !row.chunks_total) return null
  if ((row.chunks_embedded ?? 0) < 5) return null
  const startedMs = Date.parse(row.embedding_started_at)
  const elapsedSec = Math.max(0.1, (Date.now() - startedMs) / 1000)
  const rate = row.chunks_embedded / elapsedSec
  if (rate <= 0) return null
  const remaining = row.chunks_total - row.chunks_embedded
  return remaining / rate
}

function isInFlight(row) {
  return row.status === 'pending' || row.status === 'embedding'
}

export default function SourcesModal({ onClose }) {
  const [sources, setSources] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [uploadError, setUploadError] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [confirmDeleteId, setConfirmDeleteId] = useState(null)
  const [dragOver, setDragOver] = useState(false)
  const fileInputRef = useRef(null)
  const pollTimerRef = useRef(null)

  const fetchSources = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/api/regulations/sources`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setSources(data.sources || [])
      setError(null)
    } catch (e) {
      setError(e.message || 'Failed to load sources')
    } finally {
      setLoading(false)
    }
  }, [])

  // Initial load
  useEffect(() => { fetchSources() }, [fetchSources])

  // Polling while anything is in flight
  useEffect(() => {
    const anyInFlight = sources.some(isInFlight)
    if (!anyInFlight) {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current)
        pollTimerRef.current = null
      }
      return
    }
    if (pollTimerRef.current) return
    pollTimerRef.current = setInterval(fetchSources, POLL_INTERVAL_MS)
    return () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current)
        pollTimerRef.current = null
      }
    }
  }, [sources, fetchSources])

  // Close on Escape
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const validateFile = (file) => {
    if (!file) return 'No file selected'
    if (!file.name.toLowerCase().endsWith('.pdf') && file.type !== 'application/pdf') {
      return 'File must be a PDF'
    }
    if (file.size > MAX_BYTES) return `File too large (max ${MAX_BYTES / 1024 / 1024} MB)`
    return null
  }

  const uploadOne = async (file) => {
    const errMsg = validateFile(file)
    if (errMsg) {
      setUploadError(errMsg)
      return
    }
    setUploadError(null)
    setUploading(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('is_current', 'false')
      const res = await fetch(`${apiBase}/api/regulations/sources`, {
        method: 'POST',
        body: fd,
      })
      if (!res.ok) {
        let detail = `HTTP ${res.status}`
        try { detail = (await res.json()).detail || detail } catch {}
        throw new Error(detail)
      }
    } catch (e) {
      setUploadError(e.message || 'Upload failed')
    } finally {
      setUploading(false)
      fetchSources()
    }
  }

  const onFiles = async (fileList) => {
    const files = Array.from(fileList || [])
    for (const f of files) await uploadOne(f)
  }

  const onDrop = (e) => {
    e.preventDefault()
    setDragOver(false)
    onFiles(e.dataTransfer.files)
  }

  const onDelete = async (id) => {
    try {
      const res = await fetch(`${apiBase}/api/regulations/sources/${id}`, {
        method: 'DELETE',
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
    } catch (e) {
      setError(e.message || 'Delete failed')
    } finally {
      setConfirmDeleteId(null)
      fetchSources()
    }
  }

  return (
    <div style={styles.backdrop} onClick={onClose}>
      <div style={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div style={styles.header}>
          <span style={styles.title}>REGULATORY SOURCES</span>
          <button style={styles.closeBtn} onClick={onClose} title="Close">×</button>
        </div>

        <div
          data-testid="drop-zone"
          style={{ ...styles.dropZone, ...(dragOver ? styles.dropZoneActive : {}) }}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          onClick={() => fileInputRef.current?.click()}
        >
          <div style={styles.dropIcon}>⇧</div>
          <div style={styles.dropTitle}>
            {uploading ? 'UPLOADING…' : 'DROP PDF HERE OR CLICK TO BROWSE'}
          </div>
          <div style={styles.dropHint}>
            NEPA-style regulatory documents only · max 25 MB
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept="application/pdf"
            multiple
            style={{ display: 'none' }}
            onChange={(e) => onFiles(e.target.files)}
          />
        </div>

        {uploadError && <div style={styles.errorBanner}>{uploadError}</div>}

        <div style={styles.body}>
          {loading && <div style={styles.muted}>Loading sources…</div>}
          {error && <div style={styles.error}>Error: {error}</div>}
          {!loading && !error && sources.length === 0 && (
            <div style={styles.muted}>No sources yet. Drop a PDF above to begin.</div>
          )}

          {sources.map((row) => {
            const eta = computeEta(row)
            const pct = row.chunks_total
              ? Math.min(100, Math.max(0, (row.chunks_embedded / row.chunks_total) * 100))
              : 0
            const showConfirm = confirmDeleteId === row.id
            return (
              <div key={row.id} style={styles.row}>
                <div style={styles.rowMain}>
                  <div style={styles.fname}>
                    <span style={styles.statusDot(row.status)} />
                    {row.filename}
                  </div>
                  <div style={styles.meta}>
                    {formatBytes(row.size_bytes)}
                    {row.status === 'ready' && (
                      <> · <span style={styles.ready}>{row.chunk_count} chunks</span> · {row.sections_count} sections</>
                    )}
                    {row.status === 'embedding' && row.chunks_total != null && (
                      <> · {row.sections_count || '?'} sections detected</>
                    )}
                    {row.status === 'pending' && <> · queued</>}
                    {row.status === 'failed' && <> · <span style={styles.failed}>{row.status_message}</span></>}
                  </div>
                  {row.status === 'embedding' && row.chunks_total != null && (
                    <div style={styles.progressWrap}>
                      <div style={styles.progressBar}>
                        <div
                          data-testid={`progress-bar-fill-${row.id}`}
                          style={{ ...styles.progressFill, width: `${pct.toFixed(1)}%` }}
                        />
                      </div>
                      <div style={styles.progressText}>
                        {row.chunks_embedded} / {row.chunks_total} chunks
                        {eta != null && <> · {formatEta(eta)}</>}
                      </div>
                    </div>
                  )}
                </div>
                <div style={styles.rowActions}>
                  {showConfirm ? (
                    <>
                      <button
                        type="button"
                        style={styles.confirmBtn}
                        onClick={() => onDelete(row.id)}
                      >
                        CONFIRM DELETE
                      </button>
                      <button
                        type="button"
                        style={styles.cancelBtn}
                        onClick={() => setConfirmDeleteId(null)}
                      >
                        CANCEL
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      style={styles.deleteBtn}
                      onClick={() => setConfirmDeleteId(row.id)}
                      aria-label={`Delete ${row.filename}`}
                    >
                      DELETE
                    </button>
                  )}
                </div>
              </div>
            )
          })}
        </div>

        <div style={styles.footer}>
          <span style={styles.footerHint}>
            Embedding runs in the background.
          </span>
          <button style={styles.footerBtn} onClick={onClose}>CLOSE</button>
        </div>
      </div>
    </div>
  )
}

const dotColor = (status) => ({
  ready: 'var(--green-primary)',
  embedding: 'var(--green-primary)',
  pending: 'var(--text-muted)',
  failed: 'var(--red-alert)',
}[status] || 'var(--text-muted)')

const styles = {
  backdrop: {
    position: 'fixed', inset: 0,
    background: 'rgba(0, 0, 0, 0.7)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    zIndex: 1000, backdropFilter: 'blur(2px)',
  },
  modal: {
    width: 'min(680px, 92vw)', maxHeight: '88vh',
    background: 'var(--bg-secondary)',
    border: '1px solid var(--green-primary)',
    borderRadius: '8px',
    boxShadow: '0 0 30px rgba(0, 255, 100, 0.15)',
    display: 'flex', flexDirection: 'column', overflow: 'hidden',
  },
  header: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '14px 18px',
    borderBottom: '1px solid var(--border)',
    background: 'var(--bg-card)',
  },
  title: {
    fontFamily: 'var(--font-mono)', fontSize: '12px',
    letterSpacing: '3px', color: 'var(--green-primary)',
  },
  closeBtn: {
    background: 'transparent', border: 'none',
    color: 'var(--text-muted)', fontSize: '22px',
    cursor: 'pointer', lineHeight: 1, padding: '0 4px',
  },
  dropZone: {
    margin: '14px 18px 0',
    padding: '18px',
    border: '2px dashed var(--border)',
    borderRadius: '6px',
    textAlign: 'center',
    cursor: 'pointer',
    transition: 'border-color 0.15s, background 0.15s',
  },
  dropZoneActive: {
    borderColor: 'var(--green-primary)',
    background: 'var(--green-dim)',
  },
  dropIcon: {
    fontSize: '20px', color: 'var(--green-primary)', marginBottom: '6px',
  },
  dropTitle: {
    fontFamily: 'var(--font-mono)', fontSize: '11px',
    letterSpacing: '2px', color: 'var(--text-primary)',
  },
  dropHint: {
    fontFamily: 'var(--font-mono)', fontSize: '9px',
    color: 'var(--text-muted)', marginTop: '4px',
  },
  errorBanner: {
    margin: '8px 18px 0', padding: '8px 12px',
    fontFamily: 'var(--font-mono)', fontSize: '10px',
    color: 'var(--red-alert)',
    border: '1px solid var(--red-alert)',
    borderRadius: '4px',
  },
  body: {
    padding: '14px 18px', overflowY: 'auto',
    display: 'flex', flexDirection: 'column', gap: '10px', flex: 1,
  },
  row: {
    display: 'flex', alignItems: 'flex-start', gap: '12px',
    padding: '12px 14px',
    background: 'var(--bg-card)',
    border: '1px solid var(--border)',
    borderRadius: '6px',
  },
  rowMain: { flex: 1, minWidth: 0 },
  rowActions: {
    display: 'flex', flexDirection: 'column', gap: '6px', alignItems: 'flex-end',
  },
  fname: {
    fontFamily: 'var(--font-mono)', fontSize: '12px',
    color: 'var(--text-primary)', wordBreak: 'break-all',
    display: 'flex', alignItems: 'center', gap: '8px',
  },
  statusDot: (status) => ({
    display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
    background: dotColor(status),
    boxShadow: status === 'ready' ? '0 0 6px var(--green-primary)' : 'none',
    flexShrink: 0,
  }),
  meta: {
    fontFamily: 'var(--font-mono)', fontSize: '10px',
    color: 'var(--text-muted)', marginTop: '4px',
  },
  ready: { color: 'var(--green-primary)' },
  failed: { color: 'var(--red-alert)' },
  progressWrap: { marginTop: '8px' },
  progressBar: {
    width: '100%', height: '6px',
    background: 'var(--bg-primary)',
    border: '1px solid var(--border)',
    borderRadius: '3px', overflow: 'hidden',
  },
  progressFill: {
    height: '100%',
    background: 'var(--green-primary)',
    transition: 'width 0.6s ease',
  },
  progressText: {
    fontFamily: 'var(--font-mono)', fontSize: '9px',
    color: 'var(--text-secondary)', marginTop: '4px',
  },
  deleteBtn: {
    fontFamily: 'var(--font-mono)', fontSize: '9px', letterSpacing: '1px',
    color: 'var(--text-muted)', background: 'transparent',
    border: '1px solid var(--border)', borderRadius: '3px',
    padding: '4px 8px', cursor: 'pointer',
  },
  confirmBtn: {
    fontFamily: 'var(--font-mono)', fontSize: '9px', letterSpacing: '1px',
    color: 'var(--red-alert)', background: 'transparent',
    border: '1px solid var(--red-alert)', borderRadius: '3px',
    padding: '4px 8px', cursor: 'pointer',
  },
  cancelBtn: {
    fontFamily: 'var(--font-mono)', fontSize: '9px', letterSpacing: '1px',
    color: 'var(--text-muted)', background: 'transparent',
    border: '1px solid var(--border)', borderRadius: '3px',
    padding: '4px 8px', cursor: 'pointer',
  },
  footer: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '12px 18px',
    borderTop: '1px solid var(--border)',
    background: 'var(--bg-card)',
  },
  footerHint: {
    fontFamily: 'var(--font-mono)', fontSize: '9px',
    color: 'var(--text-muted)',
  },
  footerBtn: {
    fontFamily: 'var(--font-mono)', fontSize: '10px', letterSpacing: '1px',
    color: 'var(--text-secondary)', background: 'transparent',
    border: '1px solid var(--border)', borderRadius: '4px',
    padding: '6px 14px', cursor: 'pointer',
  },
  muted: {
    fontFamily: 'var(--font-mono)', fontSize: '11px',
    color: 'var(--text-muted)', fontStyle: 'italic',
    padding: '8px 0',
  },
  error: {
    fontFamily: 'var(--font-mono)', fontSize: '11px',
    color: 'var(--red-alert)', padding: '8px 0',
  },
}
