import { useEffect, useRef, useState } from 'react'

const apiBase = import.meta.env.VITE_API_URL ?? ''
const POLL_MS = 3000
const POLL_TIMEOUT_MS = 10 * 60 * 1000

export default function EcfrIngestModal({ onClose }) {
  const [title, setTitle] = useState('')
  const [part, setPart] = useState('')
  const [date, setDate] = useState('')
  const [phase, setPhase] = useState('form') // form | starting | polling | ready | failed | error
  const [msg, setMsg] = useState('')
  const [cid, setCid] = useState(null)
  const [row, setRow] = useState(null)
  const pollRef = useRef(null)
  const deadlineRef = useRef(null)

  useEffect(() => () => {
    if (pollRef.current) clearInterval(pollRef.current)
  }, [])

  const inFlight = phase === 'starting' || phase === 'polling'
  const titleNum = Number(title)
  const formValid =
    Number.isInteger(titleNum) && titleNum >= 1 && titleNum <= 50 && part.trim().length > 0

  const start = async () => {
    setPhase('starting')
    setMsg('posting to /api/regulations/sources/ecfr…')
    setRow(null)
    try {
      const body = { title: titleNum, part: part.trim() }
      if (date.trim()) body.date = date.trim()
      const res = await fetch(`${apiBase}/api/regulations/sources/ecfr`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) {
        const text = await res.text()
        setPhase('error')
        setMsg(`HTTP ${res.status}: ${text || res.statusText}`)
        return
      }
      const data = await res.json()
      setCid(data.correlation_id || null)
      setPhase('polling')
      setMsg(`accepted cid=${data.correlation_id || '?'} — polling every ${POLL_MS / 1000}s`)
      deadlineRef.current = Date.now() + POLL_TIMEOUT_MS
      pollRef.current = setInterval(() => pollOnce(titleNum, part.trim()), POLL_MS)
      // kick one poll immediately so the user sees the first status
      pollOnce(titleNum, part.trim())
    } catch (e) {
      setPhase('error')
      setMsg(`network error: ${e.message}`)
    }
  }

  const pollOnce = async (t, p) => {
    if (Date.now() > deadlineRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
      setPhase('error')
      setMsg(`timed out after ${POLL_TIMEOUT_MS / 1000}s — check regulatory_ingest_log`)
      return
    }
    try {
      const res = await fetch(`${apiBase}/api/regulations/sources`)
      if (!res.ok) return
      const body = await res.json()
      const match = (body.sources || []).find(
        (s) => s.cfr_title === t && String(s.cfr_part) === String(p),
      )
      if (!match) return
      setRow(match)
      if (match.status === 'ready') {
        clearInterval(pollRef.current)
        pollRef.current = null
        setPhase('ready')
        setMsg(`ready — ${match.chunk_count ?? 0} chunks stored`)
      } else if (match.status === 'failed') {
        clearInterval(pollRef.current)
        pollRef.current = null
        setPhase('failed')
        setMsg(`failed — ${match.error_message || 'see regulatory_ingest_log'}`)
      } else {
        setMsg(`status=${match.status} — still working…`)
      }
    } catch {
      // transient; next tick retries
    }
  }

  const handleClose = () => {
    if (inFlight) return
    if (pollRef.current) clearInterval(pollRef.current)
    onClose()
  }

  return (
    <div style={styles.overlay} onClick={handleClose} role="presentation">
      <div style={styles.modal} onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Ingest eCFR part">
        <div style={styles.header}>
          <span style={styles.title}>INGEST eCFR PART</span>
          <button
            style={styles.closeBtn}
            onClick={handleClose}
            disabled={inFlight}
            aria-label="close"
          >
            ×
          </button>
        </div>

        <div style={styles.body}>
          <label style={styles.label}>
            <span style={styles.labelText}>CFR title</span>
            <input
              style={styles.input}
              type="number"
              min={1}
              max={50}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              disabled={inFlight}
              placeholder="36"
            />
          </label>

          <label style={styles.label}>
            <span style={styles.labelText}>CFR part</span>
            <input
              style={styles.input}
              value={part}
              onChange={(e) => setPart(e.target.value)}
              disabled={inFlight}
              placeholder="800"
            />
          </label>

          <label style={styles.label}>
            <span style={styles.labelText}>
              date <span style={styles.hint}>(optional — ISO YYYY-MM-DD, default: current)</span>
            </span>
            <input
              style={styles.input}
              value={date}
              onChange={(e) => setDate(e.target.value)}
              disabled={inFlight}
              placeholder="current"
            />
          </label>

          <button
            style={{ ...styles.startBtn, ...(formValid && !inFlight ? {} : styles.startBtnDisabled) }}
            onClick={start}
            disabled={!formValid || inFlight}
          >
            {inFlight ? 'WORKING…' : phase === 'ready' || phase === 'failed' || phase === 'error' ? 'START AGAIN' : 'START INGEST'}
          </button>

          {phase !== 'form' && (
            <div style={{ ...styles.status, ...phaseStyle(phase) }}>
              <div style={styles.statusLine}>
                <span style={styles.statusLabel}>phase</span>
                <span style={styles.statusValue}>{phase}</span>
              </div>
              {cid && (
                <div style={styles.statusLine}>
                  <span style={styles.statusLabel}>cid</span>
                  <span style={styles.statusValue}>{cid}</span>
                </div>
              )}
              <div style={styles.statusLine}>
                <span style={styles.statusLabel}>msg</span>
                <span style={styles.statusValue}>{msg}</span>
              </div>
              {row && (
                <>
                  <div style={styles.statusLine}>
                    <span style={styles.statusLabel}>row.id</span>
                    <span style={styles.statusValue}>{row.id}</span>
                  </div>
                  <div style={styles.statusLine}>
                    <span style={styles.statusLabel}>chunks</span>
                    <span style={styles.statusValue}>{row.chunk_count ?? 0}</span>
                  </div>
                </>
              )}
            </div>
          )}

          <div style={styles.footer}>
            sample parts: <code>36/800</code>, <code>23/771</code>, <code>33/323</code>
          </div>
        </div>
      </div>
    </div>
  )
}

function phaseStyle(phase) {
  if (phase === 'ready') return { borderColor: 'var(--green-primary)', color: 'var(--green-primary)' }
  if (phase === 'failed' || phase === 'error') return { borderColor: '#ff4444', color: '#ff4444' }
  return { borderColor: '#ffaa00', color: '#ffaa00' }
}

const styles = {
  overlay: {
    position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
    display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
  },
  modal: {
    background: 'var(--bg-card)', border: '1px solid var(--border)',
    borderRadius: '8px', width: '520px', maxWidth: '90vw', fontFamily: 'var(--font-mono)',
  },
  header: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '12px 16px', borderBottom: '1px solid var(--border)',
  },
  title: { fontSize: '12px', color: 'var(--green-primary)', letterSpacing: '3px' },
  closeBtn: {
    background: 'transparent', color: 'var(--text-secondary)', border: 'none',
    fontSize: '20px', cursor: 'pointer', lineHeight: 1,
  },
  body: { padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' },
  label: { display: 'flex', flexDirection: 'column', gap: '4px' },
  labelText: { fontSize: '10px', color: 'var(--text-muted)', letterSpacing: '1px' },
  hint: { textTransform: 'none', letterSpacing: 0, color: 'var(--text-muted)' },
  input: {
    background: 'var(--bg-secondary)', border: '1px solid var(--border)',
    borderRadius: '4px', padding: '8px 10px', color: 'var(--text-primary)',
    fontFamily: 'var(--font-mono)', fontSize: '12px', outline: 'none',
  },
  startBtn: {
    background: 'var(--green-dim)', color: 'var(--green-primary)',
    border: '1px solid var(--green-primary)', borderRadius: '4px',
    padding: '10px', fontFamily: 'var(--font-mono)', fontSize: '11px',
    letterSpacing: '2px', cursor: 'pointer', marginTop: '4px',
  },
  startBtnDisabled: { opacity: 0.4, cursor: 'not-allowed' },
  status: {
    border: '1px solid var(--border)', borderRadius: '4px',
    padding: '10px', display: 'flex', flexDirection: 'column', gap: '4px',
    fontSize: '11px', background: 'var(--bg-secondary)',
  },
  statusLine: { display: 'flex', gap: '8px' },
  statusLabel: {
    width: '60px', flexShrink: 0, color: 'var(--text-muted)',
    fontSize: '10px', textTransform: 'uppercase', letterSpacing: '1px',
  },
  statusValue: { wordBreak: 'break-all', flex: 1 },
  footer: {
    fontSize: '10px', color: 'var(--text-muted)', marginTop: '4px', textAlign: 'center',
  },
}
