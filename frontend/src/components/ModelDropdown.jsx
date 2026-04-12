const NON_LLM_AGENTS = new Set([
  'environmental_data',
  'impact_analysis',
  'report_synthesis',
])

export { NON_LLM_AGENTS }

export default function ModelDropdown({
  agentKey,
  selections,
  setSelection,
  availableProviders,
  modelCatalog,
}) {
  if (NON_LLM_AGENTS.has(agentKey)) {
    return <span style={styles.noLlmPill}>no LLM</span>
  }

  const value = selections[agentKey] || ''

  // Group models by provider
  const grouped = {}
  for (const m of modelCatalog) {
    if (!grouped[m.provider]) grouped[m.provider] = []
    grouped[m.provider].push(m)
  }

  const providerLabels = {
    openai: 'OpenAI',
    anthropic: 'Claude',
    gemini: 'Gemini',
  }

  return (
    <select
      value={value}
      onChange={(e) => setSelection(agentKey, e.target.value)}
      style={styles.select}
    >
      {Object.entries(grouped).map(([provider, models]) => (
        <optgroup key={provider} label={providerLabels[provider] || provider}>
          {models.map((m) => (
            <option
              key={m.id}
              value={m.id}
              disabled={!availableProviders[m.provider]}
              title={
                !availableProviders[m.provider]
                  ? `${provider.toUpperCase()} API key not set on backend`
                  : undefined
              }
            >
              {m.label}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  )
}

const styles = {
  select: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--text-secondary)',
    background: 'var(--bg-primary)',
    border: '1px solid var(--border)',
    borderRadius: '4px',
    padding: '2px 4px',
    maxWidth: '140px',
    cursor: 'pointer',
    outline: 'none',
  },
  noLlmPill: {
    fontFamily: 'var(--font-mono)',
    fontSize: '9px',
    color: 'var(--text-muted)',
    padding: '2px 6px',
    border: '1px solid var(--border)',
    borderRadius: '4px',
    opacity: 0.6,
  },
}
