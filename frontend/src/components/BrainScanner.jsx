import { useEffect, useRef, useState } from 'react'

const LEVEL_COLORS = {
  INFO:     '#00ff87',
  WARNING:  '#ffaa00',
  ERROR:    '#ff4444',
  CRITICAL: '#ff4444',
  DEBUG:    '#444444',
}

function formatTs(ts) {
  const d = new Date(ts * 1000)
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  const ss = String(d.getSeconds()).padStart(2, '0')
  const ms = String(d.getMilliseconds()).padStart(3, '0')
  return `${hh}:${mm}:${ss}.${ms}`
}

function shortLogger(name) {
  // eia.agents.environmental_data → env_data
  return name
    .replace('eia.agents.', '')
    .replace('eia.', '')
    .replace('_', ' ')
    .slice(0, 16)
}

const scanLineKeyframes = `
@keyframes scanLine {
  0%   { top: 0%; opacity: 0.06; }
  100% { top: 100%; opacity: 0; }
}
@keyframes blink {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0; }
}
`
if (typeof document !== 'undefined') {
  const s = document.createElement('style')
  s.textContent = scanLineKeyframes
  document.head.appendChild(s)
}

export default function BrainScanner({ logs, running, onCommand }) {
  const bodyRef   = useRef(null)
  const inputRef  = useRef(null)
  const [cmd, setCmd]     = useState('')
  const [history, setHistory] = useState([])   // typed command echo lines
  const [histIdx, setHistIdx] = useState(-1)

  // Auto-scroll on new log entries
  useEffect(() => {
    if (bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight
    }
  }, [logs, history])

  const handleKey = (e) => {
    if (e.key === 'Enter') {
      const trimmed = cmd.trim()
      if (!trimmed) return
      setHistory(prev => [...prev, { type: 'cmd', text: trimmed }])
      setHistIdx(-1)
      setCmd('')
      onCommand(trimmed)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      // simple command history scroll — not implemented, just prevent caret jump
    }
  }

  // Merge log entries and command echoes into a single timeline
  // We use index as a stable key since logs only grow
  const allLines = [
    ...logs.map((l, i) => ({ ...l, _key: `log-${i}`, _type: 'log' })),
    ...history.map((h, i) => ({ ...h, _key: `cmd-${i}`, _type: 'cmd' })),
  ].sort((a, b) => (a.ts || 0) - (b.ts || 0))

  return (
    <div style={styles.container}>
      {/* Header */}
      <div style={styles.header}>
        <span style={styles.headerTitle}>BRAIN SCANNER</span>
        <span style={{ ...styles.headerBadge, ...(running ? styles.headerBadgeActive : {}) }}>
          {running ? 'SCANNING' : 'IDLE'}
        </span>
      </div>

      {/* CRT scan-line overlay */}
      {running && <div style={styles.scanLine} />}

      {/* Log body */}
      <div ref={bodyRef} style={styles.body}>
        {logs.length === 0 && history.length === 0 && (
          <div style={styles.idle}>
            Awaiting pipeline execution...
            <span style={styles.idleCursor}>_</span>
          </div>
        )}

        {allLines.map((line) => {
          if (line._type === 'cmd') {
            return (
              <div key={line._key} style={styles.cmdEcho}>
                <span style={styles.prompt}>&gt; </span>
                <span style={styles.cmdText}>{line.text}</span>
              </div>
            )
          }
          const color = LEVEL_COLORS[line.level] || '#888'
          return (
            <div key={line._key} style={styles.logLine}>
              <span style={styles.ts}>{formatTs(line.ts)}</span>
              <span style={{ ...styles.level, color }}>{line.level.slice(0, 4)}</span>
              <span style={styles.loggerName}>{shortLogger(line.logger)}</span>
              <span style={{ ...styles.msg, color: line.level === 'WARNING' ? '#ffaa00'
                                                  : line.level === 'ERROR'   ? '#ff4444'
                                                  : 'var(--text-primary)' }}>
                {line.msg}
              </span>
            </div>
          )
        })}

        {/* Blinking cursor while running */}
        {running && (
          <div style={styles.activeCursor}>
            <span style={styles.prompt}>&gt; </span>
            <span style={styles.blink}>█</span>
          </div>
        )}
      </div>

      {/* Terminal input */}
      <div style={styles.inputRow}>
        <span style={styles.prompt}>&gt;</span>
        <input
          ref={inputRef}
          style={styles.termInput}
          value={cmd}
          onChange={(e) => setCmd(e.target.value)}
          onKeyDown={handleKey}
          placeholder="type /q to interrupt..."
          spellCheck={false}
          autoComplete="off"
        />
      </div>
    </div>
  )
}

const styles = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    background: '#0a0a0a',
    border: '1px solid #1f1f1f',
    borderRadius: '8px',
    overflow: 'hidden',
    position: 'relative',
    fontFamily: 'var(--font-mono)',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '10px 14px',
    borderBottom: '1px solid #1f1f1f',
    background: '#111',
    flexShrink: 0,
  },
  headerTitle: {
    fontSize: '11px',
    color: 'var(--green-primary)',
    letterSpacing: '3px',
  },
  headerBadge: {
    fontSize: '10px',
    padding: '2px 8px',
    border: '1px solid #333',
    borderRadius: '3px',
    color: '#555',
    letterSpacing: '1px',
  },
  headerBadgeActive: {
    borderColor: 'var(--green-primary)',
    color: 'var(--green-primary)',
    boxShadow: '0 0 8px #00ff8740',
  },
  scanLine: {
    position: 'absolute',
    left: 0,
    right: 0,
    height: '2px',
    background: 'linear-gradient(transparent, #00ff8720, transparent)',
    animation: 'scanLine 3s linear infinite',
    pointerEvents: 'none',
    zIndex: 1,
  },
  body: {
    flex: 1,
    overflowY: 'auto',
    padding: '10px 12px',
    display: 'flex',
    flexDirection: 'column',
    gap: '1px',
  },
  idle: {
    color: '#333',
    fontSize: '12px',
    marginTop: '8px',
  },
  idleCursor: {
    color: '#333',
    animation: 'blink 1.2s step-start infinite',
    marginLeft: '2px',
  },
  logLine: {
    display: 'flex',
    alignItems: 'baseline',
    gap: '8px',
    fontSize: '11px',
    lineHeight: '1.6',
    flexWrap: 'nowrap',
  },
  ts: {
    color: '#333',
    flexShrink: 0,
    fontSize: '10px',
  },
  level: {
    flexShrink: 0,
    width: '30px',
    fontSize: '10px',
    fontWeight: 600,
  },
  loggerName: {
    color: '#555',
    flexShrink: 0,
    width: '120px',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    fontSize: '10px',
  },
  msg: {
    flex: 1,
    wordBreak: 'break-word',
    fontSize: '11px',
  },
  activeCursor: {
    display: 'flex',
    alignItems: 'center',
    fontSize: '11px',
    marginTop: '4px',
  },
  blink: {
    color: 'var(--green-primary)',
    animation: 'blink 1s step-start infinite',
  },
  cmdEcho: {
    display: 'flex',
    alignItems: 'baseline',
    gap: '4px',
    fontSize: '11px',
    lineHeight: '1.6',
    marginTop: '4px',
  },
  prompt: {
    color: 'var(--green-primary)',
    flexShrink: 0,
  },
  cmdText: {
    color: 'var(--text-secondary)',
  },
  inputRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    padding: '8px 12px',
    borderTop: '1px solid #1f1f1f',
    background: '#0d0d0d',
    flexShrink: 0,
  },
  termInput: {
    flex: 1,
    background: 'transparent',
    border: 'none',
    outline: 'none',
    color: 'var(--text-primary)',
    fontFamily: 'var(--font-mono)',
    fontSize: '12px',
    caretColor: 'var(--green-primary)',
  },
}
