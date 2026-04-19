import { useState } from 'react'
import ReactMarkdown from 'react-markdown'

const TABS = ['IMPACT MATRIX', 'REGULATIONS', 'REPORT', 'RAW JSON']

export default function ResultsPanel({ results }) {
  const [activeTab, setActiveTab] = useState(0)
  const [downloading, setDownloading] = useState(null)

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

  // Report data
  const reportData = results.report || {}
  const reportObj = (reportData.reports || [])[0] || null
  const reportSections = reportObj?.sections || []
  const reportMeta = reportObj?.metadata || {}
  const disclaimerItems = reportObj?.disclaimer_items || []

  const handleDownload = async (format) => {
    const apiBase = import.meta.env.VITE_API_URL ?? ''
    setDownloading(format)
    try {
      const resp = await fetch(`${apiBase}/api/export/${format}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(reportData),
      })
      if (!resp.ok) throw new Error(`Export failed: ${resp.status}`)
      const blob = await resp.blob()
      const ext = format === 'pdf' ? 'pdf' : 'tex'
      const name = `${results.project_name || 'EIA_Report'}.${ext}`
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = name.replace(/\s+/g, '_')
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      console.error(`${format} export error:`, err)
    } finally {
      setDownloading(null)
    }
  }

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
          <ReportTab
            reportObj={reportObj}
            reportSections={reportSections}
            reportMeta={reportMeta}
            disclaimerItems={disclaimerItems}
            reportStage={reportData.stage}
            downloading={downloading}
            onDownload={handleDownload}
          />
        )}

        {activeTab === 3 && (
          <pre style={styles.jsonBlock}>
            {JSON.stringify(results, null, 2)}
          </pre>
        )}
      </div>
    </div>
  )
}

/* ── Report Tab Component ─────────────────────────────────────────── */

function ReportTab({ reportObj, reportSections, reportMeta, disclaimerItems, reportStage, downloading, onDownload }) {
  if (!reportObj) {
    return <p style={styles.noData}>No report generated</p>
  }

  return (
    <div>
      {/* Download buttons */}
      <div style={styles.downloadBar}>
        <button
          style={{
            ...styles.downloadBtn,
            opacity: downloading ? 0.5 : 1,
          }}
          disabled={!!downloading}
          onClick={() => onDownload('pdf')}
        >
          {downloading === 'pdf' ? 'Generating...' : 'Download PDF'}
        </button>
        <button
          style={{
            ...styles.downloadBtn,
            ...styles.downloadBtnOutline,
            opacity: downloading ? 0.5 : 1,
          }}
          disabled={!!downloading}
          onClick={() => onDownload('latex')}
        >
          {downloading === 'latex' ? 'Generating...' : 'Download LaTeX'}
        </button>
        <span style={styles.reportBadge}>
          {reportObj.framework_id} {reportObj.document_type}
        </span>
      </div>

      {/* Metadata bar */}
      <div style={styles.metaBar}>
        <span style={styles.metaItem}>
          Model: {reportMeta.llm_model_used || 'N/A'}
        </span>
        <span style={styles.metaDot} />
        <span style={styles.metaItem}>
          {reportMeta.total_llm_calls || 0} LLM calls
        </span>
        <span style={styles.metaDot} />
        <span style={styles.metaItem}>
          {(reportMeta.total_tokens_used || 0).toLocaleString()} tokens
        </span>
        {reportMeta.human_review_count > 0 && (
          <>
            <span style={styles.metaDot} />
            <span style={{ ...styles.metaItem, color: 'var(--yellow-warn)' }}>
              {reportMeta.human_review_count} items need review
            </span>
          </>
        )}
      </div>

      {/* Sections */}
      {reportSections.map((section, i) => (
        <div key={i} style={styles.reportSection}>
          <div style={styles.sectionHeader}>
            <span style={styles.sectionNumber}>{section.section_number}</span>
            <span style={styles.sectionTitle}>{section.section_title}</span>
            {section.requires_llm && (
              <span style={styles.llmTag}>LLM</span>
            )}
          </div>
          <div style={styles.sectionContent}>
            <ReactMarkdown components={markdownComponents}>
              {section.content || '*No content*'}
            </ReactMarkdown>
          </div>
          {section.low_confidence_highlights?.length > 0 && (
            <div style={styles.highlightsBox}>
              <div style={styles.highlightsTitle}>Low Confidence Items</div>
              {section.low_confidence_highlights.map((h, j) => (
                <div key={j} style={styles.highlightItem}>
                  <span style={styles.highlightConf}>
                    {Math.round((h.confidence || 0) * 100)}%
                  </span>
                  <span style={styles.highlightText}>{h.text_excerpt}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}

      {/* Disclaimer items */}
      {disclaimerItems.length > 0 && (
        <div style={styles.disclaimerBox}>
          <div style={styles.disclaimerTitle}>Items Requiring Human Review</div>
          {disclaimerItems.map((item, i) => (
            <div key={i} style={styles.disclaimerItem}>
              <div style={styles.disclaimerCategory}>
                {item.category?.replace(/_/g, ' ')}
                <span style={{
                  color: significanceColor(item.determination),
                  marginLeft: '8px',
                  fontSize: '11px',
                }}>
                  {item.determination}
                </span>
                <span style={styles.disclaimerConf}>
                  {Math.round((item.confidence || 0) * 100)}% confidence
                </span>
              </div>
              {item.reasoning && (
                <div style={styles.disclaimerReasoning}>{item.reasoning}</div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* ── Markdown component overrides for dark theme ──────────────────── */

const markdownComponents = {
  h1: ({ children }) => <h1 style={{ color: 'var(--green-primary)', fontSize: '16px', fontFamily: 'var(--font-mono)', margin: '16px 0 8px', letterSpacing: '1px' }}>{children}</h1>,
  h2: ({ children }) => <h2 style={{ color: 'var(--green-primary)', fontSize: '14px', fontFamily: 'var(--font-mono)', margin: '14px 0 6px', letterSpacing: '1px' }}>{children}</h2>,
  h3: ({ children }) => <h3 style={{ color: 'var(--text-primary)', fontSize: '13px', fontFamily: 'var(--font-mono)', margin: '12px 0 4px' }}>{children}</h3>,
  p: ({ children }) => <p style={{ color: 'var(--text-secondary)', fontSize: '12px', lineHeight: 1.7, margin: '0 0 10px' }}>{children}</p>,
  strong: ({ children }) => <strong style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{children}</strong>,
  em: ({ children }) => <em style={{ color: 'var(--text-secondary)', fontStyle: 'italic' }}>{children}</em>,
  ul: ({ children }) => <ul style={{ color: 'var(--text-secondary)', fontSize: '12px', lineHeight: 1.7, paddingLeft: '20px', margin: '4px 0 10px' }}>{children}</ul>,
  ol: ({ children }) => <ol style={{ color: 'var(--text-secondary)', fontSize: '12px', lineHeight: 1.7, paddingLeft: '20px', margin: '4px 0 10px' }}>{children}</ol>,
  li: ({ children }) => <li style={{ marginBottom: '2px' }}>{children}</li>,
  blockquote: ({ children }) => <blockquote style={{ borderLeft: '2px solid var(--green-primary)', paddingLeft: '12px', margin: '8px 0', color: 'var(--text-secondary)', fontSize: '12px' }}>{children}</blockquote>,
  table: ({ children }) => <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: '11px', margin: '8px 0' }}>{children}</table>,
  th: ({ children }) => <th style={{ textAlign: 'left', padding: '6px 8px', color: 'var(--green-primary)', borderBottom: '1px solid var(--border)', fontSize: '10px', letterSpacing: '1px' }}>{children}</th>,
  td: ({ children }) => <td style={{ padding: '6px 8px', color: 'var(--text-primary)', borderBottom: '1px solid var(--border)' }}>{children}</td>,
  code: ({ children }) => <code style={{ background: '#0a0a0a', color: 'var(--green-primary)', padding: '1px 4px', borderRadius: '3px', fontFamily: 'var(--font-mono)', fontSize: '11px' }}>{children}</code>,
  hr: () => <hr style={{ border: 'none', borderTop: '1px solid var(--border)', margin: '12px 0' }} />,
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
  // Report tab styles
  downloadBar: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    marginBottom: '16px',
  },
  downloadBtn: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    letterSpacing: '1px',
    color: '#0a0a0a',
    background: 'var(--green-primary)',
    border: '1px solid var(--green-primary)',
    borderRadius: '4px',
    padding: '6px 14px',
    cursor: 'pointer',
    fontWeight: 600,
  },
  downloadBtnOutline: {
    color: 'var(--green-primary)',
    background: 'transparent',
  },
  reportBadge: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--green-primary)',
    background: 'var(--green-dim)',
    padding: '4px 10px',
    borderRadius: '3px',
    letterSpacing: '1px',
    marginLeft: 'auto',
  },
  metaBar: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    padding: '8px 12px',
    background: 'var(--bg-card)',
    border: '1px solid var(--border)',
    borderRadius: '4px',
    marginBottom: '16px',
    flexWrap: 'wrap',
  },
  metaItem: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--text-secondary)',
  },
  metaDot: {
    width: '3px',
    height: '3px',
    borderRadius: '50%',
    background: 'var(--text-muted)',
  },
  reportSection: {
    marginBottom: '16px',
    border: '1px solid var(--border)',
    borderRadius: '6px',
    overflow: 'hidden',
  },
  sectionHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
    padding: '10px 14px',
    background: 'var(--bg-card)',
    borderBottom: '1px solid var(--border)',
  },
  sectionNumber: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    color: 'var(--green-primary)',
    fontWeight: 600,
    minWidth: '24px',
  },
  sectionTitle: {
    fontFamily: 'var(--font-mono)',
    fontSize: '12px',
    color: 'var(--text-primary)',
    fontWeight: 600,
    letterSpacing: '0.5px',
  },
  llmTag: {
    fontFamily: 'var(--font-mono)',
    fontSize: '9px',
    color: 'var(--green-primary)',
    background: 'var(--green-dim)',
    padding: '2px 6px',
    borderRadius: '3px',
    letterSpacing: '1px',
    marginLeft: 'auto',
  },
  sectionContent: {
    padding: '12px 14px',
  },
  highlightsBox: {
    margin: '0 14px 12px',
    padding: '10px 12px',
    background: '#1a1400',
    border: '1px solid #3d3000',
    borderRadius: '4px',
  },
  highlightsTitle: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--yellow-warn)',
    letterSpacing: '1px',
    marginBottom: '8px',
    fontWeight: 600,
  },
  highlightItem: {
    display: 'flex',
    alignItems: 'baseline',
    gap: '8px',
    marginBottom: '4px',
  },
  highlightConf: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--yellow-warn)',
    fontWeight: 600,
    minWidth: '30px',
  },
  highlightText: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--text-secondary)',
  },
  disclaimerBox: {
    padding: '14px',
    background: '#1a0a0a',
    border: '1px solid #3d1010',
    borderRadius: '6px',
    marginTop: '8px',
  },
  disclaimerTitle: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    color: 'var(--red-alert)',
    letterSpacing: '1px',
    marginBottom: '12px',
    fontWeight: 600,
  },
  disclaimerItem: {
    marginBottom: '10px',
    paddingBottom: '10px',
    borderBottom: '1px solid #2a1010',
  },
  disclaimerCategory: {
    fontFamily: 'var(--font-mono)',
    fontSize: '12px',
    color: 'var(--text-primary)',
    fontWeight: 600,
  },
  disclaimerConf: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--text-muted)',
    marginLeft: '8px',
  },
  disclaimerReasoning: {
    fontSize: '11px',
    color: 'var(--text-secondary)',
    marginTop: '4px',
    lineHeight: 1.5,
  },
}
