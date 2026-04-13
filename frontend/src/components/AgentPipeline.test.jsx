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
    // project_parser, regulatory_screening, and impact_analysis are LLM agents
    expect(selects.length).toBe(3)
  })

  it('renders "no LLM" pill for non-LLM agents', () => {
    const { container } = render(<AgentPipeline {...extendedProps} />)
    const pills = container.querySelectorAll('span')
    const noLlmPills = Array.from(pills).filter((s) => s.textContent === 'no LLM')
    expect(noLlmPills.length).toBe(2)
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

describe('AgentPipeline impact matrix dropdown', () => {
  it('renders impact cells when impact_analysis card is clicked', () => {
    const impactMatrix = {
      actions: ['land clearing', 'construction'],
      categories: ['wetlands'],
      cells: [
        {
          action: 'land clearing',
          category: 'wetlands',
          framework: 'Clean Water Act',
          determination: {
            significance: 'significant',
            confidence: 0.85,
            reasoning: 'Direct wetland fill impact',
            mitigation: ['avoidance', 'compensatory'],
            needs_review: false,
          },
        },
        {
          action: 'construction',
          category: 'wetlands',
          framework: 'Clean Water Act',
          determination: {
            significance: 'moderate',
            confidence: 0.72,
            reasoning: 'Runoff during construction phase',
            mitigation: ['minimization'],
            needs_review: false,
          },
        },
      ],
      rag_fallbacks: [],
    }

    const props = {
      ...extendedProps,
      pipelineState: { ...extendedProps.pipelineState, impact_analysis: 'complete' },
      agentOutputs: { impact_analysis: impactMatrix },
    }
    render(<AgentPipeline {...props} />)

    // Click the impact analysis card to open dropdown
    fireEvent.click(screen.getByText('IMPACT ANALYSIS'))

    // Verify cell data renders
    expect(screen.getByText('wetlands')).toBeInTheDocument()
    expect(screen.getByText('significant')).toBeInTheDocument()
    expect(screen.getByText('85%')).toBeInTheDocument()
    expect(screen.getByText('Direct wetland fill impact')).toBeInTheDocument()
  })

  it('shows empty message when impact matrix has no cells', () => {
    const props = {
      ...extendedProps,
      pipelineState: { ...extendedProps.pipelineState, impact_analysis: 'complete' },
      agentOutputs: { impact_analysis: { actions: [], categories: [], cells: [], rag_fallbacks: [] } },
    }
    render(<AgentPipeline {...props} />)
    fireEvent.click(screen.getByText('IMPACT ANALYSIS'))
    expect(screen.getByText('No impact data')).toBeInTheDocument()
  })
})
