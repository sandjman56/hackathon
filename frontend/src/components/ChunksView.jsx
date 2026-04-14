import React, { useEffect, useState } from 'react';

const apiBase = import.meta.env.VITE_API_URL ?? '';

const FILTER_ALL = '__all__';
const PER_PAGE = 25;

function formatLabel(s) {
  if (s.source_type === 'ecfr') {
    return `${s.cfr_title} CFR Part ${s.cfr_part} (ecfr)`;
  }
  return `${s.filename} (${s.source_type || 'pdf_upload'})`;
}

export default function ChunksView({ onBack }) {
  const [sources, setSources] = useState([]);
  const [filter, setFilter] = useState(FILTER_ALL);
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [expanded, setExpanded] = useState(() => new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch(`${apiBase}/api/regulations/sources`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error('list failed'))))
      .then((body) => setSources(body.sources || []))
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (filter === FILTER_ALL) {
      // Fall back to generic table endpoint for "All sources"
      setLoading(true);
      fetch(`${apiBase}/api/db/tables/regulatory_chunks?page=${page}&per_page=${PER_PAGE}`)
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error('load failed'))))
        .then((raw) => {
          // Adapt generic shape to per-source shape so render is uniform
          setData({
            source_id: null,
            page: raw.page,
            per_page: raw.per_page,
            total: raw.total_rows,
            total_pages: raw.total_pages,
            chunks: (raw.rows || []).map((row, idx) => ({
              id: `row-${raw.page}-${idx}`,
              content: row[raw.columns.findIndex((c) => c.name === 'content')] || '',
              metadata: row[raw.columns.findIndex((c) => c.name === 'metadata')] || {},
              citation: null,
              breadcrumb: null,
              token_count: null,
            })),
          });
        })
        .catch((e) => setError(e.message))
        .finally(() => setLoading(false));
      return;
    }
    setLoading(true);
    fetch(`${apiBase}/api/regulations/sources/${filter}/chunks?page=${page}&per_page=${PER_PAGE}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error('load failed'))))
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [filter, page]);

  function toggle(id) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div style={{ fontFamily: 'var(--font-mono)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
        <button type="button" onClick={onBack} aria-label="back">← BACK</button>
        <strong>regulatory_chunks</strong>
        <label htmlFor="src-filter" style={{ marginLeft: 'auto' }}>source:</label>
        <select
          id="src-filter"
          role="combobox"
          value={filter}
          onChange={(e) => { setFilter(e.target.value); setPage(1); setExpanded(new Set()); }}
        >
          <option value={FILTER_ALL}>All sources</option>
          {sources.map((s) => (
            <option key={s.id} value={s.id}>{formatLabel(s)}</option>
          ))}
        </select>
      </div>

      {error && <div role="alert" style={{ color: 'red' }}>{error}</div>}
      {loading && <div>loading…</div>}

      {data && data.chunks.map((ch) => {
        const isOpen = expanded.has(ch.id);
        return (
          <div
            key={ch.id}
            role="row"
            style={{ borderTop: '1px solid var(--border)', padding: '8px 0', cursor: 'pointer' }}
            onClick={() => toggle(ch.id)}
          >
            <div>
              {isOpen ? '▾' : '▸'} {ch.citation || ch.id}
              {ch.breadcrumb ? <span style={{ opacity: 0.7 }}> — {ch.breadcrumb}</span> : null}
              {ch.token_count ? <span style={{ opacity: 0.7 }}> • {ch.token_count} tokens</span> : null}
            </div>
            {isOpen && (
              <pre style={{
                whiteSpace: 'pre-wrap', marginTop: 6, padding: 8,
                background: 'var(--bg-card)', border: '1px solid var(--border)',
              }}>
                {ch.content}
              </pre>
            )}
          </div>
        );
      })}

      {data && data.total_pages > 1 && (
        <div style={{ marginTop: 12, display: 'flex', gap: 8, alignItems: 'center' }}>
          <button type="button" disabled={page <= 1} onClick={() => setPage(page - 1)}>← PREV</button>
          <span>Page {data.page} of {data.total_pages}</span>
          <button type="button" disabled={page >= data.total_pages} onClick={() => setPage(page + 1)}>NEXT →</button>
        </div>
      )}
    </div>
  );
}
