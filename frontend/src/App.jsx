import { useState } from 'react'
import ProjectForm from './components/ProjectForm.jsx'
import AgentPipeline from './components/AgentPipeline.jsx'
import ResultsPanel from './components/ResultsPanel.jsx'
import BrainScanner from './components/BrainScanner.jsx'

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
  const [agentOutputs, setAgentOutputs] = useState({})
  const [results, setResults]   = useState(null)
  const [logs, setLogs]         = useState([])
  const [running, setRunning]   = useState(false)

  const handleResult = (data) => {
    setResults(data)
    if (data?.pipeline_status) setPipelineState(data.pipeline_status)
    setRunning(false)
  }

  const handlePipelineUpdate = (state) => {
    setPipelineState(state)
  }

  const handleStepsUpdate = (updater) => {
    setAgentOutputs(typeof updater === 'function' ? updater : () => updater)
  }

  const handleLog = (entry) => {
    if (entry === null) {
      setLogs([])
    } else {
      setLogs((prev) => [...prev, entry])
    }
  }

  const handleRunningChange = (isRunning) => {
    setRunning(isRunning)
  }

  const handleCommand = async (cmd) => {
    if (cmd === '/q') {
      try {
        const apiBase = import.meta.env.VITE_API_URL ?? ''
        await fetch(`${apiBase}/api/cancel`, { method: 'POST' })
      } catch {
        // best-effort
      }
      setRunning(false)
    }
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
          <span style={styles.providerBadge}>Gemini</span>
          <span style={styles.statusChip}>SYSTEM ONLINE</span>
        </div>
      </header>

      {/* Main — 3 columns */}
      <div style={styles.main}>
        {/* Left: project form */}
        <div style={styles.colLeft}>
          <ProjectForm
            onResult={handleResult}
            onPipelineUpdate={handlePipelineUpdate}
            onStepsUpdate={handleStepsUpdate}
            onLog={handleLog}
            onRunningChange={handleRunningChange}
          />
        </div>

        <div style={styles.separator} />

        {/* Middle: pipeline status + results */}
        <div style={styles.colMiddle}>
          <div style={styles.colMiddleTop}>
            <AgentPipeline pipelineState={pipelineState} agentOutputs={agentOutputs} />
          </div>
          <div style={styles.colMiddleBottom}>
            <ResultsPanel results={results} />
          </div>
        </div>

        <div style={styles.separator} />

        {/* Right: brain scanner */}
        <div style={styles.colRight}>
          <BrainScanner
            logs={logs}
            running={running}
            onCommand={handleCommand}
          />
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
  separator: {
    width: '1px',
    background: 'var(--border)',
    flexShrink: 0,
  },
  colLeft: {
    width: '30%',
    padding: '20px',
    overflowY: 'auto',
    flexShrink: 0,
  },
  colMiddle: {
    width: '28%',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
    flexShrink: 0,
  },
  colMiddleTop: {
    flex: 1,
    padding: '20px',
    overflowY: 'auto',
    borderBottom: '1px solid var(--border)',
  },
  colMiddleBottom: {
    flex: 1,
    padding: '20px',
    overflowY: 'auto',
  },
  colRight: {
    flex: 1,
    padding: '20px',
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column',
  },
}

export default App
