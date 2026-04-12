import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import AgentPipeline from './AgentPipeline.jsx'
import { NON_LLM_AGENTS } from './ModelDropdown.jsx'

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

const extendedProps = {
  ...baseProps,
  selections: {
    project_parser: 'gemini-2.5-flash',
    environmental_data: 'gemini-2.5-flash',
    regulatory_screening: 'claude-haiku-4-5-20251001',
    impact_analysis: 'gemini-2.5-flash',
    report_synthesis: 'gemini-2.5-flash',
  },
  setSelection: vi.fn(),
  availableProviders: { openai: true, anthropic: true, gemini: true },
  modelCatalog: [
    { id: 'gemini-2.5-flash', label: 'Gemini · 2.5 Flash', provider: 'gemini' },
    { id: 'claude-haiku-4-5-20251001', label: 'Claude · Haiku 4.5', provider: 'anthropic' },
  ],
  agentCosts: {},
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

describe('AgentPipeline model dropdowns', () => {
  it('renders select dropdowns for LLM agents', () => {
    render(<AgentPipeline {...extendedProps} />)
    const selects = screen.getAllByRole('combobox')
    // project_parser and regulatory_screening are LLM agents
    expect(selects.length).toBe(2)
  })

  it('renders "no LLM" pill for non-LLM agents', () => {
    const { container } = render(<AgentPipeline {...extendedProps} />)
    const pills = container.querySelectorAll('span')
    const noLlmPills = Array.from(pills).filter((s) => s.textContent === 'no LLM')
    expect(noLlmPills.length).toBe(3)
  })
})

describe('AgentPipeline cost chips', () => {
  it('shows — when no cost data', () => {
    const { container } = render(<AgentPipeline {...extendedProps} />)
    const dashes = container.querySelectorAll('[data-testid="cost-chip"]')
    dashes.forEach((chip) => {
      expect(chip.textContent).toBe('—')
    })
  })

  it('shows cost value when agentCosts has data', () => {
    const props = {
      ...extendedProps,
      agentCosts: {
        project_parser: { cost_usd: 0.0042 },
      },
    }
    const { container } = render(<AgentPipeline {...props} />)
    expect(container.textContent).toContain('$0.0042')
  })

  it('shows TOTAL in header', () => {
    const props = {
      ...extendedProps,
      agentCosts: {
        project_parser: { cost_usd: 0.003 },
        regulatory_screening: { cost_usd: 0.001 },
      },
    }
    render(<AgentPipeline {...props} />)
    expect(screen.getByText(/TOTAL/)).toBeInTheDocument()
    expect(screen.getByText('$0.0040')).toBeInTheDocument()
  })
})
