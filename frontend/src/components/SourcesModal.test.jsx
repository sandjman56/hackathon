import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import SourcesModal from './SourcesModal.jsx'

const mkRow = (overrides = {}) => ({
  id: 'id-1',
  filename: 'NEPA-40CFR1500_1508.pdf',
  sha256: 'a'.repeat(64),
  size_bytes: 1_800_000,
  uploaded_at: '2026-04-09T20:00:00Z',
  status: 'ready',
  status_message: null,
  chunks_total: 247,
  chunks_embedded: 247,
  chunk_count: 247,
  sections_count: 9,
  parser_warnings: 0,
  embedding_dim: 768,
  embedding_started_at: '2026-04-09T20:00:00Z',
  embedding_finished_at: '2026-04-09T20:01:30Z',
  is_current: true,
  ...overrides,
})

beforeEach(() => {
  global.fetch = vi.fn()
})
afterEach(() => {
  vi.restoreAllMocks()
})

const mockListResponse = (sources) => {
  global.fetch.mockResolvedValueOnce({
    ok: true,
    json: async () => ({ sources }),
  })
}

describe('SourcesModal', () => {
  it('renders loading state then empty', async () => {
    mockListResponse([])
    render(<SourcesModal onClose={() => {}} />)
    expect(screen.getByText(/loading/i)).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByText(/no sources yet/i)).toBeInTheDocument()
    })
  })

  it('renders a ready row with chunk count and DELETE', async () => {
    mockListResponse([mkRow()])
    render(<SourcesModal onClose={() => {}} />)
    await waitFor(() => {
      expect(screen.getByText('NEPA-40CFR1500_1508.pdf')).toBeInTheDocument()
    })
    expect(screen.getByText(/247 chunks/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /delete/i })).toBeInTheDocument()
  })

  it('renders an embedding row with progress bar and counters', async () => {
    const row = mkRow({
      status: 'embedding',
      chunks_embedded: 87,
      chunks_total: 247,
    })
    mockListResponse([row])
    render(<SourcesModal onClose={() => {}} />)
    await waitFor(() => {
      expect(screen.getByText(/87 \/ 247/)).toBeInTheDocument()
    })
    const bar = screen.getByTestId('progress-bar-fill-id-1')
    // 87/247 = 0.352 → "35.2%"
    expect(bar.style.width).toMatch(/^35\./)
  })

  it('renders a failed row with status_message', async () => {
    mockListResponse([mkRow({
      status: 'failed',
      status_message: 'Not a NEPA-style PDF (no CFR sections detected)',
    })])
    render(<SourcesModal onClose={() => {}} />)
    await waitFor(() => {
      expect(screen.getByText(/no CFR sections/i)).toBeInTheDocument()
    })
  })

  it('drop zone: dropping a PDF calls upload endpoint', async () => {
    mockListResponse([])
    // Second fetch is the upload itself
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mkRow({ status: 'pending' }),
    })
    // Third fetch: refetch list after upload
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ sources: [mkRow({ status: 'pending' })] }),
    })

    render(<SourcesModal onClose={() => {}} />)
    await waitFor(() => screen.getByText(/no sources yet/i))

    const file = new File(['%PDF-1.4 fake'], 'test.pdf', { type: 'application/pdf' })
    const dropZone = screen.getByTestId('drop-zone')
    fireEvent.drop(dropZone, {
      dataTransfer: { files: [file], types: ['Files'] },
    })

    await waitFor(() => {
      const calls = global.fetch.mock.calls
      const uploadCall = calls.find(
        (c) => typeof c[1] === 'object' && c[1]?.method === 'POST'
      )
      expect(uploadCall).toBeTruthy()
      expect(uploadCall[0]).toMatch(/\/api\/regulations\/sources$/)
    })
  })

  it('drop zone: dropping a non-PDF shows an error and does NOT call upload', async () => {
    mockListResponse([])
    render(<SourcesModal onClose={() => {}} />)
    await waitFor(() => screen.getByText(/no sources yet/i))

    const file = new File(['hi'], 'foo.txt', { type: 'text/plain' })
    fireEvent.drop(screen.getByTestId('drop-zone'), {
      dataTransfer: { files: [file], types: ['Files'] },
    })

    await waitFor(() => {
      expect(screen.getByText(/must be a pdf/i)).toBeInTheDocument()
    })
    // Only the initial GET ran
    expect(global.fetch.mock.calls.length).toBe(1)
  })

  it('clicking DELETE sends DELETE and removes the row', async () => {
    mockListResponse([mkRow()])
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ deleted_chunks: 247 }),
    })
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ sources: [] }),
    })

    render(<SourcesModal onClose={() => {}} />)
    await waitFor(() => screen.getByText('NEPA-40CFR1500_1508.pdf'))
    fireEvent.click(screen.getByRole('button', { name: /delete/i }))
    fireEvent.click(screen.getByRole('button', { name: /confirm delete/i }))

    await waitFor(() => {
      expect(screen.queryByText('NEPA-40CFR1500_1508.pdf')).toBeNull()
    })
  })

  it('polls every 2s while a row is in embedding', async () => {
    vi.useFakeTimers()
    try {
      const embedding = mkRow({ status: 'embedding', chunks_embedded: 10, chunks_total: 100 })
      // initial fetch
      global.fetch.mockResolvedValueOnce({ ok: true, json: async () => ({ sources: [embedding] }) })
      // poll fetch
      global.fetch.mockResolvedValueOnce({ ok: true, json: async () => ({ sources: [embedding] }) })

      render(<SourcesModal onClose={() => {}} />)
      await waitFor(() => screen.getByText(/10 \/ 100/))

      const before = global.fetch.mock.calls.length
      await act(async () => {
        vi.advanceTimersByTime(2100)
      })
      expect(global.fetch.mock.calls.length).toBeGreaterThan(before)
    } finally {
      vi.useRealTimers()
    }
  })
})
