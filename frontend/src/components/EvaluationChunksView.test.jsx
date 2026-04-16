import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import EvaluationChunksView from './EvaluationChunksView.jsx'

function jsonRes(body) {
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) })
}

describe('EvaluationChunksView', () => {
  let orig
  beforeEach(() => { orig = global.fetch })
  afterEach(() => { global.fetch = orig })

  it('renders chunk labels and breadcrumbs', async () => {
    global.fetch = vi.fn(() => jsonRes({
      evaluation_id: 1, page: 1, per_page: 25, total: 2, total_pages: 1,
      chunks: [
        { id: 'a', chunk_label: 'sample §1.1 [p.1] (1/1)',
          breadcrumb: 'Chapter 1 > 1.1 Overview', content: 'body',
          page_start: 1, page_end: 1, metadata: {} },
        { id: 'b', chunk_label: 'sample §4.1 [p.2-3] (1/1)',
          breadcrumb: 'Chapter 4 > 4.1 Water', content: 'body2',
          page_start: 2, page_end: 3, metadata: {} },
      ],
    }))
    render(<EvaluationChunksView
      evaluationId={1} filename="sample.pdf" onBack={() => {}} />)
    await waitFor(() => expect(screen.getByText(/1\.1 Overview/)).toBeTruthy())
    expect(screen.getByText(/sample §1\.1/)).toBeTruthy()
    expect(screen.getByText(/sample §4\.1/)).toBeTruthy()
  })

  it('calls onBack when back button clicked', async () => {
    global.fetch = vi.fn(() => jsonRes({
      evaluation_id: 1, page: 1, per_page: 25, total: 0, total_pages: 0, chunks: [],
    }))
    const onBack = vi.fn()
    render(<EvaluationChunksView evaluationId={1} filename="x.pdf" onBack={onBack} />)
    await waitFor(() => expect(screen.getByText(/NO CHUNKS/i)).toBeTruthy())
    fireEvent.click(screen.getByText(/BACK/))
    expect(onBack).toHaveBeenCalled()
  })
})
