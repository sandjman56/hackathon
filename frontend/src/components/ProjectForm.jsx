import { useState, useEffect } from 'react'

const PRESET_LOCATIONS = [
  { label: 'New York City', coordinates: '40.7128, -74.0060' },
  { label: 'Pittsburgh', coordinates: '40.4406, -79.9959' },
  { label: 'Washington DC', coordinates: '38.8950, -77.0364' },
]

const AGENTS = [
  'project_parser',
  'environmental_data',
  'regulatory_screening',
  'impact_analysis',
  'report_synthesis',
]

export default function ProjectForm({ onResult, onPipelineUpdate, onStepsUpdate, onLog, onRunningChange, modelSelections, onCostUpdate }) {
  const [projectName, setProjectName] = useState('')
  const [coordinates, setCoordinates] = useState('')
  const [description, setDescription] = useState('')
  const [loading, setLoading] = useState(false)
  const [savedProjects, setSavedProjects] = useState([])
  const [saveFlash, setSaveFlash] = useState(false)

  const apiBase = import.meta.env.VITE_API_URL ?? ''

  useEffect(() => {
    fetch(`${apiBase}/api/projects`)
      .then((r) => r.json())
      .then(setSavedProjects)
      .catch(() => {})
  }, [])

  const handleSave = async () => {
    if (!projectName.trim()) return
    try {
      const res = await fetch(`${apiBase}/api/projects`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: projectName.trim(),
          coordinates: coordinates.trim(),
          description: description.trim(),
        }),
      })
      const project = await res.json()
      setSavedProjects((prev) => [project, ...prev])
      setSaveFlash(true)
      setTimeout(() => setSaveFlash(false), 1200)
    } catch {
      // best-effort
    }
  }

  const handleLoad = (project) => {
    setProjectName(project.name)
    setCoordinates(project.coordinates)
    setDescription(project.description)
  }

  const handleDelete = async (id) => {
    try {
      await fetch(`${apiBase}/api/projects/${id}`, { method: 'DELETE' })
      setSavedProjects((prev) => prev.filter((p) => p.id !== id))
    } catch {
      // best-effort
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    onLog?.(null)  // clear Brain Scanner for new run
    onRunningChange?.(true)
    onPipelineUpdate(
      Object.fromEntries(AGENTS.map((a) => [a, 'pending']))
    )
    onStepsUpdate?.({})

    try {
      const apiBase = import.meta.env.VITE_API_URL ?? ''
      const res = await fetch(`${apiBase}/api/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_name: projectName,
          coordinates,
          description,
          models: modelSelections || {},
        }),
      })

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // Parse SSE events from buffer
        const events = buffer.split('\n\n')
        // Keep the last chunk (may be incomplete)
        buffer = events.pop() || ''

        for (const eventBlock of events) {
          if (!eventBlock.trim()) continue

          let eventType = ''
          let eventData = ''

          for (const line of eventBlock.split('\n')) {
            if (line.startsWith('event: ')) {
              eventType = line.slice(7)
            } else if (line.startsWith('data: ')) {
              eventData = line.slice(6)
            }
          }

          if (!eventData) continue

          try {
            const data = JSON.parse(eventData)
            handleSSEEvent(eventType, data)
          } catch {
            // skip malformed events
          }
        }
      }
    } catch (err) {
      console.error('Pipeline error:', err)
      onPipelineUpdate(
        Object.fromEntries(AGENTS.map((a) => [a, 'error']))
      )
    } finally {
      setLoading(false)
      onRunningChange?.(false)
    }
  }

  const handleSSEEvent = (eventType, data) => {
    switch (eventType) {
      case 'pipeline_start':
        if (data.pipeline_status) onPipelineUpdate(data.pipeline_status)
        break

      case 'agent_start':
        if (data.pipeline_status) onPipelineUpdate(data.pipeline_status)
        break

      case 'agent_step':
        break

      case 'agent_complete':
        if (data.pipeline_status) onPipelineUpdate(data.pipeline_status)
        if (data.output !== undefined) {
          onStepsUpdate?.((prev) => ({ ...prev, [data.agent]: data.output }))
        }
        break

      case 'agent_error':
        if (data.pipeline_status) onPipelineUpdate(data.pipeline_status)
        break

      case 'agent_cost':
        onCostUpdate?.(data)
        break

      case 'result':
        onResult(data)
        break

      case 'log':
        onLog?.(data)
        break

      case 'cancelled':
        onLog?.({
          ts: Date.now() / 1000,
          level: 'WARNING',
          logger: 'eia.pipeline',
          msg: data.msg || 'Pipeline cancelled',
        })
        onRunningChange?.(false)
        break
    }
  }

  return (
    <div style={styles.card}>
      <div style={styles.label}>PROJECT INPUT</div>
      <form onSubmit={handleSubmit}>
        <div style={styles.fieldGroup}>
          <label style={styles.fieldLabel}>Project Name</label>
          <input
            style={styles.input}
            type="text"
            value={projectName}
            onChange={(e) => setProjectName(e.target.value)}
            required
          />
        </div>

        <div style={styles.fieldGroup}>
          <label style={styles.fieldLabel}>Coordinates</label>
          <div style={styles.presets}>
            {PRESET_LOCATIONS.map((loc) => (
              <button
                key={loc.label}
                type="button"
                style={{
                  ...styles.presetBtn,
                  ...(coordinates === loc.coordinates ? styles.presetBtnActive : {}),
                }}
                onClick={() => setCoordinates(loc.coordinates)}
              >
                {loc.label}
              </button>
            ))}
          </div>
          <input
            style={styles.input}
            type="text"
            value={coordinates}
            onChange={(e) => setCoordinates(e.target.value)}
            placeholder="40.4406, -79.9959"
            required
          />
          <span style={styles.helper}>
            Decimal degrees — or click a preset above
          </span>
        </div>

        <div style={styles.fieldGroup}>
          <label style={styles.fieldLabel}>Project Description</label>
          <textarea
            style={{ ...styles.input, ...styles.textarea }}
            rows={5}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            required
          />
        </div>

        <button
          type="submit"
          disabled={loading}
          style={{
            ...styles.button,
            ...(loading ? styles.buttonLoading : {}),
          }}
        >
          {loading ? (
            <span style={styles.loadingContent}>
              <span style={styles.spinner} />
              PROCESSING...
            </span>
          ) : (
            'RUN PIPELINE'
          )}
        </button>

        <button
          type="button"
          onClick={handleSave}
          disabled={!projectName.trim()}
          style={{
            ...styles.saveBtn,
            ...(saveFlash ? styles.saveBtnFlash : {}),
            ...(!projectName.trim() ? styles.saveBtnDisabled : {}),
          }}
        >
          {saveFlash ? 'SAVED!' : 'SAVE PROJECT'}
        </button>
      </form>

      {savedProjects.length > 0 && (
        <div style={styles.savedSection}>
          <div style={styles.savedHeader}>SAVED PROJECTS</div>
          {savedProjects.map((p) => (
            <div key={p.id} style={styles.savedItem}>
              <div style={styles.savedItemMain}>
                <span style={styles.savedName}>{p.name}</span>
                <span style={styles.savedCoords}>{p.coordinates}</span>
                {p.description && (
                  <span style={styles.savedDesc}>{p.description}</span>
                )}
              </div>
              <div style={styles.savedActions}>
                <button
                  type="button"
                  style={styles.actionBtn}
                  onClick={() => handleLoad(p)}
                >
                  LOAD
                </button>
                <button
                  type="button"
                  style={{ ...styles.actionBtn, ...styles.actionBtnDelete }}
                  onClick={() => handleDelete(p.id)}
                >
                  ×
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

const spinnerKeyframes = `
@keyframes spin {
  to { transform: rotate(360deg); }
}
`

if (typeof document !== 'undefined') {
  const style = document.createElement('style')
  style.textContent = spinnerKeyframes
  document.head.appendChild(style)
}

const styles = {
  card: {
    background: 'var(--bg-card)',
    border: '1px solid var(--border)',
    borderRadius: '8px',
    padding: '24px',
  },
  label: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    color: 'var(--green-primary)',
    letterSpacing: '3px',
    marginBottom: '24px',
  },
  fieldGroup: {
    marginBottom: '20px',
  },
  fieldLabel: {
    display: 'block',
    fontFamily: 'var(--font-mono)',
    fontSize: '12px',
    color: 'var(--text-secondary)',
    marginBottom: '8px',
  },
  input: {
    width: '100%',
    padding: '12px',
    background: 'var(--bg-primary)',
    border: '1px solid var(--border)',
    borderBottom: '2px solid var(--border)',
    borderRadius: '4px',
    color: 'var(--text-primary)',
    fontFamily: 'var(--font-mono)',
    fontSize: '13px',
    outline: 'none',
    transition: 'border-color 0.2s, box-shadow 0.2s',
  },
  textarea: {
    resize: 'vertical',
  },
  presets: {
    display: 'flex',
    gap: '8px',
    marginBottom: '8px',
  },
  presetBtn: {
    padding: '4px 10px',
    background: 'transparent',
    border: '1px solid var(--border)',
    borderRadius: '3px',
    color: 'var(--text-secondary)',
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    cursor: 'pointer',
    letterSpacing: '0.5px',
    transition: 'border-color 0.15s, color 0.15s',
  },
  presetBtnActive: {
    borderColor: 'var(--green-primary)',
    color: 'var(--green-primary)',
  },
  helper: {
    display: 'block',
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--text-muted)',
    marginTop: '6px',
  },
  button: {
    width: '100%',
    padding: '14px',
    background: 'var(--green-primary)',
    color: '#0a0a0a',
    border: 'none',
    borderRadius: '4px',
    fontFamily: 'var(--font-mono)',
    fontSize: '13px',
    fontWeight: 600,
    letterSpacing: '2px',
    cursor: 'pointer',
    textTransform: 'uppercase',
    transition: 'filter 0.2s',
  },
  buttonLoading: {
    filter: 'brightness(0.8)',
    cursor: 'not-allowed',
  },
  loadingContent: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '10px',
  },
  spinner: {
    display: 'inline-block',
    width: 14,
    height: 14,
    border: '2px solid #0a0a0a40',
    borderTop: '2px solid #0a0a0a',
    borderRadius: '50%',
    animation: 'spin 0.8s linear infinite',
  },
  saveBtn: {
    width: '100%',
    marginTop: '8px',
    padding: '10px',
    background: 'transparent',
    color: 'var(--green-primary)',
    border: '1px solid var(--green-primary)',
    borderRadius: '4px',
    fontFamily: 'var(--font-mono)',
    fontSize: '12px',
    fontWeight: 600,
    letterSpacing: '2px',
    cursor: 'pointer',
    transition: 'background 0.15s, color 0.15s',
  },
  saveBtnFlash: {
    background: 'var(--green-primary)',
    color: '#0a0a0a',
  },
  saveBtnDisabled: {
    opacity: 0.3,
    cursor: 'not-allowed',
  },
  savedSection: {
    marginTop: '16px',
    borderTop: '1px solid var(--border)',
    paddingTop: '16px',
  },
  savedHeader: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--text-muted)',
    letterSpacing: '3px',
    marginBottom: '10px',
  },
  savedItem: {
    display: 'flex',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    gap: '8px',
    padding: '10px',
    marginBottom: '6px',
    background: 'var(--bg-primary)',
    border: '1px solid var(--border)',
    borderRadius: '4px',
  },
  savedItemMain: {
    display: 'flex',
    flexDirection: 'column',
    gap: '2px',
    flex: 1,
    minWidth: 0,
  },
  savedName: {
    fontFamily: 'var(--font-mono)',
    fontSize: '12px',
    color: 'var(--text-primary)',
    fontWeight: 600,
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  },
  savedCoords: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--green-primary)',
  },
  savedDesc: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--text-muted)',
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  },
  savedActions: {
    display: 'flex',
    gap: '4px',
    flexShrink: 0,
  },
  actionBtn: {
    padding: '3px 8px',
    background: 'transparent',
    border: '1px solid var(--border)',
    borderRadius: '3px',
    color: 'var(--text-secondary)',
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    cursor: 'pointer',
    letterSpacing: '0.5px',
    transition: 'border-color 0.15s, color 0.15s',
  },
  actionBtnDelete: {
    fontSize: '14px',
    padding: '1px 7px',
    lineHeight: 1,
  },
}
