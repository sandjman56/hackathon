import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import AgentPipeline from './AgentPipeline.jsx'

beforeEach(() => {
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ sources: [] }),
  })
})
afterEach(() => {
  vi.restoreAllMocks()
})

const baseProps = {
  pipelineState: {
    project_parser: 'idle',
    environmental_data: 'idle',
    regulatory_screening: 'idle',
    impact_analysis: 'idle',
    report_synthesis: 'idle',
  },
  agentOutputs: {},
}

describe('AgentPipeline VIEW SOURCES button', () => {
  it('renders VIEW SOURCES on the regulatory_screening row', () => {
    render(<AgentPipeline {...baseProps} />)
    expect(screen.getByRole('button', { name: /view sources/i })).toBeInTheDocument()
  })

  it('does NOT render VIEW SOURCES on other rows', () => {
    render(<AgentPipeline {...baseProps} />)
    const buttons = screen.getAllByRole('button', { name: /view sources/i })
    expect(buttons).toHaveLength(1)
  })

  it('clicking VIEW SOURCES opens the modal', async () => {
    render(<AgentPipeline {...baseProps} />)
    fireEvent.click(screen.getByRole('button', { name: /view sources/i }))
    await waitFor(() => {
      expect(screen.getByText(/REGULATORY SOURCES/)).toBeInTheDocument()
    })
  })
})
