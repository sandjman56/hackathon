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
const chunksPayload = {
  source_id: 's1', page: 1, per_page: 25, total: 2, total_pages: 1,
  chunks: [
    { id: 'c1', content: 'First chunk body…',
      citation: '36 CFR §800.1', breadcrumb: 'Part 800 > Purpose',
      token_count: 500, metadata: {} },
    { id: 'c2', content: 'Second chunk body…',
      citation: '36 CFR §800.2', breadcrumb: 'Part 800 > Participants',
      token_count: 420, metadata: {} },
  ],
};

beforeEach(() => {
  global.fetch = vi.fn((url) => {
    if (url.endsWith('/api/regulations/sources')) {
      return Promise.resolve({ ok: true, json: async () => sourcesPayload });
    }
    if (url.includes('/api/regulations/sources/s1/chunks')) {
      return Promise.resolve({ ok: true, json: async () => chunksPayload });
    }
    if (url.includes('/api/db/tables/regulatory_chunks')) {
      return Promise.resolve({
        ok: true,
        json: async () => ({
          page: 1,
          per_page: 25,
          total_rows: 0,
          total_pages: 0,
          columns: [{ name: 'content' }, { name: 'metadata' }],
          rows: [],
        }),
      });
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
    const row = await screen.findByText(/§800.1/);
    // collapsed: body text not visible
    expect(screen.queryByText(/First chunk body/)).toBeNull();
    fireEvent.click(row);
    await waitFor(() => {
      expect(screen.getByText(/First chunk body/)).toBeInTheDocument();
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
