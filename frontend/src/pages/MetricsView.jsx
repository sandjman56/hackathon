import { useEffect, useState } from 'react'

const apiBase = import.meta.env.VITE_API_URL ?? ''

const AGENT_ORDER = [
  'project_parser',
  'environmental_data',
  'regulatory_screening',
  'impact_analysis',
  'report_synthesis',
]
const AGENT_LABELS = {
  project_parser: 'PROJECT PARSER',
  environmental_data: 'ENV DATA',
  regulatory_screening: 'REG SCREENING',
  impact_analysis: 'IMPACT ANALYSIS',
  report_synthesis: 'REPORT SYNTH',
}

function formatCost(usd) {
  if (usd == null || usd === 0) return '—'
  if (usd < 0.0001) return '<$0.0001'
  if (usd >= 1) return `$${usd.toFixed(2)}`
  return `$${usd.toFixed(4)}`
}
function formatDuration(ms) {
  if (ms == null || ms === 0) return '—'
  return (ms / 1000).toFixed(1) + 's'
}
function formatTokens(n) {
  if (n == null) return '—'
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return String(n)
}

function BarChart({ data, formatValue }) {
  if (!data || data.length === 0 || data.every((d) => !d.value)) {
    return (
      <div style={{ color: 'var(--text-muted)', fontSize: '12px', padding: '12px 0' }}>
        No data yet — run the pipeline and save results.
      </div>
    )
  }
  const maxVal = Math.max(...data.map((d) => d.value || 0), 0.0001)
  const BAR_W = 48, GAP = 14, CHART_H = 100, LABEL_H = 46
  const totalW = data.length * (BAR_W + GAP)
  return (
    <svg width={totalW} height={CHART_H + LABEL_H} style={{ overflow: 'visible' }}>
      {data.map((d, i) => {
        const val = d.value || 0
        const barH = Math.max((val / maxVal) * CHART_H, 2)
        const x = i * (BAR_W + GAP)
        const y = CHART_H - barH
        const words = AGENT_LABELS[d.agent].split(' ')
        return (
          <g key={d.agent}>
            <rect x={x} y={y} width={BAR_W} height={barH} fill="var(--green-primary)" opacity={0.8} rx={2} />
            <text x={x + BAR_W / 2} y={y - 5} textAnchor="middle" fill="var(--green-primary)" fontSize={9} fontFamily="var(--font-mono)">
              {formatValue(val)}
            </text>
            {words.map((word, wi) => (
              <text key={wi} x={x + BAR_W / 2} y={CHART_H + 14 + wi * 11} textAnchor="middle" fill="var(--text-muted)" fontSize={8} fontFamily="var(--font-mono)">
                {word}
              </text>
            ))}
          </g>
        )
      })}
    </svg>
  )
}

export default function MetricsView({ metric, onBack }) {
  const isCost = metric === 'cost'

  const [overview, setOverview] = useState(null)
  const [runs, setRuns] = useState([])
  const [pricing, setPricing] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedProjectId, setSelectedProjectId] = useState(null)
  const [selectedRunId, setSelectedRunId] = useState(null)
  const [runDetail, setRunDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)

  useEffect(() => {
    Promise.all([
      fetch(`${apiBase}/api/metrics/overview`).then((r) => r.json()),
      fetch(`${apiBase}/api/metrics/runs`).then((r) => r.json()),
      fetch(`${apiBase}/api/metrics/pricing`).then((r) => r.json()),
    ])
      .then(([ov, runsData, pricingData]) => {
        setOverview(ov)
        setRuns(runsData)
        setPricing(pricingData)
        setLoading(false)
      })
      .catch((e) => { setError(e.message); setLoading(false) })
  }, [])

  useEffect(() => {
    if (!selectedRunId) { setRunDetail(null); return }
    setDetailLoading(true)
    fetch(`${apiBase}/api/metrics/runs/${selectedRunId}`)
      .then((r) => r.json())
      .then((d) => { setRunDetail(d); setDetailLoading(false) })
      .catch(() => setDetailLoading(false))
  }, [selectedRunId])

  const chartData = AGENT_ORDER.map((agent) => {
    const entries = (overview?.per_agent || []).filter((a) => a.agent === agent)
    if (!entries.length) return { agent, value: 0 }
    const totalRuns = entries.reduce((s, e) => s + e.run_count, 0)
    const weighted = entries.reduce((s, e) => s + (isCost ? e.avg_cost_usd : e.avg_duration_ms) * e.run_count, 0)
    return { agent, value: totalRuns > 0 ? weighted / totalRuns : 0 }
  })

  const projectOptions = Array.from(
    runs.reduce((map, r) => {
      map.set(r.project_id, r.project_name || `Project ${r.project_id}`)
      return map
    }, new Map())
  ).map(([id, name]) => ({ id, name }))

  const projectRuns = selectedProjectId
    ? runs.filter((r) => r.project_id === selectedProjectId)
    : []

  const s = {
    wrap: { padding: '24px 32px', fontFamily: 'var(--font-mono)', color: 'var(--text)', maxWidth: '1100px', margin: '0 auto' },
    backBtn: { background: 'transparent', border: '1px solid var(--border)', color: 'var(--text-muted)', padding: '4px 10px', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: '11px', letterSpacing: '0.05em', marginBottom: '20px', borderRadius: '3px' },
    title: { fontSize: '13px', letterSpacing: '0.12em', color: 'var(--green-primary)', marginBottom: '24px' },
    card: { background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: '6px', padding: '20px 24px', marginBottom: '20px' },
    sectionLabel: { fontSize: '10px', letterSpacing: '0.15em', color: 'var(--text-muted)', marginBottom: '16px' },
    statsRow: { display: 'flex', gap: '32px', marginBottom: '24px', flexWrap: 'wrap' },
    statBox: { display: 'flex', flexDirection: 'column', gap: '4px' },
    statValue: { fontSize: '22px', color: 'var(--green-primary)', letterSpacing: '-0.02em' },
    statLabel: { fontSize: '10px', color: 'var(--text-muted)', letterSpacing: '0.08em' },
    table: { width: '100%', borderCollapse: 'collapse', fontSize: '12px' },
    th: { textAlign: 'left', padding: '6px 10px', borderBottom: '1px solid var(--border)', color: 'var(--text-muted)', fontSize: '10px', letterSpacing: '0.1em' },
    td: { padding: '7px 10px', borderBottom: '1px solid var(--border)', color: 'var(--text-primary)' },
    select: { background: 'var(--bg-card)', border: '1px solid var(--border)', color: 'var(--text-primary)', padding: '5px 10px', fontFamily: 'var(--font-mono)', fontSize: '11px', cursor: 'pointer', borderRadius: '3px', marginRight: '10px' },
    muted: { color: 'var(--text-muted)', fontSize: '12px', padding: '12px 0' },
  }

  if (loading) return <div style={s.wrap}><div style={s.muted}>LOADING...</div></div>
  if (error) return <div style={s.wrap}><div style={{ ...s.muted, color: 'var(--red-alert)' }}>ERROR: {error}</div></div>

  const totals = overview?.totals || {}
  const perModel = overview?.per_model || []

  return (
    <div style={s.wrap}>
      <button style={s.backBtn} onClick={onBack}>← BACK</button>
      <div style={s.title}>{isCost ? '// COST ANALYSIS' : '// LATENCY ANALYSIS'}</div>

      {/* Overview */}
      <div style={s.card}>
        <div style={s.sectionLabel}>OVERVIEW — ALL RUNS</div>
        <div style={s.statsRow}>
          <div style={s.statBox}>
            <span style={s.statValue}>
              {isCost ? formatCost(totals.total_cost_usd) : formatDuration(totals.total_duration_ms)}
            </span>
            <span style={s.statLabel}>{isCost ? 'TOTAL COST' : 'TOTAL COMPUTE'}</span>
          </div>
          <div style={s.statBox}>
            <span style={s.statValue}>
              {isCost ? formatCost(totals.avg_cost_per_run) : formatDuration(totals.avg_duration_per_run_ms)}
            </span>
            <span style={s.statLabel}>AVG PER RUN</span>
          </div>
          <div style={s.statBox}>
            <span style={s.statValue}>{totals.total_runs || 0}</span>
            <span style={s.statLabel}>TOTAL RUNS</span>
          </div>
        </div>
        <div style={{ fontSize: '10px', color: 'var(--text-muted)', letterSpacing: '0.1em', marginBottom: '12px' }}>
          AVG {isCost ? 'COST' : 'DURATION'} PER AGENT
        </div>
        <div style={{ overflowX: 'auto', paddingBottom: '8px' }}>
          <BarChart data={chartData} formatValue={isCost ? formatCost : formatDuration} />
        </div>
      </div>

      {/* Model breakdown (cost only) */}
      {isCost && perModel.length > 0 && (
        <div style={s.card}>
          <div style={s.sectionLabel}>MODEL BREAKDOWN</div>
          <table style={s.table}>
            <thead>
              <tr>
                <th style={s.th}>MODEL</th>
                <th style={s.th}>INPUT $/1M</th>
                <th style={s.th}>OUTPUT $/1M</th>
                <th style={s.th}>INPUT TOKENS</th>
                <th style={s.th}>OUTPUT TOKENS</th>
                <th style={s.th}>TOTAL COST</th>
              </tr>
            </thead>
            <tbody>
              {perModel.map((m) => {
                const p = pricing[m.model] || {}
                return (
                  <tr key={m.model}>
                    <td style={s.td}>{p.label || m.model}</td>
                    <td style={s.td}>{p.input_per_1m != null ? `$${p.input_per_1m.toFixed(2)}` : '—'}</td>
                    <td style={s.td}>{p.output_per_1m != null ? `$${p.output_per_1m.toFixed(2)}` : '—'}</td>
                    <td style={s.td}>{formatTokens(m.total_input_tokens)}</td>
                    <td style={s.td}>{formatTokens(m.total_output_tokens)}</td>
                    <td style={{ ...s.td, color: 'var(--green-primary)' }}>{formatCost(m.total_cost_usd)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Run drill-down */}
      <div style={s.card}>
        <div style={s.sectionLabel}>RUN DRILL-DOWN</div>
        <div style={{ marginBottom: '16px' }}>
          <select
            style={s.select}
            value={selectedProjectId ?? ''}
            onChange={(e) => {
              setSelectedProjectId(e.target.value ? Number(e.target.value) : null)
              setSelectedRunId(null)
            }}
          >
            <option value="">— select project —</option>
            {projectOptions.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
          {selectedProjectId && (
            <select
              style={s.select}
              value={selectedRunId ?? ''}
              onChange={(e) => setSelectedRunId(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">— select run —</option>
              {projectRuns.map((r) => (
                <option key={r.id} value={r.id}>
                  Run #{r.id} —{' '}
                  {r.started_at
                    ? new Date(r.started_at).toLocaleString()
                    : new Date(r.finished_at || Date.now()).toLocaleString()}
                </option>
              ))}
            </select>
          )}
        </div>

        {detailLoading && <div style={s.muted}>Loading...</div>}
        {!selectedRunId && !detailLoading && (
          <div style={s.muted}>Select a project and run to see the per-agent breakdown.</div>
        )}

        {runDetail && !detailLoading && (
          <>
            <div style={{ marginBottom: '12px', fontSize: '11px', color: 'var(--text-muted)' }}>
              {runDetail.run.project_name} · Total:{' '}
              <span style={{ color: 'var(--green-primary)' }}>
                {isCost
                  ? formatCost(runDetail.run.total_cost_usd)
                  : formatDuration(runDetail.run.total_duration_ms)}
              </span>
            </div>
            <table style={s.table}>
              <thead>
                <tr>
                  <th style={s.th}>AGENT</th>
                  <th style={s.th}>MODEL</th>
                  {isCost ? (
                    <>
                      <th style={s.th}>INPUT</th>
                      <th style={s.th}>OUTPUT</th>
                      <th style={s.th}>COST</th>
                    </>
                  ) : (
                    <th style={s.th}>DURATION</th>
                  )}
                </tr>
              </thead>
              <tbody>
                {AGENT_ORDER.map((key) => {
                  const a = runDetail.agents.find((x) => x.agent === key)
                  return (
                    <tr key={key}>
                      <td style={s.td}>{AGENT_LABELS[key]}</td>
                      <td style={{ ...s.td, color: 'var(--text-muted)' }}>{a?.model || '—'}</td>
                      {isCost ? (
                        <>
                          <td style={s.td}>{a ? formatTokens(a.input_tokens) : '—'}</td>
                          <td style={s.td}>{a ? formatTokens(a.output_tokens) : '—'}</td>
                          <td style={{ ...s.td, color: 'var(--green-primary)' }}>{a ? formatCost(a.cost_usd) : '—'}</td>
                        </>
                      ) : (
                        <td style={{ ...s.td, color: 'var(--green-primary)' }}>{a ? formatDuration(a.duration_ms) : '—'}</td>
                      )}
                    </tr>
                  )
                })}
                <tr>
                  <td colSpan={2} style={{ ...s.td, color: 'var(--text-muted)', fontSize: '10px', letterSpacing: '0.08em' }}>TOTAL</td>
                  {isCost ? (
                    <>
                      <td style={s.td}>{formatTokens(runDetail.run.total_input_tokens)}</td>
                      <td style={s.td}>{formatTokens(runDetail.run.total_output_tokens)}</td>
                      <td style={{ ...s.td, color: 'var(--green-primary)' }}>{formatCost(runDetail.run.total_cost_usd)}</td>
                    </>
                  ) : (
                    <td style={{ ...s.td, color: 'var(--green-primary)' }}>{formatDuration(runDetail.run.total_duration_ms)}</td>
                  )}
                </tr>
              </tbody>
            </table>
          </>
        )}
      </div>
    </div>
  )
}
