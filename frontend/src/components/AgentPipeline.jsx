import { useState } from 'react'

const AGENTS = [
  { key: 'project_parser', name: 'PROJECT PARSER' },
  { key: 'environmental_data', name: 'ENVIRONMENTAL DATA' },
  { key: 'regulatory_screening', name: 'REGULATORY SCREENING' },
  { key: 'impact_analysis', name: 'IMPACT ANALYSIS' },
  { key: 'report_synthesis', name: 'REPORT SYNTHESIS' },
]

const agentPulseKeyframes = `
@keyframes agentPulse {
  0%, 100% { opacity: 1; box-shadow: 0 0 6px var(--green-primary); }
  50% { opacity: 0.4; box-shadow: none; }
}
`

if (typeof document !== 'undefined') {
  const style = document.createElement('style')
  style.textContent = agentPulseKeyframes
  document.head.appendChild(style)
}

function getDotStyle(status) {
  const base = {
    width: 10,
    height: 10,
    borderRadius: '50%',
    flexShrink: 0,
    transition: 'background 0.3s, box-shadow 0.3s',
  }
  switch (status) {
    case 'running':
      return {
        ...base,
        background: 'var(--green-primary)',
        animation: 'agentPulse 1.2s ease-in-out infinite',
      }
    case 'complete':
      return {
        ...base,
        background: 'var(--green-primary)',
        boxShadow: '0 0 6px var(--green-primary)',
      }
    case 'error':
      return { ...base, background: 'var(--red-alert)' }
    case 'pending':
      return { ...base, background: 'var(--yellow-warn)', opacity: 0.6 }
    default:
      return { ...base, background: 'var(--text-muted)' }
  }
}

function renderOutput(steps) {
  if (!steps) return null
  if (typeof steps === 'string') return steps
  return JSON.stringify(steps, null, 2)
}

export default function AgentPipeline({ pipelineState, agentOutputs = {} }) {
  const [openAgent, setOpenAgent] = useState(null)

  const toggleAgent = (key) => {
    setOpenAgent((prev) => (prev === key ? null : key))
  }

  return (
    <div>
      <div style={styles.label}>PIPELINE STATUS</div>
      <div style={styles.list}>
        {AGENTS.map((agent, i) => {
          const status = pipelineState[agent.key] || 'idle'
          const output = agentOutputs[agent.key]
          const isOpen = openAgent === agent.key
          const hasOutput = output !== undefined && output !== null

          return (
            <div key={agent.key}>
              <div
                style={{
                  ...styles.row,
                  cursor: hasOutput ? 'pointer' : 'default',
                  ...(isOpen ? styles.rowOpen : {}),
                }}
                onClick={() => hasOutput && toggleAgent(agent.key)}
              >
                <span style={getDotStyle(status)} />
                <span style={styles.agentName}>{agent.name}</span>
                <span style={styles.statusText}>
                  {status === 'complete' && 'DONE'}
                  {status === 'running' && 'RUNNING'}
                  {status === 'error' && 'ERROR'}
                  {status === 'pending' && 'PENDING'}
                </span>
                {hasOutput && (
                  <span style={styles.chevron}>{isOpen ? '▾' : '▸'}</span>
                )}
              </div>

              {isOpen && hasOutput && (
                <div style={styles.dropdown}>
                  <pre style={styles.dropdownContent}>{renderOutput(output)}</pre>
                </div>
              )}

              {i < AGENTS.length - 1 && (
                <div style={styles.connector} />
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

const styles = {
  label: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    color: 'var(--green-primary)',
    letterSpacing: '3px',
    marginBottom: '20px',
  },
  list: {
    display: 'flex',
    flexDirection: 'column',
  },
  row: {
    display: 'flex',
    alignItems: 'center',
    gap: '14px',
    padding: '12px 16px',
    background: 'var(--bg-card)',
    border: '1px solid var(--border)',
    borderRadius: '6px',
    userSelect: 'none',
    transition: 'border-color 0.15s, background 0.15s',
  },
  rowOpen: {
    borderColor: 'var(--green-primary)',
    borderBottomLeftRadius: 0,
    borderBottomRightRadius: 0,
  },
  agentName: {
    fontFamily: 'var(--font-mono)',
    fontSize: '12px',
    color: 'var(--text-primary)',
    flex: 1,
  },
  statusText: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--text-secondary)',
    letterSpacing: '1px',
  },
  chevron: {
    fontFamily: 'var(--font-mono)',
    fontSize: '12px',
    color: 'var(--green-primary)',
    flexShrink: 0,
  },
  connector: {
    width: '1px',
    height: '12px',
    background: 'var(--border-active)',
    marginLeft: '20px',
  },
  dropdown: {
    background: 'var(--bg-primary)',
    border: '1px solid var(--green-primary)',
    borderTop: 'none',
    borderBottomLeftRadius: '6px',
    borderBottomRightRadius: '6px',
    maxHeight: '220px',
    overflowY: 'auto',
  },
  dropdownContent: {
    margin: 0,
    padding: '12px 16px',
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    color: 'var(--text-secondary)',
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
    lineHeight: 1.6,
  },
}
