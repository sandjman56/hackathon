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

export default function AgentPipeline({ pipelineState }) {
  return (
    <div>
      <div style={styles.label}>PIPELINE STATUS</div>
      <div style={styles.list}>
        {AGENTS.map((agent, i) => {
          const status = pipelineState[agent.key] || 'idle'
          return (
            <div key={agent.key}>
              <div style={styles.row}>
                <span style={getDotStyle(status)} />
                <span style={styles.agentName}>{agent.name}</span>
                <span style={styles.statusText}>
                  {status === 'complete' && 'DONE'}
                  {status === 'running' && 'RUNNING'}
                  {status === 'error' && 'ERROR'}
                  {status === 'pending' && 'PENDING'}
                </span>
              </div>
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
  connector: {
    width: '1px',
    height: '12px',
    background: 'var(--border-active)',
    marginLeft: '20px',
  },
}
