import { useEffect, useRef, useState } from 'react'

const apiBase = import.meta.env.VITE_API_URL ?? ''

const METHODOLOGY_TEXT = `HOW SCORING WORKS
─────────────────────────────────────────

STEP 1 — GROUND TRUTH EXTRACTION (one-time per EIS document)
An LLM reads chunks from the uploaded EIS document and extracts every
environmental resource category with its significance determination
(significant / moderate / minimal / none) and applicable mitigation
types. This runs once and is cached — subsequent evaluations against
the same document reuse the cached result.

STEP 2 — CATEGORY F1 SCORE
The agent is designed to evaluate 8 resource categories:
  wetlands · air_quality · noise · traffic
  environmental_justice · endangered_species · floodplain · prime_farmland

For each category, the agent's determination is compared to ground truth:
  TP: agent flagged it AND EIS confirms a real impact
  FP: agent flagged it BUT EIS says no impact
  FN: EIS has a real impact BUT agent did not flag it
  TN: both agree there is no impact

  Precision = TP / (TP + FP)
  Recall    = TP / (TP + FN)
  F1        = 2 · P · R / (P + R)

Note: EIS categories outside the 8 agent-designed ones are NOT counted
against the F1 score. Only the agent's designed scope is evaluated.

STEP 3 — SIGNIFICANCE ACCURACY
For each matched category, the agent's significance level is compared
to the ground truth using an ordinal scale:
  significant=3, moderate=2, minimal=1, none=0

  Exact match   →  1.0 (full credit)
  Off by 1 level → 0.5 (partial credit)
  Off by 2+     →  0.0

The score is averaged across all matched categories.

STEP 4 — SEMANTIC COVERAGE
Up to 10 agent reasoning snippets are embedded and compared against
stored EIS chunks using cosine similarity. The average max-similarity
measures how well the agent's reasoning aligns with the actual EIS text.
No LLM is used for this step — it uses the existing vector embeddings.

STEP 5 — OVERALL SCORE (weighted average)
  Category F1           × 0.40
  Significance Accuracy × 0.40
  Semantic Coverage     × 0.20`

function InfoModal({ visible }) {
  if (!visible) return null
  return (
    <div style={styles.modal}>
      <div style={styles.modalHeader}>SCORING METHODOLOGY</div>
      <pre style={styles.modalBody}>{METHODOLOGY_TEXT}</pre>
    </div>
  )
}

function InfoButton() {
  const [visible, setVisible] = useState(false)
  const hideTimer = useRef(null)

  const show = () => {
    if (hideTimer.current) { clearTimeout(hideTimer.current); hideTimer.current = null }
    setVisible(true)
  }
  const startHide = () => {
    hideTimer.current = setTimeout(() => setVisible(false), 1000)
  }

  useEffect(() => () => { if (hideTimer.current) clearTimeout(hideTimer.current) }, [])

  return (
    <span style={styles.infoWrap}>
      <button
        style={styles.infoBtn}
        onMouseEnter={show}
        onMouseLeave={startHide}
        aria-label="Scoring methodology"
      >
        ⓘ
      </button>
      <InfoModal visible={visible} />
    </span>
  )
}

function ScoreBar({ value, label }) {
  const pct = Math.round((value ?? 0) * 100)
  return (
    <div style={styles.scoreRow}>
      <span style={styles.scoreLabel}>{label}</span>
      <div style={styles.barOuter}>
        <div style={{ ...styles.barInner, width: `${pct}%` }} />
      </div>
      <span style={styles.scorePct}>{pct}%</span>
    </div>
  )
}

function labelColor(label) {
  switch (label) {
    case 'TP': return 'var(--green-primary)'
    case 'FP': return 'var(--yellow-warn, #b4a347)'
    case 'FN': return 'var(--red-alert)'
    case 'TN': return 'var(--text-muted)'
    default:   return 'var(--text-muted)'
  }
}

function sigColor(sig) {
  switch (sig) {
    case 'significant': return 'var(--red-alert)'
    case 'moderate':    return 'var(--yellow-warn, #b4a347)'
    case 'minimal':     return 'var(--green-primary)'
    case 'none':        return 'var(--text-muted)'
    default:            return 'var(--text-secondary)'
  }
}

function CategoryTable({ perCategory }) {
  const rows = Object.entries(perCategory)
  return (
    <table style={styles.catTable}>
      <thead>
        <tr>
          <th style={styles.catTh}>CATEGORY</th>
          <th style={styles.catTh}>RESULT</th>
          <th style={styles.catTh}>AGENT SIG</th>
          <th style={styles.catTh}>GT SIG</th>
          <th style={styles.catTh}>MATCHED AS</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(([cat, info]) => (
          <tr key={cat} style={styles.catTr}>
            <td style={styles.catTd}>{cat.replace(/_/g, ' ')}</td>
            <td style={{ ...styles.catTd, color: labelColor(info.label), fontWeight: 700 }}>
              {info.label}
            </td>
            <td style={{ ...styles.catTd, color: sigColor(info.agent_significance) }}>
              {info.agent_significance}
            </td>
            <td style={{ ...styles.catTd, color: sigColor(info.gt_significance) }}>
              {info.gt_significance}
            </td>
            <td style={{ ...styles.catTd, color: 'var(--text-muted)', fontSize: '9px' }}>
              {info.gt_matched_name || '—'}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export default function EvaluatePanel({ selectedProject }) {
  const [linkedDocs, setLinkedDocs] = useState([])
  const [loading, setLoading] = useState(false)
  const [scores, setScores] = useState(null)
  const [error, setError] = useState(null)
  const [showDetail, setShowDetail] = useState(false)

  // When project changes: load linked docs + auto-load saved score
  useEffect(() => {
    setScores(null)
    setError(null)
    setLinkedDocs([])
    if (!selectedProject) return

    fetch(`${apiBase}/api/evaluations?project_id=${selectedProject.id}`)
      .then(r => r.json())
      .then(data => setLinkedDocs(data.documents || []))
      .catch(() => {})

    fetch(`${apiBase}/api/evaluations/score/${selectedProject.id}`)
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data) setScores(data) })
      .catch(() => {})
  }, [selectedProject?.id])

  const handleEvaluate = async () => {
    if (!selectedProject) return
    setLoading(true); setError(null); setScores(null)
    try {
      const res = await fetch(`${apiBase}/api/evaluations/score`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: selectedProject.id }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `HTTP ${res.status}`)
      }
      setScores(await res.json())
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const canEvaluate = selectedProject && linkedDocs.length > 0 && !loading
  const detail = scores?.detail || {}
  const perCat  = detail.per_category || {}

  return (
    <div style={styles.container}>
      {/* Header */}
      <div style={styles.header}>
        <span style={styles.title}>EVALUATION</span>
        <InfoButton />
      </div>

      {/* Project info + linked docs */}
      {!selectedProject ? (
        <div style={styles.noProject}>Import a run to evaluate it.</div>
      ) : (
        <div style={styles.projectInfo}>
          <div style={styles.projectInfoRow}>
            <span style={styles.projectInfoLabel}>PROJECT</span>
            <span style={styles.projectInfoVal}>{selectedProject.name}</span>
          </div>
          <div style={styles.projectInfoRow}>
            <span style={styles.projectInfoLabel}>EIS DOCS</span>
            <span style={styles.projectInfoVal}>
              {linkedDocs.length === 0
                ? <span style={styles.noDocsHint}>No linked docs — assign project when uploading.</span>
                : linkedDocs.map(d => (
                    <span key={d.id} style={styles.docPill}>{d.filename}</span>
                  ))
              }
            </span>
          </div>
        </div>
      )}

      <button
        style={{ ...styles.evalBtn, opacity: canEvaluate ? 1 : 0.5, cursor: canEvaluate ? 'pointer' : 'not-allowed' }}
        onClick={handleEvaluate}
        disabled={!canEvaluate}
      >
        {loading ? 'EVALUATING…' : scores ? 'RE-EVALUATE' : 'EVALUATE'}
      </button>

      {error && <div style={styles.error}>Error: {error}</div>}

      {/* Results */}
      {scores && (
        <div style={styles.results}>
          <div style={styles.overallRow}>
            <span style={styles.overallLabel}>OVERALL</span>
            <span style={styles.overallVal}>
              {Math.round((scores.overall_score ?? 0) * 100)}%
            </span>
          </div>

          <ScoreBar value={scores.category_f1}           label="Category F1" />
          <ScoreBar value={scores.category_precision}    label="Precision" />
          <ScoreBar value={scores.category_recall}       label="Recall" />
          <ScoreBar value={scores.significance_accuracy} label="Sig. Accuracy" />
          <ScoreBar value={scores.semantic_coverage}     label="Semantic Cov." />

          {/* Scope note */}
          <div style={styles.scopeNote}>
            ⓘ {detail.scope_note || ''}
          </div>

          <button
            style={styles.toggleDetail}
            onClick={() => setShowDetail(v => !v)}
          >
            {showDetail ? '▾ HIDE BREAKDOWN' : '▸ PER-CATEGORY BREAKDOWN'}
          </button>

          {showDetail && Object.keys(perCat).length > 0 && (
            <CategoryTable perCategory={perCat} />
          )}

          <div style={styles.scoredAt}>
            Scored {scores.scored_at ? new Date(scores.scored_at).toLocaleString() : '—'}
          </div>
        </div>
      )}
    </div>
  )
}

const styles = {
  container: {
    display: 'flex', flexDirection: 'column', height: '100%',
    padding: '16px', overflowY: 'auto', gap: '12px',
  },
  header: { display: 'flex', alignItems: 'center', gap: '8px' },
  title: {
    fontFamily: 'var(--font-mono)', fontSize: '11px',
    color: 'var(--green-primary)', letterSpacing: '3px',
  },

  // Info button + modal
  infoWrap: { position: 'relative', display: 'inline-block' },
  infoBtn: {
    fontFamily: 'var(--font-mono)', fontSize: '13px',
    color: 'var(--text-muted)', background: 'transparent',
    border: 'none', cursor: 'pointer', lineHeight: 1, padding: '0 2px',
  },
  modal: {
    position: 'absolute', top: '24px', left: 0, zIndex: 100,
    width: '420px', maxHeight: '420px', overflowY: 'auto',
    background: 'var(--bg-card)', border: '1px solid var(--border)',
    borderRadius: '6px', boxShadow: '0 4px 24px rgba(0,0,0,0.6)',
    padding: '16px',
  },
  modalHeader: {
    fontFamily: 'var(--font-mono)', fontSize: '10px', letterSpacing: '2px',
    color: 'var(--green-primary)', marginBottom: '12px', fontWeight: 700,
  },
  modalBody: {
    fontFamily: 'var(--font-mono)', fontSize: '10px',
    color: 'var(--text-secondary)', lineHeight: 1.6,
    whiteSpace: 'pre-wrap', margin: 0,
  },

  noProject: {
    fontFamily: 'var(--font-mono)', fontSize: '10px',
    color: 'var(--text-muted)', fontStyle: 'italic', padding: '4px 0',
  },
  projectInfo: {
    display: 'flex', flexDirection: 'column', gap: '6px',
    padding: '10px', background: 'var(--bg-card)',
    border: '1px solid var(--border)', borderRadius: '4px',
  },
  projectInfoRow: { display: 'flex', alignItems: 'flex-start', gap: '10px' },
  projectInfoLabel: {
    fontFamily: 'var(--font-mono)', fontSize: '9px', letterSpacing: '1px',
    color: 'var(--text-muted)', minWidth: '60px', paddingTop: '2px',
  },
  projectInfoVal: {
    fontFamily: 'var(--font-mono)', fontSize: '11px',
    color: 'var(--text-primary)', display: 'flex', flexWrap: 'wrap', gap: '4px',
  },
  noDocsHint: {
    fontFamily: 'var(--font-mono)', fontSize: '9px',
    color: 'var(--text-muted)', fontStyle: 'italic',
  },
  docPill: {
    fontFamily: 'var(--font-mono)', fontSize: '9px',
    color: 'var(--green-primary)', background: 'var(--green-dim)',
    border: '1px solid var(--green-primary)', borderRadius: '3px',
    padding: '1px 6px', display: 'inline-block',
  },

  evalBtn: {
    fontFamily: 'var(--font-mono)', fontSize: '11px', letterSpacing: '2px',
    color: '#0a0a0a', background: 'var(--green-primary)',
    border: '1px solid var(--green-primary)', borderRadius: '4px',
    padding: '10px 28px', fontWeight: 600, alignSelf: 'flex-start',
  },
  error: {
    fontFamily: 'var(--font-mono)', fontSize: '11px',
    color: 'var(--red-alert)', padding: '4px 0',
  },

  // Results
  results: {
    display: 'flex', flexDirection: 'column', gap: '8px',
    borderTop: '1px solid var(--border)', paddingTop: '12px',
  },
  overallRow: { display: 'flex', alignItems: 'baseline', gap: '10px', marginBottom: '4px' },
  overallLabel: {
    fontFamily: 'var(--font-mono)', fontSize: '10px', letterSpacing: '2px',
    color: 'var(--text-muted)',
  },
  overallVal: {
    fontFamily: 'var(--font-mono)', fontSize: '24px', fontWeight: 700,
    color: 'var(--green-primary)',
  },

  scoreRow: { display: 'flex', alignItems: 'center', gap: '8px' },
  scoreLabel: {
    fontFamily: 'var(--font-mono)', fontSize: '9px', letterSpacing: '0.5px',
    color: 'var(--text-muted)', minWidth: '100px',
  },
  barOuter: {
    flex: 1, height: '6px', background: 'var(--border)', borderRadius: '3px', overflow: 'hidden',
  },
  barInner: { height: '100%', background: 'var(--green-primary)', borderRadius: '3px' },
  scorePct: {
    fontFamily: 'var(--font-mono)', fontSize: '10px',
    color: 'var(--text-secondary)', minWidth: '36px', textAlign: 'right',
  },

  scopeNote: {
    fontFamily: 'var(--font-mono)', fontSize: '9px',
    color: 'var(--text-muted)', lineHeight: 1.5,
    borderLeft: '2px solid var(--border)', paddingLeft: '8px',
  },

  toggleDetail: {
    fontFamily: 'var(--font-mono)', fontSize: '9px', letterSpacing: '1px',
    color: 'var(--green-primary)', background: 'transparent',
    border: 'none', cursor: 'pointer', padding: '4px 0', textAlign: 'left',
  },

  // Category breakdown table
  catTable: { width: '100%', borderCollapse: 'collapse', marginTop: '4px' },
  catTh: {
    fontFamily: 'var(--font-mono)', fontSize: '8px', letterSpacing: '1px',
    color: 'var(--text-muted)', textAlign: 'left', padding: '4px 6px',
    borderBottom: '1px solid var(--border)',
  },
  catTr: { borderBottom: '1px solid var(--border)' },
  catTd: {
    fontFamily: 'var(--font-mono)', fontSize: '10px',
    color: 'var(--text-secondary)', padding: '5px 6px',
  },

  scoredAt: {
    fontFamily: 'var(--font-mono)', fontSize: '9px',
    color: 'var(--text-muted)', marginTop: '4px',
  },
}
