import { useState } from 'react'
import SourcesModal from './SourcesModal.jsx'

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
      return { ...base, background: 'var(--green-primary)', animation: 'agentPulse 1.2s ease-in-out infinite' }
    case 'complete':
      return { ...base, background: 'var(--green-primary)', boxShadow: '0 0 6px var(--green-primary)' }
    case 'error':
      return { ...base, background: 'var(--red-alert)' }
    case 'pending':
      return { ...base, background: 'var(--yellow-warn)', opacity: 0.6 }
    default:
      return { ...base, background: 'var(--text-muted)' }
  }
}

// ── Shared primitives ──────────────────────────────────────────────────────────

function DataRow({ label, value }) {
  return (
    <div style={s.dataRow}>
      <span style={s.dataLabel}>{label}</span>
      <span style={s.dataValue}>{value ?? '—'}</span>
    </div>
  )
}

function SectionTitle({ children }) {
  return <div style={s.sectionTitle}>{children}</div>
}

function Empty({ msg = 'No data' }) {
  return <div style={s.empty}>{msg}</div>
}

// ── Per-agent formatters ───────────────────────────────────────────────────────

function renderProjectParser(data) {
  if (!data) return <Empty />
  const permits = data.permits_required || []
  return (
    <div style={s.outputBody}>
      <DataRow label="Type" value={data.project_type} />
      <DataRow label="Scale" value={data.scale} />
      <DataRow label="Location" value={data.location} />
      <div style={s.dataRow}>
        <span style={s.dataLabel}>Permits Required</span>
        <div>
          {permits.length === 0
            ? <span style={s.dataValue}>None identified</span>
            : permits.map((p, i) => <div key={i} style={s.bullet}>• {p}</div>)}
        </div>
      </div>
    </div>
  )
}

function renderEnvironmentalData(data) {
  if (!data) return <Empty />
  const usfws = data.usfws_species || {}
  const nwi = data.nwi_wetlands || {}
  const fema = data.fema_flood_zones || {}
  const farmland = data.usda_farmland || {}
  const ej = data.ejscreen || {}

  const sfhaColor = fema.in_sfha ? 'var(--red-alert)' : 'var(--green-primary)'
  const primeColor = farmland.is_prime ? 'var(--yellow-warn)' : 'var(--text-secondary)'

  return (
    <div style={s.outputBody}>
      <SectionTitle>USFWS — Endangered Species</SectionTitle>
      <DataRow label="Species found" value={usfws.count ?? 0} />
      {(usfws.species || []).slice(0, 5).map((sp, i) => (
        <div key={i} style={s.speciesRow}>
          <span style={s.speciesName}>{sp.name}</span>
          {sp.status && <span style={s.speciesStatus}>{sp.status}</span>}
        </div>
      ))}
      {(usfws.count || 0) > 5 && (
        <div style={s.more}>+{usfws.count - 5} more not shown</div>
      )}

      <SectionTitle>NWI — Wetlands</SectionTitle>
      <DataRow label="Features within 1 km" value={nwi.count ?? 0} />
      {(nwi.wetlands || []).slice(0, 4).map((w, i) => (
        <div key={i} style={s.bullet}>
          • {w.type || w.attribute || 'Wetland'}{w.acres != null ? ` — ${w.acres} ac` : ''}
        </div>
      ))}
      {(nwi.count || 0) > 4 && (
        <div style={s.more}>+{nwi.count - 4} more</div>
      )}

      <SectionTitle>FEMA — Flood Hazard</SectionTitle>
      <div style={s.dataRow}>
        <span style={s.dataLabel}>In SFHA</span>
        <span style={{ ...s.dataValue, color: sfhaColor, fontWeight: 600 }}>
          {fema.in_sfha === undefined ? '—' : fema.in_sfha ? 'YES' : 'No'}
        </span>
      </div>
      {(fema.flood_zones || []).length > 0
        ? (fema.flood_zones || []).map((z, i) => (
            <div key={i} style={s.bullet}>
              • Zone {z.flood_zone}{z.zone_subtype ? ` (${z.zone_subtype})` : ''}
            </div>
          ))
        : <div style={s.bullet}>• Zone X (minimal hazard)</div>
      }

      <SectionTitle>USDA — Farmland</SectionTitle>
      {Object.keys(farmland).length === 0
        ? <Empty />
        : <>
            <DataRow label="Class" value={farmland.farmland_class} />
            <DataRow label="Map unit" value={farmland.map_unit} />
            <div style={s.dataRow}>
              <span style={s.dataLabel}>Prime farmland</span>
              <span style={{ ...s.dataValue, color: primeColor, fontWeight: 600 }}>
                {farmland.is_prime === undefined ? '—' : farmland.is_prime ? 'Yes' : 'No'}
              </span>
            </div>
          </>
      }

      <SectionTitle>EJScreen — Demographics</SectionTitle>
      {Object.keys(ej).length === 0
        ? <Empty />
        : <>
            <DataRow label="Census tract" value={ej.census_tract} />
            <DataRow
              label="Minority pop."
              value={ej.minority_pct != null ? `${(ej.minority_pct * 100).toFixed(1)}%` : null}
            />
            <DataRow
              label="Low income"
              value={ej.low_income_pct != null ? `${(ej.low_income_pct * 100).toFixed(1)}%` : null}
            />
            <DataRow label="Source" value={ej.source} />
          </>
      }
    </div>
  )
}

function renderRegulations(regs) {
  if (!Array.isArray(regs) || regs.length === 0) {
    return <Empty msg="No regulations identified (RAG stub)" />
  }
  return (
    <div style={s.outputBody}>
      {regs.map((r, i) => (
        <div key={i} style={s.regBlock}>
          <div style={s.regName}>{r.name}</div>
          {r.jurisdiction && <div style={s.regJurisdiction}>{r.jurisdiction}</div>}
          {r.description && <div style={s.regDesc}>{r.description}</div>}
        </div>
      ))}
    </div>
  )
}

function renderImpactMatrix(matrix) {
  if (!Array.isArray(matrix) || matrix.length === 0) {
    return <Empty msg="No impact matrix generated (LLM stub)" />
  }
  const sigColor = {
    significant: 'var(--red-alert)',
    moderate: 'var(--yellow-warn)',
    minimal: 'var(--green-primary)',
    none: 'var(--text-muted)',
  }
  return (
    <div style={s.outputBody}>
      {matrix.map((row, i) => (
        <div key={i} style={s.matrixRow}>
          <span style={s.matrixCategory}>{row.category}</span>
          <span style={{ ...s.matrixSig, color: sigColor[row.significance] || 'var(--text-muted)' }}>
            {row.significance}
          </span>
          {row.notes && <div style={s.matrixNotes}>{row.notes}</div>}
        </div>
      ))}
    </div>
  )
}

function renderReport(report) {
  if (!report) return <Empty msg="No report generated (stub)" />
  if (typeof report === 'string') return <div style={s.reportText}>{report}</div>
  return <div style={s.outputBody}>{JSON.stringify(report, null, 2)}</div>
}

function renderAgentOutput(agentKey, data) {
  if (data === null || data === undefined) return <Empty />
  switch (agentKey) {
    case 'project_parser':      return renderProjectParser(data)
    case 'environmental_data':  return renderEnvironmentalData(data)
    case 'regulatory_screening': return renderRegulations(data)
    case 'impact_analysis':     return renderImpactMatrix(data)
    case 'report_synthesis':    return renderReport(data)
    default:
      return <pre style={s.fallback}>{JSON.stringify(data, null, 2)}</pre>
  }
}

// ── Component ──────────────────────────────────────────────────────────────────

export default function AgentPipeline({ pipelineState, agentOutputs = {} }) {
  const [openAgent, setOpenAgent] = useState(null)
  const [sourcesOpen, setSourcesOpen] = useState(false)

  const toggleAgent = (key) => {
    setOpenAgent((prev) => (prev === key ? null : key))
  }

  return (
    <div>
      <div style={styles.label}>PIPELINE STATUS</div>
      <div style={styles.list}>
        {AGENTS.map((agent, i) => {
          const status = pipelineState[agent.key] || 'idle'
          const output = agentOutputs[agent.key]
          const isOpen = openAgent === agent.key
          const hasOutput = output !== undefined && output !== null
          const isRegulatory = agent.key === 'regulatory_screening'

          return (
            <div key={agent.key}>
              <div
                style={{
                  ...styles.row,
                  cursor: hasOutput ? 'pointer' : 'default',
                  ...(isOpen ? styles.rowOpen : {}),
                }}
                onClick={() => hasOutput && toggleAgent(agent.key)}
              >
                <span style={getDotStyle(status)} />
                <span style={styles.agentName}>{agent.name}</span>
                {isRegulatory && (
                  <button
                    type="button"
                    style={styles.sourcesBtn}
                    onClick={(e) => {
                      e.stopPropagation()
                      setSourcesOpen(true)
                    }}
                    title="View regulatory source documents"
                  >
                    VIEW SOURCES
                  </button>
                )}
                <span style={styles.statusText}>
                  {status === 'complete' && 'DONE'}
                  {status === 'running' && 'RUNNING'}
                  {status === 'error' && 'ERROR'}
                  {status === 'pending' && 'PENDING'}
                </span>
                {hasOutput && (
                  <span style={styles.chevron}>{isOpen ? '▾' : '▸'}</span>
                )}
              </div>

              {isOpen && hasOutput && (
                <div style={styles.dropdown}>
                  {renderAgentOutput(agent.key, output)}
                </div>
              )}

              {i < AGENTS.length - 1 && (
                <div style={styles.connector} />
              )}
            </div>
          )
        })}
      </div>

      {sourcesOpen && (
        <SourcesModal onClose={() => setSourcesOpen(false)} />
      )}
    </div>
  )
}

// ── Styles ─────────────────────────────────────────────────────────────────────

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
    userSelect: 'none',
    transition: 'border-color 0.15s, background 0.15s',
  },
  rowOpen: {
    borderColor: 'var(--green-primary)',
    borderBottomLeftRadius: 0,
    borderBottomRightRadius: 0,
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
  chevron: {
    fontFamily: 'var(--font-mono)',
    fontSize: '12px',
    color: 'var(--green-primary)',
    flexShrink: 0,
  },
  sourcesBtn: {
    fontFamily: 'var(--font-mono)',
    fontSize: '9px',
    letterSpacing: '1px',
    color: 'var(--green-primary)',
    background: 'transparent',
    border: '1px solid var(--green-primary)',
    borderRadius: '3px',
    padding: '3px 8px',
    cursor: 'pointer',
    flexShrink: 0,
  },
  connector: {
    width: '1px',
    height: '12px',
    background: 'var(--border-active)',
    marginLeft: '20px',
  },
  dropdown: {
    background: 'var(--bg-primary)',
    border: '1px solid var(--green-primary)',
    borderTop: 'none',
    borderBottomLeftRadius: '6px',
    borderBottomRightRadius: '6px',
    maxHeight: '320px',
    overflowY: 'auto',
  },
}

const s = {
  outputBody: {
    padding: '10px 14px',
    display: 'flex',
    flexDirection: 'column',
    gap: '3px',
  },
  sectionTitle: {
    fontFamily: 'var(--font-mono)',
    fontSize: '9px',
    color: 'var(--green-primary)',
    letterSpacing: '2px',
    textTransform: 'uppercase',
    marginTop: '10px',
    marginBottom: '4px',
    borderBottom: '1px solid var(--border)',
    paddingBottom: '3px',
  },
  dataRow: {
    display: 'flex',
    alignItems: 'baseline',
    gap: '8px',
    padding: '1px 0',
  },
  dataLabel: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--text-muted)',
    minWidth: '110px',
    flexShrink: 0,
  },
  dataValue: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    color: 'var(--text-secondary)',
    wordBreak: 'break-word',
  },
  bullet: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--text-secondary)',
    paddingLeft: '8px',
    lineHeight: 1.7,
  },
  speciesRow: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'baseline',
    padding: '1px 8px',
    gap: '8px',
  },
  speciesName: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--text-secondary)',
  },
  speciesStatus: {
    fontFamily: 'var(--font-mono)',
    fontSize: '9px',
    color: 'var(--yellow-warn)',
    flexShrink: 0,
  },
  more: {
    fontFamily: 'var(--font-mono)',
    fontSize: '9px',
    color: 'var(--text-muted)',
    paddingLeft: '8px',
    fontStyle: 'italic',
  },
  regBlock: {
    padding: '6px 0',
    borderBottom: '1px solid var(--border)',
  },
  regName: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    color: 'var(--text-primary)',
    fontWeight: 600,
  },
  regJurisdiction: {
    fontFamily: 'var(--font-mono)',
    fontSize: '9px',
    color: 'var(--text-muted)',
    marginTop: '2px',
  },
  regDesc: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--text-secondary)',
    marginTop: '3px',
    lineHeight: 1.5,
  },
  matrixRow: {
    display: 'flex',
    gap: '10px',
    alignItems: 'baseline',
    padding: '3px 0',
    borderBottom: '1px solid var(--border)',
  },
  matrixCategory: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--text-secondary)',
    flex: 1,
  },
  matrixSig: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    fontWeight: 600,
    flexShrink: 0,
    textTransform: 'uppercase',
  },
  matrixNotes: {
    fontFamily: 'var(--font-mono)',
    fontSize: '9px',
    color: 'var(--text-muted)',
    width: '100%',
    marginTop: '2px',
  },
  reportText: {
    padding: '12px 14px',
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--text-secondary)',
    lineHeight: 1.6,
    whiteSpace: 'pre-wrap',
  },
  empty: {
    padding: '10px 14px',
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--text-muted)',
    fontStyle: 'italic',
  },
  fallback: {
    margin: 0,
    padding: '12px 14px',
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--text-secondary)',
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
  },
}
