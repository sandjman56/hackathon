import { useState, useEffect, useLayoutEffect, useRef } from 'react'
import ProjectForm from './components/ProjectForm.jsx'
import AgentPipeline from './components/AgentPipeline.jsx'
import ResultsPanel from './components/ResultsPanel.jsx'
import BrainScanner from './components/BrainScanner.jsx'
import Globe from './components/Globe.jsx'
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
  const [projectInfo, setProjectInfo] = useState({ projectName: '', coordinates: '' })
  const [saveResultsFlash, setSaveResultsFlash] = useState(null) // null | 'saving' | 'saved' | 'error'
  const [pendingOverwrite, setPendingOverwrite] = useState(null) // null | {saved_at}
  const [systemStatus, setSystemStatus] = useState('checking') // 'checking'|'online'|'pending'|'offline'
  const statusTimerRef = useRef(null)
  const globeContainerRef = useRef(null)
  const [globeSize, setGlobeSize] = useState(320)

  useEffect(() => {
    const apiBase = import.meta.env.VITE_API_URL ?? ''

    const check = async () => {
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), 8000)
      let next = 'offline'
      try {
        const res = await fetch(`${apiBase}/api/health`, { signal: controller.signal })
        clearTimeout(timeoutId)
        next = res.ok ? 'online' : 'pending'
      } catch (err) {
        clearTimeout(timeoutId)
        // AbortError means the 8s timeout fired — server is reachable but
        // not responding yet (Render spinning a free dyno back up).
        next = err.name === 'AbortError' ? 'pending' : 'offline'
      }
      setSystemStatus(next)
      // Poll more aggressively when not online so we catch spin-up quickly.
      statusTimerRef.current = setTimeout(check, next === 'online' ? 30000 : 12000)
    }

    check()
    return () => {
      if (statusTimerRef.current) clearTimeout(statusTimerRef.current)
    }
  }, [])

  useLayoutEffect(() => {
    if (!globeContainerRef.current) return
    const w = Math.floor(globeContainerRef.current.getBoundingClientRect().width)
    if (w > 0) setGlobeSize(w)
    const ro = new ResizeObserver(entries => {
      for (const e of entries) {
        const w = Math.floor(e.contentRect.width)
        if (w > 0) setGlobeSize(w)
      }
    })
    ro.observe(globeContainerRef.current)
    return () => ro.disconnect()
  }, [])

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

  const handleSaveResults = async (force = false) => {
    if (!currentProjectId) {
      setSaveResultsFlash('error')
      setTimeout(() => setSaveResultsFlash(null), 2000)
      return
    }
    setSaveResultsFlash('saving')
    setPendingOverwrite(null)
    try {
      const apiBase = import.meta.env.VITE_API_URL ?? ''
      const url = `${apiBase}/api/projects/${currentProjectId}/save-run${force ? '?force=true' : ''}`
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agent_outputs: agentOutputs,
          agent_costs: agentCosts,
        }),
      })
      if (res.status === 409) {
        const body = await res.json()
        setSaveResultsFlash(null)
        setPendingOverwrite({ saved_at: body.saved_at })
        return
      }
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
          <span style={{ ...styles.pulsingDot, background: STATUS_CONFIG[systemStatus].dot }} />
          <span style={styles.title}>CLEAVER</span>
          <span style={styles.subtitle}>Customized Environmental Impact Reports</span>
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
          <span style={{
            ...styles.statusChip,
            color: STATUS_CONFIG[systemStatus].color,
            borderColor: STATUS_CONFIG[systemStatus].color,
            background: STATUS_CONFIG[systemStatus].bg,
          }}>
            {STATUS_CONFIG[systemStatus].label}
          </span>
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
              onProjectIdChange={(id) => { setCurrentProjectId(id); setPendingOverwrite(null) }}
              onProjectInfoChange={setProjectInfo}
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
                <div style={{ marginTop: '12px' }}>
                  <button
                    onClick={() => handleSaveResults(false)}
                    disabled={saveResultsFlash === 'saving'}
                    style={{
                      ...styles.saveResultsBtn,
                      ...(saveResultsFlash === 'saved' ? styles.saveResultsBtnSaved : {}),
                      ...(saveResultsFlash === 'error' ? styles.saveResultsBtnError : {}),
                    }}
                  >
                    {saveResultsFlash === 'saving' ? 'SAVING...'
                      : saveResultsFlash === 'saved' ? 'SAVED ✓'
                      : saveResultsFlash === 'error' ? 'ERROR — TRY AGAIN'
                      : 'SAVE RESULTS'}
                  </button>
                  {pendingOverwrite && (
                    <div style={styles.overwriteWarning}>
                      <span>Results saved {new Date(pendingOverwrite.saved_at).toLocaleString()} already exist.</span>
                      <div style={{ display: 'flex', gap: '8px', marginTop: '8px' }}>
                        <button
                          style={styles.overwriteConfirmBtn}
                          onClick={() => handleSaveResults(true)}
                        >
                          CONFIRM OVERWRITE
                        </button>
                        <button
                          style={styles.overwriteCancelBtn}
                          onClick={() => setPendingOverwrite(null)}
                        >
                          CANCEL
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          <div style={styles.separator} />

          {/* Right: globe + brain scanner */}
          <div style={styles.colRight}>
            <div ref={globeContainerRef} style={styles.globeWrapper}>
              <Globe
                projectName={projectInfo.projectName}
                coordinates={projectInfo.coordinates}
                size={globeSize}
              />
            </div>
            <div style={styles.brainScannerWrapper}>
              <BrainScanner
                logs={logs}
                running={running}
                onCommand={handleCommand}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

const STATUS_CONFIG = {
  checking: { label: 'CHECKING...', color: 'var(--text-muted)', bg: 'transparent', dot: 'var(--text-muted)' },
  online:   { label: 'SYSTEM ONLINE',   color: 'var(--green-primary)', bg: 'var(--green-dim)',          dot: 'var(--green-primary)' },
  pending:  { label: 'SYSTEM PENDING',  color: '#f0a500',              bg: 'rgba(240,165,0,0.1)',        dot: '#f0a500' },
  offline:  { label: 'SYSTEM OFFLINE',  color: 'var(--red-alert)',     bg: 'rgba(255,68,68,0.1)',        dot: 'var(--red-alert)' },
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
  subtitle: {
    fontFamily: 'var(--font-mono)',
    fontSize: '9px',
    color: 'var(--text-muted)',
    letterSpacing: '0.5px',
    whiteSpace: 'nowrap',
    overflow: 'hidden',
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
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column',
    gap: 0,
  },
  globeWrapper: {
    width: '100%',
    aspectRatio: '1 / 1',
    flexShrink: 0,
    overflow: 'hidden',
  },
  brainScannerWrapper: {
    flex: 1,
    padding: '0 20px 20px 20px',
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column',
  },
  saveResultsBtn: {
    width: '100%',
    padding: '12px',
    background: 'var(--green-primary)',
    color: '#0a0a0a',
    border: '1px solid var(--green-primary)',
    borderRadius: '4px',
    fontFamily: 'var(--font-mono)',
    fontSize: '12px',
    fontWeight: 700,
    letterSpacing: '2px',
    cursor: 'pointer',
    transition: 'opacity 0.15s',
  },
  saveResultsBtnSaved: {
    opacity: 0.8,
  },
  saveResultsBtnError: {
    background: 'transparent',
    color: '#ff4444',
    borderColor: '#ff4444',
  },
  overwriteWarning: {
    marginTop: '10px',
    padding: '10px 12px',
    background: 'rgba(255,170,0,0.08)',
    border: '1px solid #ffaa00',
    borderRadius: '4px',
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: '#ffaa00',
    lineHeight: 1.5,
  },
  overwriteConfirmBtn: {
    fontFamily: 'var(--font-mono)',
    fontSize: '9px',
    letterSpacing: '1px',
    color: '#0a0a0a',
    background: '#ffaa00',
    border: '1px solid #ffaa00',
    borderRadius: '3px',
    padding: '4px 10px',
    cursor: 'pointer',
  },
  overwriteCancelBtn: {
    fontFamily: 'var(--font-mono)',
    fontSize: '9px',
    letterSpacing: '1px',
    color: 'var(--text-muted)',
    background: 'transparent',
    border: '1px solid var(--border)',
    borderRadius: '3px',
    padding: '4px 10px',
    cursor: 'pointer',
  },
}

export default App
