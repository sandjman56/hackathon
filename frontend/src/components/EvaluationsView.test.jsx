import { render, screen, waitFor, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import EvaluationsView from './EvaluationsView.jsx'

function jsonRes(body, ok = true, status = 200) {
  return Promise.resolve({
    ok, status, json: () => Promise.resolve(body),
  })
}

describe('EvaluationsView', () => {
  let originalFetch
  beforeEach(() => {
    originalFetch = global.fetch
    vi.useFakeTimers()
  })
  afterEach(() => {
    global.fetch = originalFetch
    vi.useRealTimers()
  })

  it('renders status pill and progress for an embedding row', async () => {
    global.fetch = vi.fn(() => jsonRes({
      documents: [{
        id: 1, filename: 'x.pdf', sha256: 'abc', size_bytes: 2048,
        uploaded_at: new Date().toISOString(),
        status: 'embedding', chunks_total: 10, chunks_embedded: 4,
        status_message: null,
      }],
    }))
    render(<EvaluationsView onBack={() => {}} onOpenChunks={() => {}} />)
    await waitFor(() => expect(screen.getByText(/EMBEDDING/i)).toBeTruthy())
    expect(screen.getByText(/4\s*\/\s*10/)).toBeTruthy()
  })

  it('shows RETRY only on failed rows', async () => {
    global.fetch = vi.fn(() => jsonRes({
      documents: [
        { id: 1, filename: 'a.pdf', status: 'ready', chunks_total: 3,
          chunks_embedded: 3, size_bytes: 10, uploaded_at: new Date().toISOString() },
        { id: 2, filename: 'b.pdf', status: 'failed', chunks_total: 0,
          chunks_embedded: 0, size_bytes: 10, uploaded_at: new Date().toISOString(),
          status_message: 'bad pdf' },
      ],
    }))
    render(<EvaluationsView onBack={() => {}} onOpenChunks={() => {}} />)
    await waitFor(() => expect(screen.getAllByRole('row').length).toBeGreaterThan(1))
    const retryBtns = screen.getAllByText(/RETRY/i)
    expect(retryBtns).toHaveLength(1)
  })

  it('stops polling on unmount', async () => {
    const fetchSpy = vi.fn(() => jsonRes({
      documents: [{ id: 1, filename: 'a.pdf', status: 'embedding',
        chunks_total: 5, chunks_embedded: 1, size_bytes: 10,
        uploaded_at: new Date().toISOString() }],
    }))
    global.fetch = fetchSpy
    const { unmount } = render(<EvaluationsView onBack={() => {}} onOpenChunks={() => {}} />)
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled())
    const before = fetchSpy.mock.calls.length
    unmount()
    act(() => { vi.advanceTimersByTime(10000) })
    expect(fetchSpy.mock.calls.length).toBe(before)
  })
})
