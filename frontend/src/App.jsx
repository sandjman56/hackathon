import { useState } from 'react'
import ProjectForm from './components/ProjectForm.jsx'
import AgentPipeline from './components/AgentPipeline.jsx'
import ResultsPanel from './components/ResultsPanel.jsx'

const AGENTS = [
  'project_parser',
  'environmental_data',
  'regulatory_screening',
  'impact_analysis',
  'report_synthesis',
]

function App() {
  const [pipelineState, setPipelineState] = useState(
    Object.fromEntries(AGENTS.map((a) => [a, 'idle']))
  )
  const [results, setResults] = useState(null)

  const handleResult = (data) => {
    setResults(data)
    if (data?.pipeline_status) {
      setPipelineState(data.pipeline_status)
    }
  }

  const handlePipelineUpdate = (state) => {
    setPipelineState(state)
  }

  return (
    <div style={styles.container}>
      {/* Header */}
      <header style={styles.header}>
        <div style={styles.headerLeft}>
          <span style={styles.pulsingDot} />
          <span style={styles.title}>EIA AGENT</span>
          <span style={styles.version}>v0.1.0</span>
        </div>
        <div style={styles.headerRight}>
          <span style={styles.providerBadge}>GPT-4o</span>
          <span style={styles.statusChip}>SYSTEM ONLINE</span>
        </div>
      </header>

      {/* Main content */}
      <div style={styles.main}>
        <div style={styles.leftColumn}>
          <ProjectForm
            onResult={handleResult}
            onPipelineUpdate={handlePipelineUpdate}
          />
        </div>
        <div style={styles.separator} />
        <div style={styles.rightColumn}>
          <div style={styles.rightTop}>
            <AgentPipeline pipelineState={pipelineState} />
          </div>
          <div style={styles.rightBottom}>
            <ResultsPanel results={results} />
          </div>
        </div>
      </div>
    </div>
  )
}

const pulseKeyframes = `
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}
`

if (typeof document !== 'undefined') {
  const style = document.createElement('style')
  style.textContent = pulseKeyframes
  document.head.appendChild(style)
}

const styles = {
  container: {
    height: '100vh',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '12px 24px',
    borderBottom: '1px solid var(--border)',
    background: 'var(--bg-secondary)',
    flexShrink: 0,
  },
  headerLeft: {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
  },
  pulsingDot: {
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: 'var(--green-primary)',
    animation: 'pulse 2s ease-in-out infinite',
  },
  title: {
    fontFamily: 'var(--font-mono)',
    fontSize: '14px',
    fontWeight: 600,
    color: 'var(--green-primary)',
    letterSpacing: '2px',
  },
  version: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    color: 'var(--text-muted)',
  },
  headerRight: {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
  },
  providerBadge: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    color: 'var(--text-secondary)',
    padding: '4px 10px',
    border: '1px solid var(--border)',
    borderRadius: '4px',
  },
  statusChip: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    color: 'var(--green-primary)',
    padding: '4px 10px',
    border: '1px solid var(--green-primary)',
    borderRadius: '4px',
    background: 'var(--green-dim)',
  },
  main: {
    display: 'flex',
    flex: 1,
    overflow: 'hidden',
  },
  leftColumn: {
    width: '40%',
    padding: '20px',
    overflowY: 'auto',
  },
  separator: {
    width: '1px',
    background: 'var(--green-dim)',
    flexShrink: 0,
  },
  rightColumn: {
    width: '60%',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
  },
  rightTop: {
    flex: 1,
    padding: '20px',
    overflowY: 'auto',
    borderBottom: '1px solid var(--border)',
  },
  rightBottom: {
    flex: 1,
    padding: '20px',
    overflowY: 'auto',
  },
}

export default App
