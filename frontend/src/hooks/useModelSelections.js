import { useState, useEffect } from 'react'

const DEFAULT_MODELS = {
  project_parser: 'gemini-2.5-flash',
  environmental_data: 'gemini-2.5-flash',
  regulatory_screening: 'claude-haiku-4-5-20251001',
  impact_analysis: 'gemini-2.5-flash',
  report_synthesis: 'gemini-2.5-flash',
}

const STORAGE_KEY = 'eia.model_selections'

export default function useModelSelections() {
  const [selections, setSelections] = useState(() => {
    try {
      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY))
      return { ...DEFAULT_MODELS, ...stored }
    } catch {
      return { ...DEFAULT_MODELS }
    }
  })
  const [availableProviders, setAvailableProviders] = useState({})
  const [modelCatalog, setModelCatalog] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const apiBase = import.meta.env.VITE_API_URL ?? ''
    fetch(`${apiBase}/api/providers`)
      .then((r) => r.json())
      .then((data) => {
        setAvailableProviders(data.available || {})
        setModelCatalog(data.models || [])
        // Validate stored selections against catalog
        const validIds = new Set((data.models || []).map((m) => m.id))
        setSelections((prev) => {
          const cleaned = { ...prev }
          for (const [agent, modelId] of Object.entries(cleaned)) {
            if (!validIds.has(modelId)) {
              cleaned[agent] = DEFAULT_MODELS[agent]
            }
          }
          localStorage.setItem(STORAGE_KEY, JSON.stringify(cleaned))
          return cleaned
        })
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const setSelection = (agentKey, modelId) => {
    setSelections((prev) => {
      const next = { ...prev, [agentKey]: modelId }
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
      return next
    })
  }

  return { selections, setSelection, availableProviders, modelCatalog, loading }
}

export { DEFAULT_MODELS }
