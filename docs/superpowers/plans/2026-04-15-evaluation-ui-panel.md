# Evaluation UI Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an evaluation UI panel to the evaluations page with "IMPORT RUN" to load past pipeline outputs, a resizable split-pane preview of all 5 agent outputs, and an EVALUATE stub button.

**Architecture:** New backend endpoint joins the 5 per-agent output tables by `project_id`. Frontend adds a resizable split-pane below the existing upload/docs section in `EvaluationsView`, with two new child components for the run preview and evaluate stub.

**Tech Stack:** FastAPI (Python), React 18, inline CSS styles (existing pattern), no new libraries.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `backend/main.py` | Modify (add ~40 lines after line 300) | New `GET /api/projects/{id}/outputs` endpoint |
| `frontend/src/components/RunPreviewPanel.jsx` | Create (~350 lines) | IMPORT RUN button, project picker dropdown, 5 collapsible agent output sections |
| `frontend/src/components/EvaluatePanel.jsx` | Create (~60 lines) | EVALUATE stub button |
| `frontend/src/components/EvaluationsView.jsx` | Modify | Add bottom split-pane section with resizable divider, import new components |

---

### Task 1: Backend — Project Outputs Endpoint

**Files:**
- Modify: `backend/main.py:288-300` (insert new endpoint before the delete endpoint)

- [ ] **Step 1: Add the endpoint**

Insert this after the `save_project` function (line 286) and before `delete_project` (line 288) in `backend/main.py`:

```python
AGENT_OUTPUT_TABLES = [
    ("project_parser", "project_parser_outputs"),
    ("environmental_data", "environmental_data_outputs"),
    ("regulatory_screening", "regulatory_screening_outputs"),
    ("impact_analysis", "impact_analysis_outputs"),
    ("report_synthesis", "report_synthesis_outputs"),
]


@app.get("/api/projects/{project_id}/outputs")
def get_project_outputs(project_id: int):
    conn = _get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, coordinates, description, saved_at "
            "FROM projects WHERE id = %s",
            (project_id,),
        )
        proj = cur.fetchone()
        if not proj:
            cur.close()
            raise HTTPException(status_code=404, detail="Project not found")

        result = {
            "project": {
                "id": proj[0],
                "name": proj[1],
                "coordinates": proj[2],
                "description": proj[3],
                "savedAt": proj[4].isoformat() if proj[4] else None,
            }
        }

        for agent_key, table_name in AGENT_OUTPUT_TABLES:
            cur.execute(
                f'SELECT output, model, input_tokens, output_tokens, cost_usd, saved_at '
                f'FROM "{table_name}" WHERE project_id = %s '
                f'ORDER BY saved_at DESC LIMIT 1',
                (project_id,),
            )
            row = cur.fetchone()
            if row:
                result[agent_key] = {
                    "output": row[0],
                    "model": row[1],
                    "input_tokens": row[2],
                    "output_tokens": row[3],
                    "cost_usd": float(row[4]) if row[4] is not None else None,
                    "savedAt": row[5].isoformat() if row[5] else None,
                }
            else:
                result[agent_key] = None

        cur.close()
        return result
    finally:
        conn.close()
```

- [ ] **Step 2: Smoke test**

Run: `curl http://localhost:5050/api/projects/1/outputs | python -m json.tool`

Expected: JSON with `project` object and 5 agent keys, each containing `output` JSONB + metadata or `null`.

- [ ] **Step 3: Commit**

```bash
git add backend/main.py
git commit -m "feat(api): add GET /api/projects/{id}/outputs endpoint"
```

---

### Task 2: Frontend — EvaluatePanel Stub

**Files:**
- Create: `frontend/src/components/EvaluatePanel.jsx`

- [ ] **Step 1: Create the component**

```jsx
export default function EvaluatePanel() {
  return (
    <div style={styles.container}>
      <div style={styles.label}>EVALUATION</div>
      <p style={styles.hint}>Run evaluation against imported pipeline data</p>
      <button
        style={styles.evalBtn}
        onClick={() => {}}
      >
        EVALUATE
      </button>
    </div>
  )
}

const styles = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    height: '100%',
    gap: '16px',
    padding: '24px',
  },
  label: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    color: 'var(--green-primary)',
    letterSpacing: '3px',
  },
  hint: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--text-muted)',
    textAlign: 'center',
    margin: 0,
  },
  evalBtn: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    letterSpacing: '2px',
    color: '#0a0a0a',
    background: 'var(--green-primary)',
    border: '1px solid var(--green-primary)',
    borderRadius: '4px',
    padding: '10px 28px',
    cursor: 'pointer',
    fontWeight: 600,
  },
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/EvaluatePanel.jsx
git commit -m "feat(frontend): add EvaluatePanel stub component"
```

---

### Task 3: Frontend — RunPreviewPanel

**Files:**
- Create: `frontend/src/components/RunPreviewPanel.jsx`

- [ ] **Step 1: Create the component**

```jsx
import { useEffect, useState } from 'react'

const apiBase = import.meta.env.VITE_API_URL ?? ''

const AGENT_SECTIONS = [
  { key: 'project_parser', label: 'PROJECT PARSE' },
  { key: 'environmental_data', label: 'API CALLS & RESULTS' },
  { key: 'regulatory_screening', label: 'REGULATORY SCREENING' },
  { key: 'impact_analysis', label: 'IMPACT MATRIX' },
  { key: 'report_synthesis', label: 'REPORT SYNTHESIS' },
]

export default function RunPreviewPanel() {
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
    try {
      const res = await fetch(`${apiBase}/api/projects`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setProjects(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoadingProjects(false)
    }
  }

  const handleImport = () => {
    fetchProjects()
    setPickerOpen(true)
  }

  const handleSelect = async (project) => {
    setPickerOpen(false)
    setSelectedProject(project)
    setLoadingOutputs(true)
    setError(null)
    try {
      const res = await fetch(`${apiBase}/api/projects/${project.id}/outputs`)
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

      {/* Project picker dropdown */}
      {pickerOpen && (
        <div style={styles.picker}>
          {loadingProjects ? (
            <div style={styles.pickerItem}>Loading...</div>
          ) : projects.length === 0 ? (
            <div style={styles.pickerItem}>No projects found</div>
          ) : (
            projects.map((p) => (
              <button
                key={p.id}
                style={styles.pickerItem}
                onClick={() => handleSelect(p)}
              >
                <span style={styles.pickerName}>{p.name}</span>
                <span style={styles.pickerMeta}>
                  {p.coordinates} &middot; {new Date(p.savedAt).toLocaleDateString()}
                </span>
              </button>
            ))
          )}
        </div>
      )}

      {error && <div style={styles.error}>Error: {error}</div>}
      {loadingOutputs && <div style={styles.muted}>Loading pipeline outputs...</div>}

      {/* Agent output sections */}
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

/* ── Agent-specific output renderers ──────────────────────────────── */

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
  // data is the parsed_project JSONB — render key-value pairs
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
  // data is a dict of API source keys → results
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
  // data is a list of regulation objects
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
  // data may have .reports[0].sections or be the report object directly
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

/* ── Styles ───────────────────────────────────────────────────────── */

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

  // Key-value (project parser)
  kvRow: { display: 'flex', gap: '12px', padding: '4px 0', borderBottom: '1px solid var(--border)' },
  kvKey: { fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)', minWidth: '120px', textTransform: 'uppercase', letterSpacing: '0.5px' },
  kvVal: { fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-primary)', whiteSpace: 'pre-wrap', wordBreak: 'break-word' },

  // API cards (environmental data)
  apiCard: { marginBottom: '10px', padding: '10px', background: 'var(--bg-secondary)', borderRadius: '4px', border: '1px solid var(--border)' },
  apiSource: { fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--green-primary)', letterSpacing: '1px', marginBottom: '6px', fontWeight: 600 },

  // Regulatory
  regCard: { background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: '4px', padding: '10px', marginBottom: '6px' },
  regName: { fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-primary)', fontWeight: 600, marginBottom: '4px' },
  regDesc: { fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '6px', lineHeight: 1.4 },
  regTag: { fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'var(--green-primary)', background: 'var(--green-dim)', padding: '2px 6px', borderRadius: '3px' },

  // Impact matrix
  matrixTable: { width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: '11px' },
  matrixTh: { textAlign: 'left', padding: '6px 8px', color: 'var(--green-primary)', borderBottom: '1px solid var(--border)', fontSize: '9px', letterSpacing: '1px' },
  matrixTd: { padding: '6px 8px', color: 'var(--text-primary)', borderBottom: '1px solid var(--border)', fontSize: '11px' },

  // Report synthesis
  reportSection: { marginBottom: '8px', border: '1px solid var(--border)', borderRadius: '4px', overflow: 'hidden' },
  reportSectionHead: { fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-primary)', fontWeight: 600, padding: '8px 10px', background: 'var(--bg-secondary)', display: 'flex', gap: '8px' },
  sectionNum: { color: 'var(--green-primary)', fontWeight: 600 },
  reportContent: { fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-secondary)', padding: '10px', lineHeight: 1.5, whiteSpace: 'pre-wrap' },

  // JSON fallback
  jsonSmall: {
    background: '#0a0a0a', border: '1px solid var(--border)', borderRadius: '4px',
    padding: '10px', color: 'var(--green-primary)', fontFamily: 'var(--font-mono)',
    fontSize: '10px', overflow: 'auto', maxHeight: '300px', margin: 0,
  },
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/RunPreviewPanel.jsx
git commit -m "feat(frontend): add RunPreviewPanel with import run + agent output sections"
```

---

### Task 4: Frontend — Integrate Split Pane into EvaluationsView

**Files:**
- Modify: `frontend/src/components/EvaluationsView.jsx`

- [ ] **Step 1: Add imports at top**

Add after the existing import:

```jsx
import RunPreviewPanel from './RunPreviewPanel.jsx'
import EvaluatePanel from './EvaluatePanel.jsx'
```

- [ ] **Step 2: Add resizable split-pane state and handlers**

Inside the `EvaluationsView` function, after the existing `useRef` declarations (around line 47), add:

```jsx
  const [splitPct, setSplitPct] = useState(70)
  const draggingRef = useRef(false)
  const splitContainerRef = useRef(null)

  useEffect(() => {
    const onMouseMove = (e) => {
      if (!draggingRef.current || !splitContainerRef.current) return
      const rect = splitContainerRef.current.getBoundingClientRect()
      const pct = ((e.clientX - rect.left) / rect.width) * 100
      setSplitPct(Math.min(85, Math.max(15, pct)))
    }
    const onMouseUp = () => { draggingRef.current = false }
    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)
    return () => {
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)
    }
  }, [])
```

- [ ] **Step 3: Modify the JSX — change container layout and add split pane**

Replace the outer container `<div style={styles.container}>` through the closing `</div>` (lines 129–211) with:

```jsx
  return (
    <div style={styles.container}>
      <div style={styles.topBar}>
        <button style={styles.backBtn} onClick={onBack}>&larr; BACK</button>
        <span style={styles.pageTitle}>EVALUATIONS</span>
        <span style={styles.docCount}>
          {!loading && !error && `${docs.length} documents`}
        </span>
      </div>

      <div style={styles.body}>
        <div style={styles.uploadZone}>
          <input
            ref={fileRef}
            type="file" accept=".pdf"
            onChange={handleUpload}
            style={{ display: 'none' }}
          />
          <button
            style={styles.uploadBtn}
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
          >
            {uploading ? 'UPLOADING...' : 'UPLOAD EIS PDF'}
          </button>
          <span style={styles.uploadHint}>PDF files up to 25 MB</span>
        </div>

        {error && <div style={styles.error}>Error: {error}</div>}
        {loading && <div style={styles.muted}>Loading...</div>}
        {!loading && docs.length === 0 && (
          <div style={styles.muted}>No evaluation documents uploaded yet.</div>
        )}

        {!loading && docs.length > 0 && (
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>FILENAME</th>
                <th style={styles.th}>SIZE</th>
                <th style={styles.th}>STATUS</th>
                <th style={styles.th}>UPLOADED</th>
                <th style={styles.th}></th>
              </tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id} style={styles.tr}>
                  <td style={styles.td}>
                    <button
                      style={styles.linkBtn}
                      onClick={() => onOpenChunks && onOpenChunks(d.id, d.filename)}
                      disabled={d.status !== 'ready'}
                      title={d.status !== 'ready' ? 'Chunks available once ingest is ready' : 'View chunks'}
                    >
                      {d.filename}
                    </button>
                  </td>
                  <td style={styles.td}>{formatBytes(d.size_bytes)}</td>
                  <td style={styles.td}>
                    <StatusPill doc={d} />
                    <ProgressBar doc={d} />
                  </td>
                  <td style={styles.td}>
                    {new Date(d.uploaded_at).toLocaleDateString()}
                  </td>
                  <td style={styles.td}>
                    {d.status === 'failed' && (
                      <button style={styles.retryBtn} onClick={() => handleRetry(d.id)}>
                        RETRY
                      </button>
                    )}
                    <button style={styles.deleteBtn} onClick={() => handleDelete(d.id)}>
                      DELETE
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* ── Evaluation split pane ──────────────────────────────── */}
      <div style={styles.splitDividerH} />
      <div ref={splitContainerRef} style={styles.splitContainer}>
        <div style={{ ...styles.splitLeft, width: `${splitPct}%` }}>
          <RunPreviewPanel />
        </div>
        <div
          style={styles.splitHandle}
          onMouseDown={() => { draggingRef.current = true }}
        />
        <div style={{ ...styles.splitRight, width: `${100 - splitPct}%` }}>
          <EvaluatePanel />
        </div>
      </div>
    </div>
  )
```

- [ ] **Step 4: Update the styles object**

Change the existing `container` style and add the new split-pane styles. Replace:

```js
  container: { height: '100vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' },
```

with:

```js
  container: { height: '100vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' },
```

(container stays the same)

Then change the `body` style from `flex: 1` to a fixed portion so the split pane gets space:

```js
  body: { flex: 0, padding: '24px', overflowY: 'auto', maxHeight: '40vh' },
```

And add these new styles at the end of the styles object:

```js
  splitDividerH: {
    height: '1px',
    background: 'var(--border)',
    flexShrink: 0,
  },
  splitContainer: {
    flex: 1,
    display: 'flex',
    overflow: 'hidden',
  },
  splitLeft: {
    overflow: 'auto',
    padding: '16px',
  },
  splitHandle: {
    width: '4px',
    background: 'var(--border)',
    cursor: 'col-resize',
    flexShrink: 0,
    transition: 'background 0.15s',
  },
  splitRight: {
    overflow: 'auto',
    padding: '16px',
  },
```

- [ ] **Step 5: Verify in browser**

Open `http://localhost:5173`, navigate to EVALUATIONS. Confirm:
- Upload zone and documents table at top
- Horizontal divider below
- Left panel with IMPORT RUN button, right panel with EVALUATE button
- Dragging the vertical divider resizes the panels
- Clicking IMPORT RUN shows project picker
- Selecting a project loads and displays all 5 agent output sections

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/EvaluationsView.jsx
git commit -m "feat(frontend): integrate resizable split pane into evaluations page"
```

---

### Task 5: Polish — Split Handle Hover Effect

**Files:**
- Modify: `frontend/src/components/EvaluationsView.jsx`

- [ ] **Step 1: Add hover effect to split handle**

The inline `onMouseDown` is already set. Add hover styling by updating the `splitHandle` div to include `onMouseEnter` / `onMouseLeave`:

```jsx
        <div
          style={styles.splitHandle}
          onMouseDown={() => { draggingRef.current = true }}
          onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--green-primary)' }}
          onMouseLeave={(e) => { e.currentTarget.style.background = 'var(--border)' }}
        />
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/EvaluationsView.jsx
git commit -m "feat(frontend): add hover highlight to split pane drag handle"
```
