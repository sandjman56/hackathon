import { renderHook, act, waitFor } from '@testing-library/react'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import useModelSelections, { DEFAULT_MODELS } from './useModelSelections.js'

const MOCK_PROVIDERS_RESPONSE = {
  available: { openai: true, anthropic: true, gemini: true },
  models: [
    { id: 'gpt-5.4', label: 'OpenAI · GPT-5.4', provider: 'openai', input: 2.5, output: 15.0 },
    { id: 'gemini-2.5-flash', label: 'Gemini · 2.5 Flash', provider: 'gemini', input: 0.3, output: 2.5 },
    { id: 'claude-haiku-4-5-20251001', label: 'Claude · Haiku 4.5', provider: 'anthropic', input: 1.0, output: 5.0 },
  ],
  pricing_last_updated: '2026-04-11',
}

beforeEach(() => {
  localStorage.clear()
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => MOCK_PROVIDERS_RESPONSE,
  })
})

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('useModelSelections', () => {
  it('initializes with DEFAULT_MODELS when localStorage is empty', () => {
    const { result } = renderHook(() => useModelSelections())
    expect(result.current.selections).toEqual(DEFAULT_MODELS)
  })

  it('setSelection updates state and writes to localStorage', () => {
    const { result } = renderHook(() => useModelSelections())
    act(() => {
      result.current.setSelection('project_parser', 'gpt-5.4')
    })
    expect(result.current.selections.project_parser).toBe('gpt-5.4')
    const stored = JSON.parse(localStorage.getItem('eia.model_selections'))
    expect(stored.project_parser).toBe('gpt-5.4')
  })

  it('fetches /api/providers on mount', async () => {
    renderHook(() => useModelSelections())
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/providers')
      )
    })
  })

  it('replaces stale localStorage selections with defaults', async () => {
    localStorage.setItem(
      'eia.model_selections',
      JSON.stringify({ project_parser: 'stale-model-that-no-longer-exists' })
    )
    const { result } = renderHook(() => useModelSelections())
    await waitFor(() => {
      expect(result.current.loading).toBe(false)
    })
    // stale selection replaced with default
    expect(result.current.selections.project_parser).toBe(DEFAULT_MODELS.project_parser)
  })

  it('populates availableProviders after fetch', async () => {
    const { result } = renderHook(() => useModelSelections())
    await waitFor(() => {
      expect(result.current.loading).toBe(false)
    })
    expect(result.current.availableProviders.openai).toBe(true)
    expect(result.current.availableProviders.anthropic).toBe(true)
  })

  it('populates modelCatalog after fetch', async () => {
    const { result } = renderHook(() => useModelSelections())
    await waitFor(() => {
      expect(result.current.modelCatalog.length).toBeGreaterThan(0)
    })
    expect(result.current.modelCatalog[0].id).toBe('gpt-5.4')
  })
})
