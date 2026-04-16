import { useState } from 'react'
import ProjectForm from './components/ProjectForm.jsx'
import AgentPipeline from './components/AgentPipeline.jsx'
import ResultsPanel from './components/ResultsPanel.jsx'
import BrainScanner from './components/BrainScanner.jsx'
import DatabaseView from './components/DatabaseView.jsx'
import EvaluationsView from './components/EvaluationsView.jsx'
import EvaluationChunksView from './components/EvaluationChunksView.jsx'
import useModelSelections from './hooks/useModelSelections.js'
import { runEcfrIngestCommand } from './lib/ecfrIngestCommand.js'

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
  const [view, setView]         = useState('main')
  const [selectedEvalId, setSelectedEvalId] = useState(null)
  const [selectedEvalFilename, setSelectedEvalFilename] = useState(null)
  const { selections, setSelection, availableProviders, modelCatalog } = useModelSelections()
  const [agentCosts, setAgentCosts] = useState({})
  const [currentProjectId, setCurrentProjectId] = useState(null)
  const [saveResultsFlash, setSaveResultsFlash] = useState(null) // null | 'saving' | 'saved' | 'error'

  const handleCostUpdate = (data) => {
    setAgentCosts((prev) => ({ ...prev, [data.agent]: data }))
  }

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
    if (isRunning) setAgentCosts({})
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
      return
    }

    if (cmd === '/ingest-ecfr' || cmd.startsWith('/ingest-ecfr ')) {
      await runEcfrIngestCommand(cmd, handleLog)
      return
    }

    handleLog({
      ts: Date.now() / 1000, level: 'WARNING', logger: 'eia.cli',
      msg: `unknown command: ${cmd} — try /ingest-ecfr <title> <part> [date] or /q`,
    })
  }

  const handleSaveResults = async () => {
    if (!currentProjectId) {
      setSaveResultsFlash('error')
      setTimeout(() => setSaveResultsFlash(null), 2000)
      return
    }
    setSaveResultsFlash('saving')
    try {
      const apiBase = import.meta.env.VITE_API_URL ?? ''
      const res = await fetch(`${apiBase}/api/projects/${currentProjectId}/outputs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agent_outputs: agentOutputs,
          agent_costs: agentCosts,
        }),
      })
      if (!res.ok) throw new Error('save failed')
      setSaveResultsFlash('saved')
      setTimeout(() => setSaveResultsFlash(null), 1500)
    } catch {
      setSaveResultsFlash('error')
      setTimeout(() => setSaveResultsFlash(null), 2000)
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
          <button
            style={view === 'evaluations' ? { ...styles.dbBtn, background: 'var(--green-dim)' } : styles.dbBtn}
            onClick={() => setView(view === 'evaluations' ? 'main' : 'evaluations')}
          >
            EVALUATIONS
          </button>
          <button
            style={view === 'db' ? { ...styles.dbBtn, background: 'var(--green-dim)' } : styles.dbBtn}
            onClick={() => setView(view === 'db' ? 'main' : 'db')}
          >
            VIEW DB
          </button>
          <span style={styles.statusChip}>SYSTEM ONLINE</span>
        </div>
      </header>

      {view === 'db' ? (
        <DatabaseView onBack={() => setView('main')} />
      ) : view === 'evaluations' ? (
        <EvaluationsView
          onBack={() => setView('main')}
          onOpenChunks={(eid, filename) => {
            setSelectedEvalId(eid)
            setSelectedEvalFilename(filename)
            setView('evaluation-chunks')
          }}
        />
      ) : view === 'evaluation-chunks' ? (
        <EvaluationChunksView
          evaluationId={selectedEvalId}
          filename={selectedEvalFilename}
          onBack={() => setView('evaluations')}
        />
      ) : (
        <div style={styles.main}>
          {/* Left: project form */}
          <div style={styles.colLeft}>
            <ProjectForm
              onResult={handleResult}
              onPipelineUpdate={handlePipelineUpdate}
              onStepsUpdate={handleStepsUpdate}
              onLog={handleLog}
              onRunningChange={handleRunningChange}
              modelSelections={selections}
              onCostUpdate={handleCostUpdate}
              onProjectIdChange={setCurrentProjectId}
              onLoadOutputs={(outputs, costs, pipelineStatus) => {
                setAgentOutputs(outputs)
                setAgentCosts(costs)
                setPipelineState(pipelineStatus)
                const hasAnyOutput = Object.values(outputs).some(v => v !== null)
                if (hasAnyOutput) {
                  setResults({
                    impact_matrix: outputs.impact_analysis || {},
                    regulations: outputs.regulatory_screening || [],
                    report: outputs.report_synthesis || {},
                  })
                } else {
                  setResults(null)
                }
              }}
            />
          </div>

          <div style={styles.separator} />

          {/* Middle: pipeline status + results */}
          <div style={styles.colMiddle}>
            <div style={styles.colMiddleTop}>
              <AgentPipeline
                pipelineState={pipelineState}
                agentOutputs={agentOutputs}
                selections={selections}
                setSelection={setSelection}
                availableProviders={availableProviders}
                modelCatalog={modelCatalog}
                agentCosts={agentCosts}
              />
            </div>
            <div style={styles.colMiddleBottom}>
              <ResultsPanel results={results} />
              {!running && Object.keys(agentOutputs).length > 0 && (
                <button
                  onClick={handleSaveResults}
                  disabled={saveResultsFlash === 'saving'}
                  style={{
                    ...styles.saveResultsBtn,
                    ...(saveResultsFlash === 'saved' ? styles.saveResultsBtnSaved : {}),
                    ...(saveResultsFlash === 'error' ? styles.saveResultsBtnError : {}),
                  }}
                >
                  {saveResultsFlash === 'saving' ? 'SAVING...'
                    : saveResultsFlash === 'saved' ? 'SAVED!'
                    : saveResultsFlash === 'error' ? 'SAVE PROJECT FIRST'
                    : 'SAVE RESULTS'}
                </button>
              )}
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
      )}
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
  dbBtn: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    letterSpacing: '1px',
    color: 'var(--green-primary)',
    background: 'transparent',
    border: '1px solid var(--green-primary)',
    borderRadius: '4px',
    padding: '4px 10px',
    cursor: 'pointer',
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
  saveResultsBtn: {
    width: '100%',
    marginTop: '12px',
    padding: '10px',
    background: 'transparent',
    color: 'var(--green-primary)',
    border: '1px solid var(--green-primary)',
    borderRadius: '4px',
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    fontWeight: 600,
    letterSpacing: '2px',
    cursor: 'pointer',
    transition: 'background 0.15s, color 0.15s',
  },
  saveResultsBtnSaved: {
    background: 'var(--green-primary)',
    color: '#0a0a0a',
  },
  saveResultsBtnError: {
    borderColor: '#ff4444',
    color: '#ff4444',
  },
}

export default App
