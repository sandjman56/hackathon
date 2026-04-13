import { useEffect, useState, useRef } from 'react'

const apiBase = import.meta.env.VITE_API_URL ?? ''

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function EvaluationsView({ onBack }) {
  const [docs, setDocs] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef(null)

  const fetchDocs = async () => {
    try {
      const res = await fetch(`${apiBase}/api/evaluations`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setDocs(data.documents)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchDocs()
  }, [])

  const handleUpload = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    setError(null)
    try {
      const form = new FormData()
      form.append('file', file)
      const res = await fetch(`${apiBase}/api/evaluations`, {
        method: 'POST',
        body: form,
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `HTTP ${res.status}`)
      }
      const doc = await res.json()
      setDocs((prev) => [doc, ...prev])
    } catch (e) {
      setError(e.message)
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const handleDelete = async (id) => {
    try {
      const res = await fetch(`${apiBase}/api/evaluations/${id}`, {
        method: 'DELETE',
      })
      if (!res.ok && res.status !== 204) throw new Error(`HTTP ${res.status}`)
      setDocs((prev) => prev.filter((d) => d.id !== id))
    } catch (e) {
      setError(e.message)
    }
  }

  return (
    <div style={styles.container}>
      <div style={styles.topBar}>
        <button style={styles.backBtn} onClick={onBack}>
          &larr; BACK
        </button>
        <span style={styles.pageTitle}>EVALUATIONS</span>
        <span style={styles.docCount}>
          {!loading && !error && `${docs.length} documents`}
        </span>
      </div>

      <div style={styles.body}>
        {/* Upload zone */}
        <div style={styles.uploadZone}>
          <input
            ref={fileRef}
            type="file"
            accept=".pdf"
            onChange={handleUpload}
            style={{ display: 'none' }}
          />
          <button
            style={styles.uploadBtn}
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
          >
            {uploading ? 'UPLOADING...' : 'UPLOAD EIS PDF'}
          </button>
          <span style={styles.uploadHint}>PDF files up to 25 MB</span>
        </div>

        {error && (
          <div style={styles.error}>Error: {error}</div>
        )}

        {loading && <div style={styles.muted}>Loading...</div>}

        {!loading && docs.length === 0 && (
          <div style={styles.muted}>No evaluation documents uploaded yet.</div>
        )}

        {!loading && docs.length > 0 && (
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>FILENAME</th>
                <th style={styles.th}>SIZE</th>
                <th style={styles.th}>UPLOADED</th>
                <th style={styles.th}></th>
              </tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id} style={styles.tr}>
                  <td style={styles.td}>{d.filename}</td>
                  <td style={styles.td}>{formatBytes(d.size_bytes)}</td>
                  <td style={styles.td}>
                    {new Date(d.uploaded_at).toLocaleDateString()}
                  </td>
                  <td style={styles.td}>
                    <button
                      style={styles.deleteBtn}
                      onClick={() => handleDelete(d.id)}
                    >
                      DELETE
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
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
    letterSpacing: '3px',
  },
  docCount: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    color: 'var(--text-muted)',
  },
  body: {
    flex: 1,
    padding: '24px',
    overflowY: 'auto',
  },
  uploadZone: {
    display: 'flex',
    alignItems: 'center',
    gap: '16px',
    marginBottom: '24px',
  },
  uploadBtn: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    letterSpacing: '1px',
    color: 'var(--green-primary)',
    background: 'transparent',
    border: '1px solid var(--green-primary)',
    borderRadius: '4px',
    padding: '8px 16px',
    cursor: 'pointer',
  },
  uploadHint: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--text-muted)',
  },
  error: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    color: 'var(--red-alert)',
    padding: '8px 0',
  },
  muted: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    color: 'var(--text-muted)',
    fontStyle: 'italic',
    padding: '8px 0',
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse',
  },
  th: {
    fontFamily: 'var(--font-mono)',
    fontSize: '9px',
    letterSpacing: '1px',
    color: 'var(--text-muted)',
    textAlign: 'left',
    padding: '8px 12px',
    borderBottom: '1px solid var(--border)',
  },
  tr: {
    borderBottom: '1px solid var(--border)',
  },
  td: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    color: 'var(--text-secondary)',
    padding: '10px 12px',
  },
  deleteBtn: {
    fontFamily: 'var(--font-mono)',
    fontSize: '9px',
    letterSpacing: '1px',
    color: 'var(--red-alert)',
    background: 'transparent',
    border: '1px solid var(--red-alert)',
    borderRadius: '3px',
    padding: '3px 8px',
    cursor: 'pointer',
  },
}
