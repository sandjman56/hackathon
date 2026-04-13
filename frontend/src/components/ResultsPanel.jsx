import { useState } from 'react'

const TABS = ['IMPACT MATRIX', 'REGULATIONS', 'RAW JSON']

export default function ResultsPanel({ results }) {
  const [activeTab, setActiveTab] = useState(0)

  if (!results) {
    return (
      <div>
        <div style={styles.label}>OUTPUT</div>
        <div style={styles.emptyState}>
          <svg
            width="80"
            height="80"
            viewBox="0 0 80 80"
            style={{ opacity: 0.15 }}
          >
            <line x1="40" y1="0" x2="40" y2="80" stroke="var(--green-primary)" strokeWidth="0.5" />
            <line x1="0" y1="40" x2="80" y2="40" stroke="var(--green-primary)" strokeWidth="0.5" />
            <circle cx="40" cy="40" r="20" fill="none" stroke="var(--green-primary)" strokeWidth="0.5" />
            <circle cx="40" cy="40" r="35" fill="none" stroke="var(--green-primary)" strokeWidth="0.3" />
          </svg>
          <span style={styles.emptyText}>Awaiting pipeline execution...</span>
        </div>
      </div>
    )
  }

  const impactMatrix = results.impact_matrix || {}
  const matrixCells = impactMatrix.cells || []
  const matrixActions = impactMatrix.actions || []
  const matrixCategories = impactMatrix.categories || []
  const regulations = results.regulations || []

  return (
    <div>
      <div style={styles.label}>OUTPUT</div>

      {/* Tab bar */}
      <div style={styles.tabBar}>
        {TABS.map((tab, i) => (
          <button
            key={tab}
            onClick={() => setActiveTab(i)}
            style={{
              ...styles.tab,
              ...(activeTab === i ? styles.tabActive : {}),
            }}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div style={styles.tabContent}>
        {activeTab === 0 && (
          <div style={styles.tableWrap}>
            {matrixCells.length === 0 ? (
              <p style={styles.noData}>No impact data available</p>
            ) : (
              <table style={styles.table}>
                <thead>
                  <tr>
                    <th style={styles.th}>Category</th>
                    {matrixActions.map((action, i) => (
                      <th key={i} style={{...styles.th, minWidth: '140px'}}>
                        {action}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {matrixCategories.map((cat, ri) => (
                    <tr
                      key={cat}
                      style={{
                        background: ri % 2 === 0 ? '#161616' : '#111111',
                      }}
                    >
                      <td style={{...styles.td, fontWeight: 600, whiteSpace: 'nowrap'}}>
                        {cat.replace(/_/g, ' ')}
                      </td>
                      {matrixActions.map((action, ci) => {
                        const cell = matrixCells.find(
                          c => c.category === cat && c.action === action
                        )
                        if (!cell) {
                          return (
                            <td key={ci} style={{...styles.td, color: 'var(--text-muted)'}}>
                              —
                            </td>
                          )
                        }
                        const det = cell.determination || {}
                        return (
                          <td key={ci} style={styles.td}>
                            <div style={{
                              color: significanceColor(det.significance),
                              fontWeight: 600,
                              fontSize: '12px',
                            }}>
                              {det.significance}
                              {det.needs_review && (
                                <span style={styles.reviewBadge} title="Flagged for human review">
                                  ⚠
                                </span>
                              )}
                            </div>
                            <div style={{
                              fontSize: '10px',
                              color: 'var(--text-muted)',
                              marginTop: '2px',
                            }}>
                              {Math.round((det.confidence || 0) * 100)}% conf
                            </div>
                            {det.mitigation?.length > 0 && (
                              <div style={{
                                fontSize: '9px',
                                color: 'var(--text-secondary)',
                                marginTop: '2px',
                              }}>
                                {det.mitigation.join(', ')}
                              </div>
                            )}
                            <div style={{
                              fontSize: '10px',
                              color: 'var(--text-secondary)',
                              marginTop: '4px',
                              lineHeight: 1.3,
                            }}>
                              {det.reasoning}
                            </div>
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        {activeTab === 1 && (
          <div>
            {regulations.length === 0 ? (
              <p style={styles.noData}>No regulations identified</p>
            ) : (
              regulations.map((reg, i) => (
                <div key={i} style={styles.regCard}>
                  <div style={styles.regName}>{reg.name}</div>
                  <div style={styles.regDesc}>{reg.description}</div>
                  <span style={styles.regTag}>{reg.jurisdiction}</span>
                </div>
              ))
            )}
          </div>
        )}

        {activeTab === 2 && (
          <pre style={styles.jsonBlock}>
            {JSON.stringify(results, null, 2)}
          </pre>
        )}
      </div>
    </div>
  )
}

function significanceColor(level) {
  switch (level?.toLowerCase()) {
    case 'significant':
      return 'var(--red-alert)'
    case 'moderate':
      return 'var(--yellow-warn)'
    case 'none':
    case 'minimal':
      return 'var(--green-primary)'
    default:
      return 'var(--text-secondary)'
  }
}

const styles = {
  label: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    color: 'var(--green-primary)',
    letterSpacing: '3px',
    marginBottom: '16px',
  },
  emptyState: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '16px',
    padding: '60px 20px',
  },
  emptyText: {
    fontFamily: 'var(--font-mono)',
    fontSize: '12px',
    color: 'var(--text-muted)',
  },
  tabBar: {
    display: 'flex',
    gap: '0',
    borderBottom: '1px solid var(--border)',
    marginBottom: '16px',
  },
  tab: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    color: 'var(--text-secondary)',
    background: 'none',
    border: 'none',
    borderBottom: '2px solid transparent',
    padding: '8px 16px',
    cursor: 'pointer',
    letterSpacing: '1px',
    transition: 'color 0.2s, border-color 0.2s',
  },
  tabActive: {
    color: 'var(--green-primary)',
    borderBottomColor: 'var(--green-primary)',
  },
  tabContent: {
    minHeight: '100px',
  },
  tableWrap: {
    overflowX: 'auto',
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse',
    fontFamily: 'var(--font-mono)',
    fontSize: '12px',
  },
  th: {
    textAlign: 'left',
    padding: '10px 12px',
    color: 'var(--green-primary)',
    borderBottom: '1px solid var(--border)',
    fontSize: '11px',
    letterSpacing: '1px',
  },
  td: {
    padding: '10px 12px',
    color: 'var(--text-primary)',
    borderBottom: '1px solid var(--border)',
  },
  noData: {
    fontFamily: 'var(--font-mono)',
    fontSize: '12px',
    color: 'var(--text-muted)',
    textAlign: 'center',
    padding: '40px',
  },
  reviewBadge: {
    marginLeft: '4px',
    fontSize: '11px',
    cursor: 'help',
  },
  regCard: {
    background: 'var(--bg-card)',
    border: '1px solid var(--border)',
    borderRadius: '6px',
    padding: '16px',
    marginBottom: '10px',
  },
  regName: {
    fontFamily: 'var(--font-mono)',
    fontSize: '13px',
    color: 'var(--text-primary)',
    fontWeight: 600,
    marginBottom: '6px',
  },
  regDesc: {
    fontSize: '12px',
    color: 'var(--text-secondary)',
    marginBottom: '10px',
    lineHeight: 1.5,
  },
  regTag: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--green-primary)',
    background: 'var(--green-dim)',
    padding: '3px 8px',
    borderRadius: '3px',
    letterSpacing: '1px',
  },
  jsonBlock: {
    background: '#0a0a0a',
    border: '1px solid var(--border)',
    borderRadius: '6px',
    padding: '16px',
    color: 'var(--green-primary)',
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    overflow: 'auto',
    maxHeight: '300px',
    margin: 0,
  },
}
