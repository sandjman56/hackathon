import { useState, useEffect, useLayoutEffect, useRef } from 'react'
import ProjectForm from './components/ProjectForm.jsx'
import AgentPipeline from './components/AgentPipeline.jsx'
import ResultsPanel from './components/ResultsPanel.jsx'
import BrainScanner from './components/BrainScanner.jsx'
import Globe from './components/Globe.jsx'
import DatabaseView from './components/DatabaseView.jsx'
import EvaluationsView from './components/EvaluationsView.jsx'
import EvaluationChunksView from './components/EvaluationChunksView.jsx'
import MetricsView from './pages/MetricsView.jsx'
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
  const [agentDurations, setAgentDurations] = useState({})
  const [pipelineStartedAt, setPipelineStartedAt] = useState(null)
  const [currentProjectId, setCurrentProjectId] = useState(null)
  const [projectInfo, setProjectInfo] = useState({ projectName: '', coordinates: '' })
  const [saveResultsFlash, setSaveResultsFlash] = useState(null) // null | 'saving' | 'saved' | 'error'
  const [pendingOverwrite, setPendingOverwrite] = useState(null) // null | {saved_at}
  const [pipelineRunKey, setPipelineRunKey] = useState(0)
  const [evalMenuOpen, setEvalMenuOpen] = useState(false)
  const evalMenuRef = useRef(null)
  const [systemStatus, setSystemStatus] = useState('checking') // 'checking'|'online'|'pending'|'offline'
  const statusTimerRef = useRef(null)
  const globeContainerRef = useRef(null)
  const [globeSize, setGlobeSize] = useState(200)

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
    const rect = globeContainerRef.current.getBoundingClientRect()
    const s = Math.min(Math.floor(rect.height), Math.floor(rect.width))
    if (s > 0) setGlobeSize(s)
    const ro = new ResizeObserver(entries => {
      for (const e of entries) {
        const s = Math.min(Math.floor(e.contentRect.height), Math.floor(e.contentRect.width))
        if (s > 0) setGlobeSize(s)
      }
    })
    ro.observe(globeContainerRef.current)
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    if (!evalMenuOpen) return
    const handleOutside = (e) => {
      if (evalMenuRef.current && !evalMenuRef.current.contains(e.target)) {
        setEvalMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handleOutside)
    return () => document.removeEventListener('mousedown', handleOutside)
  }, [evalMenuOpen])

  const handleCostUpdate = (data) => {
    setAgentCosts((prev) => ({ ...prev, [data.agent]: data }))
  }

  const handleDurationUpdate = (agentKey, durationMs) => {
    setAgentDurations((prev) => ({ ...prev, [agentKey]: durationMs }))
  }

  const handlePipelineStartedAt = (startedAt) => {
    setPipelineStartedAt(startedAt)
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
    if (isRunning) {
      setAgentCosts({})
      setAgentDurations({})
      setPipelineStartedAt(null)
      setPipelineRunKey((k) => k + 1)
    }
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
      const res = await fetch(`${apiBase}/api/projects/${currentProjectId}/save-run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agent_outputs: agentOutputs,
          agent_costs: agentCosts,
          agent_durations: agentDurations,
          started_at: pipelineStartedAt,
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
          <svg width="36" height="50" viewBox="0 0 100 140" fill="none" style={{ filter: 'drop-shadow(0 0 8px #00ff87)', flexShrink: 0 }}>
            <g fill="#00ff87">
              <path d="M 50 4 L 52 80 L 50 90 L 48 80 Z"/>
              <path d="M 22 44 C 16 60, 24 80, 50 86 C 76 80, 84 60, 78 44 C 80 52, 72 68, 50 76 C 28 68, 20 52, 22 44 Z"/>
            </g>
          </svg>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1px' }}>
            <span style={styles.title}>CLEAVER</span>
            <span style={styles.subtitle}>Customized Environmental Impact Reports</span>
          </div>
        </div>
        <div style={styles.headerRight}>
          <div ref={evalMenuRef} style={{ position: 'relative' }}>
            <button
              style={['evaluations', 'evaluation-chunks', 'cost', 'latency'].includes(view) ? { ...styles.dbBtn, background: 'var(--green-dim)' } : styles.dbBtn}
              onClick={() => setEvalMenuOpen((o) => !o)}
            >
              EVALUATIONS ▾
            </button>
            {evalMenuOpen && (
              <div style={styles.evalDropdown}>
                {[
                  { label: 'PIPELINE EVALS', v: 'evaluations' },
                  { label: 'COST', v: 'cost' },
                  { label: 'LATENCY', v: 'latency' },
                ].map(({ label, v }) => (
                  <button
                    key={v}
                    style={{ ...styles.evalDropdownItem, ...(view === v ? styles.evalDropdownItemActive : {}) }}
                    onClick={() => { setView(v); setEvalMenuOpen(false) }}
                  >
                    {label}
                  </button>
                ))}
              </div>
            )}
          </div>
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
      ) : view === 'cost' ? (
        <MetricsView metric="cost" onBack={() => setView('main')} />
      ) : view === 'latency' ? (
        <MetricsView metric="latency" onBack={() => setView('main')} />
      ) : (
        <div style={styles.main}>
          {/* Left: project form */}
          <div style={styles.colLeft}>
            <ProjectForm
              projectId={currentProjectId}
              onResult={handleResult}
              onPipelineUpdate={handlePipelineUpdate}
              onStepsUpdate={handleStepsUpdate}
              onLog={handleLog}
              onRunningChange={handleRunningChange}
              modelSelections={selections}
              onCostUpdate={handleCostUpdate}
              onDurationUpdate={handleDurationUpdate}
              onPipelineStartedAt={handlePipelineStartedAt}
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
                agentDurations={agentDurations}
                pipelineRunKey={pipelineRunKey}
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
    textOverflow: 'ellipsis',
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
    width: '38%',
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
    minWidth: '200px',
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column',
    gap: 0,
  },
  globeWrapper: {
    flex: 1,
    overflow: 'hidden',
    display: 'flex',
    justifyContent: 'flex-end',
    alignItems: 'flex-start',
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
  evalDropdown: {
    position: 'absolute',
    top: 'calc(100% + 4px)',
    right: 0,
    background: 'var(--bg-secondary)',
    border: '1px solid var(--border)',
    borderRadius: '4px',
    zIndex: 100,
    minWidth: '150px',
    display: 'flex',
    flexDirection: 'column',
  },
  evalDropdownItem: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    letterSpacing: '1px',
    color: 'var(--text-secondary)',
    background: 'transparent',
    border: 'none',
    borderBottom: '1px solid var(--border)',
    padding: '8px 14px',
    cursor: 'pointer',
    textAlign: 'left',
  },
  evalDropdownItemActive: {
    color: 'var(--green-primary)',
    background: 'var(--green-dim)',
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
