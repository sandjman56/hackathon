import { useState } from 'react'

const apiBase = import.meta.env.VITE_API_URL ?? ''

const AGENT_SECTIONS = [
  { key: 'project_parser', label: 'PROJECT PARSE' },
  { key: 'environmental_data', label: 'API CALLS & RESULTS' },
  { key: 'regulatory_screening', label: 'REGULATORY SCREENING' },
  { key: 'impact_analysis', label: 'IMPACT MATRIX' },
  { key: 'report_synthesis', label: 'REPORT SYNTHESIS' },
]

export default function RunPreviewPanel({ onProjectSelect }) {
  const [projects, setProjects] = useState([])
  const [loadingProjects, setLoadingProjects] = useState(false)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [selectedProject, setSelectedProject] = useState(null)
  const [outputs, setOutputs] = useState(null)
  const [loadingOutputs, setLoadingOutputs] = useState(false)
  const [error, setError] = useState(null)
  const [collapsed, setCollapsed] = useState({ report_synthesis: true })

  const fetchProjects = async () => {
    setLoadingProjects(true)
    setError(null)
    try {
      const res = await fetch(`${apiBase}/api/pipeline-runs`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setProjects(Array.isArray(data) ? data : [])
    } catch (e) {
      setError(e.message)
    } finally {
      setLoadingProjects(false)
    }
  }

  const handleImport = () => {
    if (pickerOpen) {
      setPickerOpen(false)
      return
    }
    fetchProjects()
    setPickerOpen(true)
  }

  const handleSelect = async (run) => {
    setPickerOpen(false)
    // Normalize: expose `id` as project_id so downstream consumers (EvaluatePanel) work unchanged
    const normalized = { ...run, id: run.project_id }
    setSelectedProject(normalized)
    onProjectSelect?.(normalized)
    setLoadingOutputs(true)
    setError(null)
    try {
      const res = await fetch(`${apiBase}/api/projects/${run.project_id}/outputs`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setOutputs(data)
    } catch (e) {
      setError(e.message)
      setOutputs(null)
    } finally {
      setLoadingOutputs(false)
    }
  }

  const toggleSection = (key) => {
    setCollapsed((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <button style={styles.importBtn} onClick={handleImport}>
          IMPORT RUN
        </button>
        {selectedProject && (
          <span style={styles.projectName}>{selectedProject.name}</span>
        )}
      </div>

      {pickerOpen && (
        <div style={styles.picker}>
          {loadingProjects ? (
            <div style={styles.pickerItem}>Loading...</div>
          ) : projects.length === 0 ? (
            <div style={styles.pickerItem}>No saved runs found</div>
          ) : (
            projects.map((p) => (
              <button
                key={p.run_id}
                style={styles.pickerItem}
                onClick={() => handleSelect(p)}
              >
                <span style={styles.pickerName}>{p.name}</span>
                <span style={styles.pickerMeta}>
                  {p.coordinates} &middot; {p.run_saved_at ? new Date(p.run_saved_at).toLocaleDateString() : '—'}
                </span>
              </button>
            ))
          )}
        </div>
      )}

      {error && <div style={styles.error}>Error: {error}</div>}
      {loadingOutputs && <div style={styles.muted}>Loading pipeline outputs...</div>}

      {outputs && !loadingOutputs && (
        <div style={styles.sections}>
          {AGENT_SECTIONS.map(({ key, label }) => {
            const data = outputs[key]
            const isCollapsed = collapsed[key]
            return (
              <div key={key} style={styles.section}>
                <button
                  style={styles.sectionHeader}
                  onClick={() => toggleSection(key)}
                >
                  <span style={styles.chevron}>{isCollapsed ? '\u25B8' : '\u25BE'}</span>
                  <span style={styles.sectionLabel}>{label}</span>
                  {data && (
                    <span style={styles.sectionMeta}>
                      {data.model && <span style={styles.modelBadge}>{data.model}</span>}
                      {data.input_tokens != null && (
                        <span style={styles.tokenInfo}>
                          {(data.input_tokens + (data.output_tokens || 0)).toLocaleString()} tok
                        </span>
                      )}
                      {data.cost_usd != null && (
                        <span style={styles.costInfo}>${data.cost_usd.toFixed(4)}</span>
                      )}
                    </span>
                  )}
                </button>
                {!isCollapsed && (
                  <div style={styles.sectionBody}>
                    {!data ? (
                      <div style={styles.muted}>No data for this agent</div>
                    ) : (
                      <AgentOutput agentKey={key} output={data.output} />
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function AgentOutput({ agentKey, output }) {
  if (!output || (typeof output === 'object' && Object.keys(output).length === 0)) {
    return <div style={styles.muted}>Empty output</div>
  }

  switch (agentKey) {
    case 'project_parser':
      return <ProjectParseView data={output} />
    case 'environmental_data':
      return <EnvironmentalDataView data={output} />
    case 'regulatory_screening':
      return <RegulatoryScreeningView data={output} />
    case 'impact_analysis':
      return <ImpactMatrixView data={output} />
    case 'report_synthesis':
      return <ReportSynthesisView data={output} />
    default:
      return <JsonFallback data={output} />
  }
}

function ProjectParseView({ data }) {
  if (typeof data !== 'object') return <JsonFallback data={data} />
  const entries = Object.entries(data)
  return (
    <div>
      {entries.map(([k, v]) => (
        <div key={k} style={styles.kvRow}>
          <span style={styles.kvKey}>{k.replace(/_/g, ' ')}</span>
          <span style={styles.kvVal}>
            {typeof v === 'object' ? JSON.stringify(v, null, 2) : String(v)}
          </span>
        </div>
      ))}
    </div>
  )
}

function EnvironmentalDataView({ data }) {
  if (typeof data !== 'object') return <JsonFallback data={data} />
  const entries = Object.entries(data)
  return (
    <div>
      {entries.map(([source, result]) => (
        <div key={source} style={styles.apiCard}>
          <div style={styles.apiSource}>{source.replace(/_/g, ' ').toUpperCase()}</div>
          <pre style={styles.jsonSmall}>{JSON.stringify(result, null, 2)}</pre>
        </div>
      ))}
    </div>
  )
}

function RegulatoryScreeningView({ data }) {
  const regs = Array.isArray(data) ? data : []
  if (regs.length === 0) return <div style={styles.muted}>No regulations identified</div>
  return (
    <div>
      {regs.map((reg, i) => (
        <div key={i} style={styles.regCard}>
          <div style={styles.regName}>{reg.name || `Regulation ${i + 1}`}</div>
          {reg.description && <div style={styles.regDesc}>{reg.description}</div>}
          {reg.jurisdiction && <span style={styles.regTag}>{reg.jurisdiction}</span>}
        </div>
      ))}
    </div>
  )
}

function ImpactMatrixView({ data }) {
  const cells = data?.cells || []
  const actions = data?.actions || []
  const categories = data?.categories || []
  if (cells.length === 0) return <div style={styles.muted}>No impact data</div>

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={styles.matrixTable}>
        <thead>
          <tr>
            <th style={styles.matrixTh}>Category</th>
            {actions.map((a, i) => (
              <th key={i} style={styles.matrixTh}>{a}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {categories.map((cat, ri) => (
            <tr key={cat} style={{ background: ri % 2 === 0 ? 'var(--bg-card)' : 'transparent' }}>
              <td style={{ ...styles.matrixTd, fontWeight: 600 }}>{cat.replace(/_/g, ' ')}</td>
              {actions.map((action, ci) => {
                const cell = cells.find((c) => c.category === cat && c.action === action)
                if (!cell) return <td key={ci} style={{ ...styles.matrixTd, color: 'var(--text-muted)' }}>&mdash;</td>
                const det = cell.determination || {}
                return (
                  <td key={ci} style={styles.matrixTd}>
                    <div style={{ color: significanceColor(det.significance), fontWeight: 600, fontSize: '11px' }}>
                      {det.significance}
                    </div>
                    <div style={{ fontSize: '9px', color: 'var(--text-muted)' }}>
                      {Math.round((det.confidence || 0) * 100)}% conf
                    </div>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function significanceColor(level) {
  switch (level?.toLowerCase()) {
    case 'significant': return 'var(--red-alert)'
    case 'moderate': return 'var(--yellow-warn)'
    case 'none': case 'minimal': return 'var(--green-primary)'
    default: return 'var(--text-secondary)'
  }
}

function ReportSynthesisView({ data }) {
  const reportObj = data?.reports?.[0] || data
  const sections = reportObj?.sections || []
  if (sections.length === 0) return <JsonFallback data={data} />
  return (
    <div>
      {sections.map((s, i) => (
        <div key={i} style={styles.reportSection}>
          <div style={styles.reportSectionHead}>
            {s.section_number && <span style={styles.sectionNum}>{s.section_number}</span>}
            <span>{s.section_title}</span>
          </div>
          <div style={styles.reportContent}>{s.content || 'No content'}</div>
        </div>
      ))}
    </div>
  )
}

function JsonFallback({ data }) {
  return (
    <pre style={styles.jsonSmall}>{JSON.stringify(data, null, 2)}</pre>
  )
}

const styles = {
  container: { display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' },
  header: { display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '12px', flexShrink: 0 },
  importBtn: {
    fontFamily: 'var(--font-mono)', fontSize: '10px', letterSpacing: '2px',
    color: 'var(--green-primary)', background: 'var(--green-dim)',
    border: '1px solid var(--green-primary)', borderRadius: '4px',
    padding: '6px 14px', cursor: 'pointer',
  },
  projectName: {
    fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-primary)', fontWeight: 600,
  },
  picker: {
    background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: '6px',
    marginBottom: '12px', maxHeight: '200px', overflowY: 'auto',
  },
  pickerItem: {
    display: 'flex', flexDirection: 'column', gap: '2px', width: '100%',
    padding: '10px 14px', background: 'transparent', border: 'none',
    borderBottom: '1px solid var(--border)', cursor: 'pointer', textAlign: 'left',
  },
  pickerName: { fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--green-primary)', fontWeight: 600 },
  pickerMeta: { fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'var(--text-muted)' },
  error: { fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--red-alert)', padding: '4px 0' },
  muted: { fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)', fontStyle: 'italic', padding: '4px 0' },
  sections: { flex: 1, overflowY: 'auto' },
  section: { border: '1px solid var(--border)', borderRadius: '6px', marginBottom: '8px', overflow: 'hidden' },
  sectionHeader: {
    display: 'flex', alignItems: 'center', gap: '8px', width: '100%',
    padding: '8px 12px', background: 'var(--bg-card)', border: 'none',
    cursor: 'pointer', textAlign: 'left',
  },
  chevron: { fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--green-primary)', width: '14px' },
  sectionLabel: { fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--green-primary)', letterSpacing: '1px', fontWeight: 600 },
  sectionMeta: { display: 'flex', alignItems: 'center', gap: '8px', marginLeft: 'auto' },
  modelBadge: {
    fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'var(--green-primary)',
    background: 'var(--green-dim)', padding: '2px 6px', borderRadius: '3px', letterSpacing: '0.5px',
  },
  tokenInfo: { fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'var(--text-muted)' },
  costInfo: { fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'var(--text-secondary)' },
  sectionBody: { padding: '12px', borderTop: '1px solid var(--border)' },

  kvRow: { display: 'flex', gap: '12px', padding: '4px 0', borderBottom: '1px solid var(--border)' },
  kvKey: { fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)', minWidth: '120px', textTransform: 'uppercase', letterSpacing: '0.5px' },
  kvVal: { fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-primary)', whiteSpace: 'pre-wrap', wordBreak: 'break-word' },

  apiCard: { marginBottom: '10px', padding: '10px', background: 'var(--bg-secondary)', borderRadius: '4px', border: '1px solid var(--border)' },
  apiSource: { fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--green-primary)', letterSpacing: '1px', marginBottom: '6px', fontWeight: 600 },

  regCard: { background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: '4px', padding: '10px', marginBottom: '6px' },
  regName: { fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-primary)', fontWeight: 600, marginBottom: '4px' },
  regDesc: { fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '6px', lineHeight: 1.4 },
  regTag: { fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'var(--green-primary)', background: 'var(--green-dim)', padding: '2px 6px', borderRadius: '3px' },

  matrixTable: { width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: '11px' },
  matrixTh: { textAlign: 'left', padding: '6px 8px', color: 'var(--green-primary)', borderBottom: '1px solid var(--border)', fontSize: '9px', letterSpacing: '1px' },
  matrixTd: { padding: '6px 8px', color: 'var(--text-primary)', borderBottom: '1px solid var(--border)', fontSize: '11px' },

  reportSection: { marginBottom: '8px', border: '1px solid var(--border)', borderRadius: '4px', overflow: 'hidden' },
  reportSectionHead: { fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-primary)', fontWeight: 600, padding: '8px 10px', background: 'var(--bg-secondary)', display: 'flex', gap: '8px' },
  sectionNum: { color: 'var(--green-primary)', fontWeight: 600 },
  reportContent: { fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-secondary)', padding: '10px', lineHeight: 1.5, whiteSpace: 'pre-wrap' },

  jsonSmall: {
    background: '#0a0a0a', border: '1px solid var(--border)', borderRadius: '4px',
    padding: '10px', color: 'var(--green-primary)', fontFamily: 'var(--font-mono)',
    fontSize: '10px', overflow: 'auto', maxHeight: '300px', margin: 0,
  },
}
