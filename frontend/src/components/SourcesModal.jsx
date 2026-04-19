import { useEffect, useRef, useState, useCallback } from 'react'

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

  // Multi-select state
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [lastClickedId, setLastClickedId] = useState(null)

  // Project assignment state
  const [projects, setProjects] = useState([])
  const [assignProjectId, setAssignProjectId] = useState('')
  const [assigning, setAssigning] = useState(false)
  const [assignFlash, setAssignFlash] = useState(null) // null | 'ok' | 'error'

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

  const fetchProjects = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/api/projects`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setProjects(Array.isArray(data) ? data : [])
    } catch (e) {
      console.warn('SourcesModal: failed to load projects:', e.message)
      setProjects([])
    }
  }, [])

  useEffect(() => { fetchSources() }, [fetchSources])
  useEffect(() => { fetchProjects() }, [fetchProjects])

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
    if (errMsg) { setUploadError(errMsg); return }
    setUploadError(null)
    setUploading(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('is_current', 'true')
      const res = await fetch(`${apiBase}/api/regulations/sources`, { method: 'POST', body: fd })
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
      const res = await fetch(`${apiBase}/api/regulations/sources/${id}`, { method: 'DELETE' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setSelectedIds(prev => { const next = new Set(prev); next.delete(id); return next })
    } catch (e) {
      setError(e.message || 'Delete failed')
    } finally {
      setConfirmDeleteId(null)
      fetchSources()
    }
  }

  // ── Multi-select logic ───────────────────────────────────────────────────
  const handleRowClick = (e, id) => {
    // Don't interfere with button clicks inside the row
    if (e.target.tagName === 'BUTTON') return

    if (e.shiftKey && lastClickedId) {
      const ids = sources.map(s => s.id)
      const from = ids.indexOf(lastClickedId)
      const to = ids.indexOf(id)
      const range = ids.slice(Math.min(from, to), Math.max(from, to) + 1)
      setSelectedIds(prev => { const next = new Set(prev); range.forEach(rid => next.add(rid)); return next })
      setLastClickedId(id)
    } else if (e.ctrlKey || e.metaKey) {
      setSelectedIds(prev => {
        const next = new Set(prev)
        if (next.has(id)) next.delete(id)
        else next.add(id)
        return next
      })
      setLastClickedId(id)
    } else {
      // Single-click: select only this, or deselect if already sole selection
      setSelectedIds(prev => (prev.size === 1 && prev.has(id)) ? new Set() : new Set([id]))
      setLastClickedId(id)
    }
  }

  // ── Assignment ───────────────────────────────────────────────────────────
  const handleAssign = async () => {
    if (selectedIds.size === 0) return
    const pid = assignProjectId === '' || assignProjectId === 'none'
      ? null
      : parseInt(assignProjectId, 10)
    setAssigning(true)
    setAssignFlash(null)
    try {
      const res = await fetch(`${apiBase}/api/regulations/sources/assign`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_ids: Array.from(selectedIds), project_id: pid }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setAssignFlash('ok')
      setSelectedIds(new Set())
      setAssignProjectId('')
      await fetchSources()
    } catch {
      setAssignFlash('error')
    } finally {
      setAssigning(false)
      setTimeout(() => setAssignFlash(null), 2000)
    }
  }

  // Project name lookup helper
  const projectName = (pid) => {
    if (pid == null) return null
    const p = projects.find(p => p.id === pid)
    return p ? p.name : `Project #${pid}`
  }

  const hasNoProjects = projects.length === 0
  const selCount = selectedIds.size
  const showToolbar = selCount > 0

  return (
    <div style={styles.backdrop} onClick={onClose}>
      <div style={styles.modal} onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div style={styles.header}>
          <span style={styles.title}>REGULATORY SOURCES</span>
          <button style={styles.closeBtn} onClick={onClose} title="Close">×</button>
        </div>

        {/* Save-project reminder banner */}
        {hasNoProjects && (
          <div style={styles.reminderBanner}>
            ⚠ No saved projects yet — save a project in the main panel before assigning sources.
            Sources run pipeline RAG on assigned sources only; unassigned sources are skipped.
          </div>
        )}

        {/* Drop zone */}
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

        {/* Selection / assignment toolbar */}
        {showToolbar && (
          <div style={styles.toolbar}>
            <span style={styles.toolbarCount}>
              {selCount} selected
            </span>
            <div style={styles.toolbarRight}>
              {hasNoProjects ? (
                <span style={styles.toolbarNoProjects}>
                  Save a project first to assign
                </span>
              ) : (
                <>
                  <select
                    style={styles.projectSelect}
                    value={assignProjectId}
                    onChange={e => setAssignProjectId(e.target.value)}
                  >
                    <option value="">— pick a project —</option>
                    <option value="none">Remove assignment</option>
                    {projects.map(p => (
                      <option key={p.id} value={String(p.id)}>{p.name}</option>
                    ))}
                  </select>
                  <button
                    style={{
                      ...styles.assignBtn,
                      ...(assignFlash === 'ok' ? styles.assignBtnOk : {}),
                      ...(assignFlash === 'error' ? styles.assignBtnErr : {}),
                    }}
                    onClick={handleAssign}
                    disabled={assigning || assignProjectId === ''}
                  >
                    {assigning ? 'ASSIGNING…'
                      : assignFlash === 'ok' ? 'ASSIGNED ✓'
                      : assignFlash === 'error' ? 'FAILED'
                      : 'ASSIGN'}
                  </button>
                </>
              )}
              <button
                style={styles.clearSelBtn}
                onClick={() => setSelectedIds(new Set())}
                title="Clear selection"
              >
                ×
              </button>
            </div>
          </div>
        )}

        {/* Source list */}
        <div style={styles.body}>
          {loading && <div style={styles.muted}>Loading sources…</div>}
          {error && <div style={styles.error}>Error: {error}</div>}
          {!loading && !error && sources.length === 0 && (
            <div style={styles.muted}>No sources yet. Drop a PDF above to begin.</div>
          )}
          {!loading && !error && sources.length > 0 && (
            <div style={styles.selectHint}>
              Click to select · Ctrl+click to multi-select · Shift+click for range
            </div>
          )}

          {sources.map((row) => {
            const eta = computeEta(row)
            const pct = row.chunks_total
              ? Math.min(100, Math.max(0, (row.chunks_embedded / row.chunks_total) * 100))
              : 0
            const showConfirm = confirmDeleteId === row.id
            const isSelected = selectedIds.has(row.id)
            const pname = projectName(row.project_id)

            return (
              <div
                key={row.id}
                style={{
                  ...styles.row,
                  ...(isSelected ? styles.rowSelected : {}),
                  cursor: 'pointer',
                }}
                onClick={(e) => handleRowClick(e, row.id)}
              >
                {/* Selection indicator */}
                <div style={styles.selIndicator}>
                  <div style={{
                    ...styles.selDot,
                    background: isSelected ? 'var(--green-primary)' : 'transparent',
                    border: isSelected ? '2px solid var(--green-primary)' : '2px solid var(--border)',
                  }} />
                </div>

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
                  {/* Project assignment badge */}
                  <div style={styles.projectBadge}>
                    {pname
                      ? <span style={styles.badgeAssigned}>⬡ {pname}</span>
                      : <span style={styles.badgeUnassigned}>
                          {!hasNoProjects ? '— unassigned — select & assign above' : '— unassigned'}
                        </span>
                    }
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
                      <button type="button" style={styles.confirmBtn} onClick={() => onDelete(row.id)}>
                        CONFIRM DELETE
                      </button>
                      <button type="button" style={styles.cancelBtn} onClick={() => setConfirmDeleteId(null)}>
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

        {/* Footer */}
        <div style={styles.footer}>
          <span style={styles.footerHint}>
            {hasNoProjects
              ? '⚠ Save a project first — assigned sources are used exclusively for that project\'s RAG run.'
              : 'Assigned sources are used exclusively during that project\'s regulatory screening step.'}
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
    width: 'min(720px, 94vw)', maxHeight: '90vh',
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
  reminderBanner: {
    margin: '10px 18px 0',
    padding: '9px 12px',
    background: 'rgba(240,165,0,0.08)',
    border: '1px solid rgba(240,165,0,0.4)',
    borderRadius: '5px',
    fontFamily: 'var(--font-mono)', fontSize: '10px',
    color: '#f0a500',
    lineHeight: 1.5,
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
  dropIcon: { fontSize: '20px', color: 'var(--green-primary)', marginBottom: '6px' },
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
    border: '1px solid var(--red-alert)', borderRadius: '4px',
  },
  // Toolbar
  toolbar: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    margin: '10px 18px 0', padding: '8px 12px',
    background: 'var(--green-dim)',
    border: '1px solid var(--green-primary)',
    borderRadius: '5px',
    gap: '10px',
  },
  toolbarCount: {
    fontFamily: 'var(--font-mono)', fontSize: '10px',
    color: 'var(--green-primary)', letterSpacing: '1px', whiteSpace: 'nowrap',
  },
  toolbarRight: { display: 'flex', alignItems: 'center', gap: '8px' },
  toolbarNoProjects: {
    fontFamily: 'var(--font-mono)', fontSize: '10px',
    color: '#f0a500', fontStyle: 'italic',
  },
  projectSelect: {
    fontFamily: 'var(--font-mono)', fontSize: '10px',
    background: 'var(--bg-primary)', color: 'var(--text-primary)',
    border: '1px solid var(--border)', borderRadius: '4px',
    padding: '4px 8px', cursor: 'pointer',
  },
  assignBtn: {
    fontFamily: 'var(--font-mono)', fontSize: '10px', letterSpacing: '1px',
    color: 'var(--green-primary)', background: 'transparent',
    border: '1px solid var(--green-primary)', borderRadius: '4px',
    padding: '4px 10px', cursor: 'pointer', whiteSpace: 'nowrap',
  },
  assignBtnOk: { color: '#0a0a0a', background: 'var(--green-primary)' },
  assignBtnErr: { color: 'var(--red-alert)', borderColor: 'var(--red-alert)' },
  clearSelBtn: {
    fontFamily: 'var(--font-mono)', fontSize: '14px', lineHeight: 1,
    color: 'var(--text-muted)', background: 'transparent',
    border: 'none', cursor: 'pointer', padding: '0 4px',
  },
  // Select hint
  selectHint: {
    fontFamily: 'var(--font-mono)', fontSize: '9px',
    color: 'var(--text-muted)', letterSpacing: '0.5px',
    paddingBottom: '4px',
  },
  body: {
    padding: '10px 18px 14px', overflowY: 'auto',
    display: 'flex', flexDirection: 'column', gap: '8px', flex: 1,
  },
  row: {
    display: 'flex', alignItems: 'flex-start', gap: '10px',
    padding: '10px 12px',
    background: 'var(--bg-card)',
    border: '1px solid var(--border)',
    borderRadius: '6px',
    transition: 'border-color 0.1s, background 0.1s',
    userSelect: 'none',
  },
  rowSelected: {
    borderColor: 'var(--green-primary)',
    background: 'var(--green-dim)',
  },
  selIndicator: {
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    paddingTop: '2px', flexShrink: 0,
  },
  selDot: {
    width: 12, height: 12, borderRadius: '50%',
    transition: 'background 0.1s, border-color 0.1s',
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
  projectBadge: { marginTop: '5px' },
  badgeAssigned: {
    fontFamily: 'var(--font-mono)', fontSize: '9px',
    color: 'var(--green-primary)', letterSpacing: '0.5px',
    padding: '2px 6px',
    background: 'var(--green-dim)',
    border: '1px solid var(--green-primary)',
    borderRadius: '3px',
  },
  badgeUnassigned: {
    fontFamily: 'var(--font-mono)', fontSize: '9px',
    color: 'var(--text-muted)', fontStyle: 'italic',
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
    gap: '12px',
  },
  footerHint: {
    fontFamily: 'var(--font-mono)', fontSize: '9px',
    color: 'var(--text-muted)', flex: 1, lineHeight: 1.5,
  },
  footerBtn: {
    fontFamily: 'var(--font-mono)', fontSize: '10px', letterSpacing: '1px',
    color: 'var(--text-secondary)', background: 'transparent',
    border: '1px solid var(--border)', borderRadius: '4px',
    padding: '6px 14px', cursor: 'pointer', flexShrink: 0,
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
