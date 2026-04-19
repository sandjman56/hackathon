import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import ChunksView from './ChunksView';

const sourcesPayload = {
  sources: [
    { id: 's1', filename: 'title-36_part-800.xml', source_type: 'ecfr',
      cfr_title: 36, cfr_part: '800', effective_date: null,
      chunk_count: 2, status: 'ready' },
    { id: 's2', filename: 'NEPA.pdf', source_type: 'pdf_upload',
      cfr_title: null, cfr_part: null, effective_date: null,
      chunk_count: 5, status: 'ready' },
  ]
};

const chunksPayloadS1 = {
  source_id: 's1', page: 1, per_page: 50, total: 2, total_pages: 1,
  chunks: [
    { id: 'c1', content: 'First chunk body…',
      citation: '36 CFR §800.1', breadcrumb: 'Part 800 > Purpose',
      token_count: 500, metadata: {}, embedded: true },
    { id: 'c2', content: 'Second chunk body…',
      citation: '36 CFR §800.2', breadcrumb: 'Part 800 > Participants',
      token_count: 420, metadata: {}, embedded: false },
  ],
};

const chunksPayloadAll = {
  source_id: null, page: 1, per_page: 50, total: 1, total_pages: 1,
  chunks: [
    { id: 'ca', content: 'Cross-source chunk…',
      citation: '36 CFR §800.1', breadcrumb: null, token_count: null,
      metadata: {}, source_id: 's1', embedded: true },
  ],
};

const fullTablePayload = {
  page: 1, per_page: 50, total_rows: 1, total_pages: 1,
  columns: [
    { name: 'id', type: 'uuid' },
    { name: 'embedding', type: 'USER-DEFINED' },
    { name: 'content', type: 'text' },
    { name: 'breadcrumb', type: 'text' },
    { name: 'metadata', type: 'jsonb' },
    { name: 'source_id', type: 'uuid' },
    { name: 'created_at', type: 'timestamp with time zone' },
  ],
  rows: [
    ['row-uuid', '[0,0,0]', 'full content', 'bc', '{}', 's1', '2026-04-14'],
  ],
};

beforeEach(() => {
  global.fetch = vi.fn((url) => {
    if (url.endsWith('/api/regulations/sources')) {
      return Promise.resolve({ ok: true, json: async () => sourcesPayload });
    }
    if (url.includes('/api/regulations/sources/s1/chunks')) {
      return Promise.resolve({ ok: true, json: async () => chunksPayloadS1 });
    }
    if (url.includes('/api/regulations/chunks')) {
      return Promise.resolve({ ok: true, json: async () => chunksPayloadAll });
    }
    if (url.includes('/api/db/tables/regulatory_chunks')) {
      return Promise.resolve({ ok: true, json: async () => fullTablePayload });
    }
    return Promise.reject(new Error('unexpected fetch: ' + url));
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ChunksView', () => {
  it('populates the source dropdown from /api/regulations/sources', async () => {
    render(<ChunksView onBack={() => {}} />);
    await waitFor(() => {
      expect(screen.getByRole('combobox')).toBeInTheDocument();
    });
    const options = screen.getAllByRole('option');
    expect(options.length).toBeGreaterThanOrEqual(3); // "All" + 2 sources
  });

  it('fetches per-source chunks when a source is selected', async () => {
    render(<ChunksView onBack={() => {}} />);
    const select = await screen.findByRole('combobox');
    fireEvent.change(select, { target: { value: 's1' } });
    await waitFor(() => {
      expect(screen.getByText(/§800.1/)).toBeInTheDocument();
    });
  });

  it('chunks render collapsed by default; clicking expands body', async () => {
    render(<ChunksView onBack={() => {}} />);
    const select = await screen.findByRole('combobox');
    fireEvent.change(select, { target: { value: 's1' } });
    // Wait for the s1 payload (two chunks) to render.
    await screen.findByText(/§800\.1/);
    await screen.findByText(/§800\.2/);
    expect(screen.queryByText(/First chunk body/)).toBeNull();
    const row = await screen.findByRole('button', { name: /§800\.1/ });
    fireEvent.click(row);
    await waitFor(() => {
      expect(screen.getByText(/First chunk body/)).toBeInTheDocument();
    });
  });

  it('shows EMBEDDED and PENDING badges per chunk', async () => {
    render(<ChunksView onBack={() => {}} />);
    const select = await screen.findByRole('combobox');
    fireEvent.change(select, { target: { value: 's1' } });
    await screen.findByText(/§800.1/);
    expect(screen.getByText('EMBEDDED')).toBeInTheDocument();
    expect(screen.getByText('PENDING')).toBeInTheDocument();
  });

  it('defaults to All sources using the cross-source chunks endpoint', async () => {
    render(<ChunksView onBack={() => {}} />);
    await screen.findByRole('combobox');
    await waitFor(() => {
      const calls = global.fetch.mock.calls.map((c) => c[0]);
      expect(calls.some((u) => u.includes('/api/regulations/chunks') && u.includes('per_page=50'))).toBe(true);
    });
  });

  it('switches to FULL TABLE mode and renders all columns', async () => {
    render(<ChunksView onBack={() => {}} />);
    await screen.findByRole('combobox');
    fireEvent.click(screen.getByRole('tab', { name: /full table/i }));
    await waitFor(() => {
      expect(screen.getByText('breadcrumb')).toBeInTheDocument();
      expect(screen.getByText('source_id')).toBeInTheDocument();
      expect(screen.getByText('embedding')).toBeInTheDocument();
    });
  });

  it('full table mode passes source_id to the generic endpoint when filtered', async () => {
    render(<ChunksView onBack={() => {}} />);
    await screen.findByRole('combobox');
    fireEvent.click(screen.getByRole('tab', { name: /full table/i }));
    const select = screen.getByRole('combobox');
    fireEvent.change(select, { target: { value: 's1' } });
    await waitFor(() => {
      const calls = global.fetch.mock.calls.map((c) => c[0]);
      expect(calls.some((u) => u.includes('/api/db/tables/regulatory_chunks') && u.includes('source_id=s1'))).toBe(true);
    });
  });

  it('requests 50 per page', async () => {
    render(<ChunksView onBack={() => {}} />);
    await screen.findByRole('combobox');
    await waitFor(() => {
      const calls = global.fetch.mock.calls.map((c) => c[0]);
      expect(calls.some((u) => u.includes('per_page=50'))).toBe(true);
    });
  });

  it('pressing BACK calls the provided callback', async () => {
    const onBack = vi.fn();
    render(<ChunksView onBack={onBack} />);
    await screen.findByRole('combobox');
    fireEvent.click(screen.getByRole('button', { name: /back/i }));
    expect(onBack).toHaveBeenCalled();
  });
});
