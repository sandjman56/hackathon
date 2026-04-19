import React, { useEffect, useState } from 'react';

const apiBase = import.meta.env.VITE_API_URL ?? '';

const FILTER_ALL = '__all__';
const PER_PAGE = 50;

function formatLabel(s) {
  if (s.source_type === 'ecfr') {
    return `${s.cfr_title} CFR Part ${s.cfr_part} (ecfr)`;
  }
  return `${s.filename} (${s.source_type || 'pdf_upload'})`;
}

function truncateCell(val) {
  if (val == null) return 'NULL';
  const s = String(val);
  return s.length > 100 ? s.slice(0, 97) + '...' : s;
}

export default function ChunksView({ onBack }) {
  const [sources, setSources] = useState([]);
  const [filter, setFilter] = useState(FILTER_ALL);
  const [mode, setMode] = useState('chunks'); // 'chunks' | 'full'
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [expanded, setExpanded] = useState(() => new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    fetch(`${apiBase}/api/regulations/sources`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error('list failed'))))
      .then((body) => { if (!cancelled) setSources(body.sources || []); })
      .catch((e) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    let url;
    if (mode === 'full') {
      const params = new URLSearchParams({ page: String(page), per_page: String(PER_PAGE) });
      if (filter !== FILTER_ALL) params.set('source_id', filter);
      url = `${apiBase}/api/db/tables/regulatory_chunks?${params.toString()}`;
    } else if (filter === FILTER_ALL) {
      url = `${apiBase}/api/regulations/chunks?page=${page}&per_page=${PER_PAGE}`;
    } else {
      url = `${apiBase}/api/regulations/sources/${filter}/chunks?page=${page}&per_page=${PER_PAGE}`;
    }

    fetch(url)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error('load failed'))))
      .then((body) => { if (!cancelled) setData(body); })
      .catch((e) => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [filter, page, mode]);

  function toggle(id) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  // Both endpoints share page/total_pages keys; only row-count name differs.
  const totalPages = data?.total_pages;
  const currentPage = data?.page;
  const totalRows = mode === 'full' ? data?.total_rows : data?.total;

  return (
    <div style={styles.container}>
      <div style={styles.topBar}>
        <button type="button" style={styles.backBtn} onClick={onBack} aria-label="back">
          &larr; BACK
        </button>
        <span style={styles.pageTitle}>regulatory_chunks</span>
        {totalRows != null && (
          <span style={styles.rowBadge}>{totalRows} rows</span>
        )}

        <div style={styles.modeToggle} role="tablist" aria-label="view mode">
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'chunks'}
            style={mode === 'chunks' ? styles.modeBtnActive : styles.modeBtn}
            onClick={() => { setMode('chunks'); setPage(1); setExpanded(new Set()); }}
          >
            CHUNKS
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'full'}
            style={mode === 'full' ? styles.modeBtnActive : styles.modeBtn}
            onClick={() => { setMode('full'); setPage(1); setExpanded(new Set()); }}
          >
            FULL TABLE
          </button>
        </div>

        <div style={{ flex: 1 }} />

        <label htmlFor="src-filter" style={styles.filterLabel}>source:</label>
        <select
          id="src-filter"
          style={styles.select}
          value={filter}
          onChange={(e) => { setFilter(e.target.value); setPage(1); setExpanded(new Set()); }}
        >
          <option value={FILTER_ALL}>All sources</option>
          {sources.map((s) => (
            <option key={s.id} value={s.id}>{formatLabel(s)}</option>
          ))}
        </select>
      </div>

      <div style={styles.body}>
        {error && <div role="alert" style={styles.error}>Error: {error}</div>}
        {loading && <div style={styles.muted}>loading…</div>}

        {mode === 'chunks' && data && data.chunks && data.chunks.length === 0 && !loading && (
          <div style={styles.muted}>No chunks.</div>
        )}

        {mode === 'chunks' && data && data.chunks && data.chunks.map((ch, i) => {
          const rowId = ch.id ?? `row-${data.page}-${i}`;
          const isOpen = expanded.has(rowId);
          return (
            <div
              key={rowId}
              role="button"
              tabIndex={0}
              aria-expanded={isOpen}
              style={styles.chunkRow}
              onClick={() => toggle(rowId)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  toggle(rowId);
                }
              }}
            >
              <div style={styles.chunkHeader}>
                <span>
                  {isOpen ? '▾' : '▸'} {ch.citation || rowId}
                  {ch.breadcrumb ? <span style={styles.dim}> — {ch.breadcrumb}</span> : null}
                  {ch.token_count != null ? <span style={styles.dim}> • {ch.token_count} tokens</span> : null}
                </span>
                <span style={ch.embedded ? styles.badgeEmbedded : styles.badgePending}>
                  {ch.embedded ? 'EMBEDDED' : 'PENDING'}
                </span>
              </div>
              {isOpen && (
                <pre style={styles.chunkBody}>{ch.content}</pre>
              )}
            </div>
          );
        })}

        {mode === 'full' && data && data.columns && (
          <div style={styles.tableWrap}>
            <table style={styles.table}>
              <thead>
                <tr>
                  {data.columns.map((col) => (
                    <th key={col.name} style={styles.th}>
                      <div style={styles.colName}>{col.name}</div>
                      <div style={styles.colType}>{col.type}</div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.length === 0 ? (
                  <tr>
                    <td colSpan={data.columns.length} style={styles.emptyCell}>No rows</td>
                  </tr>
                ) : (
                  data.rows.map((row, i) => (
                    <tr key={i} style={i % 2 === 0 ? styles.rowEven : styles.rowOdd}>
                      {row.map((cell, j) => (
                        <td key={j} style={styles.td}>{truncateCell(cell)}</td>
                      ))}
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {data && totalPages > 1 && (
        <div style={styles.pagination}>
          <button
            type="button"
            style={styles.pageBtn}
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
          >
            &larr; PREV
          </button>
          <span style={styles.pageInfo}>Page {currentPage} of {totalPages}</span>
          <button
            type="button"
            style={styles.pageBtn}
            disabled={page >= totalPages}
            onClick={() => setPage((p) => p + 1)}
          >
            NEXT &rarr;
          </button>
        </div>
      )}
    </div>
  );
}

const styles = {
  container: {
    height: '100vh',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
    fontFamily: 'var(--font-mono)',
  },
  topBar: {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
    padding: '12px 24px',
    borderBottom: '1px solid var(--border)',
    background: 'var(--bg-secondary)',
    flexShrink: 0,
  },
  backBtn: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    letterSpacing: '1px',
    color: 'var(--text-secondary)',
    background: 'transparent',
    border: '1px solid var(--border)',
    borderRadius: '4px',
    padding: '6px 12px',
    cursor: 'pointer',
  },
  pageTitle: {
    fontFamily: 'var(--font-mono)',
    fontSize: '14px',
    fontWeight: 600,
    color: 'var(--green-primary)',
    letterSpacing: '2px',
  },
  rowBadge: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--text-muted)',
    padding: '3px 8px',
    border: '1px solid var(--border)',
    borderRadius: '4px',
  },
  modeToggle: {
    display: 'flex',
    gap: '4px',
    marginLeft: '8px',
  },
  modeBtn: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    letterSpacing: '1px',
    color: 'var(--text-secondary)',
    background: 'transparent',
    border: '1px solid var(--border)',
    borderRadius: '4px',
    padding: '6px 12px',
    cursor: 'pointer',
  },
  modeBtnActive: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    letterSpacing: '1px',
    color: 'var(--green-primary)',
    background: 'var(--green-dim)',
    border: '1px solid var(--green-primary)',
    borderRadius: '4px',
    padding: '6px 12px',
    cursor: 'pointer',
  },
  filterLabel: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--text-muted)',
    letterSpacing: '1px',
  },
  select: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    color: 'var(--text-primary)',
    background: 'var(--bg-card)',
    border: '1px solid var(--border)',
    borderRadius: '4px',
    padding: '5px 8px',
  },
  body: {
    flex: 1,
    padding: '20px 24px',
    overflowY: 'auto',
  },
  chunkRow: {
    borderTop: '1px solid var(--border)',
    padding: '10px 0',
    cursor: 'pointer',
  },
  chunkHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: '12px',
  },
  chunkBody: {
    whiteSpace: 'pre-wrap',
    marginTop: 6,
    padding: 8,
    background: 'var(--bg-card)',
    border: '1px solid var(--border)',
  },
  dim: { opacity: 0.7 },
  badgeEmbedded: {
    fontFamily: 'var(--font-mono)',
    fontSize: '9px',
    letterSpacing: '1px',
    color: 'var(--green-primary)',
    background: 'var(--green-dim)',
    border: '1px solid var(--green-primary)',
    borderRadius: '3px',
    padding: '2px 6px',
    flexShrink: 0,
  },
  badgePending: {
    fontFamily: 'var(--font-mono)',
    fontSize: '9px',
    letterSpacing: '1px',
    color: 'var(--text-muted)',
    background: 'transparent',
    border: '1px solid var(--border)',
    borderRadius: '3px',
    padding: '2px 6px',
    flexShrink: 0,
  },
  tableWrap: {
    overflowX: 'auto',
    border: '1px solid var(--border)',
    borderRadius: '6px',
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse',
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
  },
  th: {
    textAlign: 'left',
    padding: '10px 14px',
    background: 'var(--bg-secondary)',
    borderBottom: '1px solid var(--border)',
    position: 'sticky',
    top: 0,
    whiteSpace: 'nowrap',
  },
  colName: {
    color: 'var(--text-primary)',
    fontWeight: 600,
    fontSize: '11px',
  },
  colType: {
    color: 'var(--text-muted)',
    fontSize: '9px',
    marginTop: '2px',
  },
  td: {
    padding: '8px 14px',
    color: 'var(--text-secondary)',
    borderBottom: '1px solid var(--border)',
    whiteSpace: 'nowrap',
    maxWidth: '300px',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  },
  rowEven: { background: 'var(--bg-card)' },
  rowOdd: { background: 'var(--bg-primary)' },
  emptyCell: {
    padding: '20px 14px',
    color: 'var(--text-muted)',
    fontStyle: 'italic',
    textAlign: 'center',
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
  },
  pagination: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '16px',
    padding: '12px 24px',
    borderTop: '1px solid var(--border)',
    background: 'var(--bg-secondary)',
    flexShrink: 0,
  },
  pageBtn: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    letterSpacing: '1px',
    color: 'var(--text-secondary)',
    background: 'transparent',
    border: '1px solid var(--border)',
    borderRadius: '4px',
    padding: '6px 12px',
    cursor: 'pointer',
  },
  pageInfo: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--text-muted)',
  },
  muted: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    color: 'var(--text-muted)',
    fontStyle: 'italic',
    padding: '8px 0',
  },
  error: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    color: 'var(--red-alert)',
    padding: '8px 0',
  },
};
