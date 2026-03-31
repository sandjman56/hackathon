import { useState } from 'react'

const AGENTS = [
  'project_parser',
  'environmental_data',
  'regulatory_screening',
  'impact_analysis',
  'report_synthesis',
]

export default function ProjectForm({ onResult, onPipelineUpdate }) {
  const [projectName, setProjectName] = useState('')
  const [coordinates, setCoordinates] = useState('')
  const [description, setDescription] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    onPipelineUpdate(
      Object.fromEntries(AGENTS.map((a) => [a, 'pending']))
    )

    try {
      const res = await fetch('/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_name: projectName,
          coordinates,
          description,
        }),
      })
      const data = await res.json()
      onResult(data)
    } catch (err) {
      console.error('Pipeline error:', err)
      onPipelineUpdate(
        Object.fromEntries(AGENTS.map((a) => [a, 'error']))
      )
    } finally {
      setLoading(false)
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
          <input
            style={styles.input}
            type="text"
            value={coordinates}
            onChange={(e) => setCoordinates(e.target.value)}
            placeholder="40.4406\u00b0 N, 79.9959\u00b0 W"
            required
          />
          <span style={styles.helper}>
            Enter decimal degrees or DMS format
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
      </form>
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
}
