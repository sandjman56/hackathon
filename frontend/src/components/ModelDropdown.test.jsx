import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import ModelDropdown, { NON_LLM_AGENTS } from './ModelDropdown.jsx'

const CATALOG = [
  { id: 'gpt-5.4', label: 'OpenAI · GPT-5.4', provider: 'openai' },
  { id: 'gpt-5.4-mini', label: 'OpenAI · GPT-5.4 mini', provider: 'openai' },
  { id: 'claude-haiku-4-5-20251001', label: 'Claude · Haiku 4.5', provider: 'anthropic' },
  { id: 'gemini-2.5-flash', label: 'Gemini · 2.5 Flash', provider: 'gemini' },
]

const ALL_AVAILABLE = { openai: true, anthropic: true, gemini: true }
const PARTIAL_AVAILABLE = { openai: true, anthropic: false, gemini: true }

describe('ModelDropdown', () => {
  it('renders a <select> for LLM agents', () => {
    render(
      <ModelDropdown
        agentKey="project_parser"
        selections={{ project_parser: 'gemini-2.5-flash' }}
        setSelection={() => {}}
        availableProviders={ALL_AVAILABLE}
        modelCatalog={CATALOG}
      />
    )
    expect(screen.getByRole('combobox')).toBeInTheDocument()
  })

  it('renders "no LLM" pill for non-LLM agents', () => {
    for (const agent of NON_LLM_AGENTS) {
      const { container } = render(
        <ModelDropdown
          agentKey={agent}
          selections={{}}
          setSelection={() => {}}
          availableProviders={ALL_AVAILABLE}
          modelCatalog={CATALOG}
        />
      )
      expect(container.textContent).toContain('no LLM')
    }
  })

  it('renders options grouped by provider', () => {
    render(
      <ModelDropdown
        agentKey="project_parser"
        selections={{ project_parser: 'gemini-2.5-flash' }}
        setSelection={() => {}}
        availableProviders={ALL_AVAILABLE}
        modelCatalog={CATALOG}
      />
    )
    const options = screen.getAllByRole('option')
    expect(options.length).toBe(CATALOG.length)
  })

  it('disables options when provider unavailable', () => {
    render(
      <ModelDropdown
        agentKey="project_parser"
        selections={{ project_parser: 'gemini-2.5-flash' }}
        setSelection={() => {}}
        availableProviders={PARTIAL_AVAILABLE}
        modelCatalog={CATALOG}
      />
    )
    const haiku = screen.getByRole('option', { name: 'Claude · Haiku 4.5' })
    expect(haiku).toBeDisabled()
  })

  it('calls setSelection on change', () => {
    const spy = vi.fn()
    render(
      <ModelDropdown
        agentKey="project_parser"
        selections={{ project_parser: 'gemini-2.5-flash' }}
        setSelection={spy}
        availableProviders={ALL_AVAILABLE}
        modelCatalog={CATALOG}
      />
    )
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'gpt-5.4' } })
    expect(spy).toHaveBeenCalledWith('project_parser', 'gpt-5.4')
  })
})
